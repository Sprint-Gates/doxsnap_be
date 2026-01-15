"""
Multi-tenant Redis Cache Service

Supports both local Redis and Upstash REST API.

CRITICAL: All cache operations MUST include company_id in the key
to ensure strict tenant isolation between companies.

Usage:
    from app.services.cache import cache_service

    # In startup
    await cache_service.connect()

    # Get cached data
    data = await cache_service.get_items_page(company_id, page, page_size, filters_hash)

    # Set cached data
    await cache_service.set_items_page(company_id, page, page_size, filters_hash, data)

    # Invalidate on mutations
    await cache_service.invalidate_items(company_id)
"""
import json
import logging
import hashlib
import aiohttp
from typing import Optional, Any, List
from decimal import Decimal

logger = logging.getLogger(__name__)


def _json_serializer(obj):
    """Custom JSON serializer for types not serializable by default"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class CacheService:
    """
    Thread-safe, multi-tenant aware caching service.

    Supports both local Redis and Upstash REST API.
    All cache keys are namespaced by company_id to ensure strict
    tenant isolation. Cache gracefully degrades if Redis is unavailable.
    """

    def __init__(self):
        self._redis = None
        self._connected = False
        self._use_upstash = False
        self._upstash_url = None
        self._upstash_token = None

    async def connect(self):
        """Initialize Redis connection (local or Upstash)"""
        from app.config import settings

        if not settings.cache_enabled:
            logger.info("Redis cache disabled by configuration (CACHE_ENABLED=false)")
            return

        # Check if Upstash is configured
        if settings.use_upstash:
            await self._connect_upstash(settings)
        else:
            await self._connect_local_redis(settings)

    async def _connect_upstash(self, settings):
        """Connect to Upstash Redis REST API"""
        try:
            self._upstash_url = settings.upstash_redis_rest_url
            self._upstash_token = settings.upstash_redis_rest_token
            self._use_upstash = True

            # Test connection with PING
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._upstash_url}/ping",
                    headers={"Authorization": f"Bearer {self._upstash_token}"}
                ) as response:
                    if response.status == 200:
                        self._connected = True
                        logger.info(f"Upstash Redis connected successfully to {self._upstash_url}")
                    else:
                        raise Exception(f"Upstash PING failed: {response.status}")
        except Exception as e:
            logger.warning(f"Failed to connect to Upstash Redis (caching disabled): {e}")
            self._connected = False
            self._use_upstash = False

    async def _connect_local_redis(self, settings):
        """Connect to local Redis server"""
        try:
            import redis.asyncio as redis_async

            self._redis = redis_async.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self._redis.ping()
            self._connected = True
            logger.info(f"Redis cache connected successfully to {settings.redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis (caching disabled): {e}")
            self._redis = None
            self._connected = False

    async def disconnect(self):
        """Close Redis connection"""
        if self._redis and not self._use_upstash:
            await self._redis.close()
        self._connected = False
        logger.info("Redis cache connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected and available"""
        if self._use_upstash:
            return self._connected and self._upstash_url is not None
        return self._connected and self._redis is not None

    def _key(self, company_id: int, *parts: str) -> str:
        """
        Generate tenant-isolated cache key.

        CRITICAL: company_id is ALWAYS the first component to ensure
        no data leakage between tenants.
        """
        return f"company:{company_id}:" + ":".join(str(p) for p in parts)

    async def _upstash_request(self, command: list) -> Any:
        """Execute Upstash REST API request"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._upstash_url,
                    headers={
                        "Authorization": f"Bearer {self._upstash_token}",
                        "Content-Type": "application/json"
                    },
                    json=command
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("result")
                    else:
                        text = await response.text()
                        logger.warning(f"Upstash request failed: {response.status} - {text}")
                        return None
        except Exception as e:
            logger.warning(f"Upstash request error: {e}")
            return None

    async def get(self, company_id: int, *key_parts: str) -> Optional[Any]:
        """Get cached value for a specific company"""
        if not self.is_connected:
            return None
        try:
            key = self._key(company_id, *key_parts)

            if self._use_upstash:
                data = await self._upstash_request(["GET", key])
            else:
                data = await self._redis.get(key)

            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None

    async def set(
        self,
        company_id: int,
        *key_parts: str,
        value: Any,
        ttl: int = None
    ):
        """Set cached value for a specific company with TTL"""
        if not self.is_connected:
            return
        try:
            from app.config import settings
            key = self._key(company_id, *key_parts)
            ttl = ttl or settings.cache_default_ttl
            json_value = json.dumps(value, default=_json_serializer)

            if self._use_upstash:
                await self._upstash_request(["SETEX", key, ttl, json_value])
            else:
                await self._redis.setex(key, ttl, json_value)

            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
        except Exception as e:
            logger.warning(f"Cache set error: {e}")

    async def delete(self, company_id: int, *key_parts: str):
        """Delete specific cached value"""
        if not self.is_connected:
            return
        try:
            key = self._key(company_id, *key_parts)

            if self._use_upstash:
                await self._upstash_request(["DEL", key])
            else:
                await self._redis.delete(key)

            logger.debug(f"Cache DELETE: {key}")
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")

    async def invalidate_pattern(self, company_id: int, pattern: str):
        """
        Delete all keys matching pattern for a specific company.

        Uses SCAN for production safety (non-blocking).
        """
        if not self.is_connected:
            return
        try:
            full_pattern = f"company:{company_id}:{pattern}"

            if self._use_upstash:
                # Upstash: Use SCAN to find keys, then delete
                cursor = "0"
                all_keys = []
                while True:
                    result = await self._upstash_request(["SCAN", cursor, "MATCH", full_pattern, "COUNT", "100"])
                    if result:
                        cursor = result[0]
                        keys = result[1] if len(result) > 1 else []
                        all_keys.extend(keys)
                        if cursor == "0":
                            break
                    else:
                        break

                if all_keys:
                    await self._upstash_request(["DEL", *all_keys])
                    logger.info(f"Cache INVALIDATE: {len(all_keys)} keys matching '{full_pattern}'")
            else:
                keys = []
                async for key in self._redis.scan_iter(match=full_pattern):
                    keys.append(key)
                if keys:
                    await self._redis.delete(*keys)
                    logger.info(f"Cache INVALIDATE: {len(keys)} keys matching '{full_pattern}'")
        except Exception as e:
            logger.warning(f"Cache invalidate error: {e}")

    # ================================================================
    # Item Master Cache Methods
    # ================================================================

    async def get_items_page(
        self,
        company_id: int,
        page: int,
        page_size: int,
        filters_hash: str
    ) -> Optional[dict]:
        """Get cached paginated items list"""
        return await self.get(
            company_id, "items", f"p{page}", f"s{page_size}", filters_hash
        )

    async def set_items_page(
        self,
        company_id: int,
        page: int,
        page_size: int,
        filters_hash: str,
        data: dict
    ):
        """Cache paginated items list (5 min TTL)"""
        await self.set(
            company_id, "items", f"p{page}", f"s{page_size}", filters_hash,
            value=data,
            ttl=300  # 5 minutes
        )

    async def get_item_detail(self, company_id: int, item_id: int) -> Optional[dict]:
        """Get cached single item details"""
        return await self.get(company_id, "item", str(item_id))

    async def set_item_detail(self, company_id: int, item_id: int, data: dict):
        """Cache single item details (10 min TTL)"""
        await self.set(
            company_id, "item", str(item_id),
            value=data,
            ttl=600  # 10 minutes
        )

    async def invalidate_items(self, company_id: int):
        """Invalidate all item caches for a company"""
        await self.invalidate_pattern(company_id, "items:*")
        await self.invalidate_pattern(company_id, "item:*")

    async def invalidate_item(self, company_id: int, item_id: int):
        """Invalidate specific item and list caches"""
        await self.delete(company_id, "item", str(item_id))
        await self.invalidate_pattern(company_id, "items:*")

    # ================================================================
    # Warehouse Stock Cache Methods
    # ================================================================

    async def get_warehouse_stock(
        self,
        company_id: int,
        warehouse_id: int
    ) -> Optional[dict]:
        """Get cached warehouse stock levels"""
        return await self.get(company_id, "warehouse", str(warehouse_id), "stock")

    async def set_warehouse_stock(
        self,
        company_id: int,
        warehouse_id: int,
        data: dict
    ):
        """Cache warehouse stock (2 min TTL - changes frequently)"""
        await self.set(
            company_id, "warehouse", str(warehouse_id), "stock",
            value=data,
            ttl=120  # 2 minutes
        )

    async def invalidate_warehouse_stock(self, company_id: int, warehouse_id: int):
        """Invalidate stock cache for specific warehouse"""
        await self.delete(company_id, "warehouse", str(warehouse_id), "stock")

    async def invalidate_all_stock(self, company_id: int):
        """Invalidate all stock caches for a company"""
        await self.invalidate_pattern(company_id, "warehouse:*:stock")
        await self.invalidate_pattern(company_id, "hhd:*:stock")

    # ================================================================
    # HHD Stock Cache Methods
    # ================================================================

    async def get_hhd_stock(
        self,
        company_id: int,
        hhd_id: int
    ) -> Optional[dict]:
        """Get cached HHD stock levels"""
        return await self.get(company_id, "hhd", str(hhd_id), "stock")

    async def set_hhd_stock(
        self,
        company_id: int,
        hhd_id: int,
        data: dict
    ):
        """Cache HHD stock (2 min TTL)"""
        await self.set(
            company_id, "hhd", str(hhd_id), "stock",
            value=data,
            ttl=120  # 2 minutes
        )

    async def invalidate_hhd_stock(self, company_id: int, hhd_id: int):
        """Invalidate stock cache for specific HHD"""
        await self.delete(company_id, "hhd", str(hhd_id), "stock")

    # ================================================================
    # Item Ledger Cache Methods
    # ================================================================

    async def get_item_ledger(
        self,
        company_id: int,
        item_id: int,
        filters_hash: str
    ) -> Optional[List]:
        """Get cached ledger entries for an item"""
        return await self.get(company_id, "item", str(item_id), "ledger", filters_hash)

    async def set_item_ledger(
        self,
        company_id: int,
        item_id: int,
        filters_hash: str,
        data: List
    ):
        """Cache ledger entries (15 min TTL - append-only data)"""
        await self.set(
            company_id, "item", str(item_id), "ledger", filters_hash,
            value=data,
            ttl=900  # 15 minutes
        )

    async def get_ledger_list(
        self,
        company_id: int,
        filters_hash: str
    ) -> Optional[dict]:
        """Get cached ledger list (all items)"""
        return await self.get(company_id, "ledger", filters_hash)

    async def set_ledger_list(
        self,
        company_id: int,
        filters_hash: str,
        data: dict
    ):
        """Cache ledger list (10 min TTL)"""
        await self.set(
            company_id, "ledger", filters_hash,
            value=data,
            ttl=600  # 10 minutes
        )

    async def invalidate_ledger(self, company_id: int, item_id: Optional[int] = None):
        """Invalidate ledger caches"""
        if item_id:
            await self.invalidate_pattern(company_id, f"item:{item_id}:ledger:*")
        await self.invalidate_pattern(company_id, "ledger:*")

    # ================================================================
    # Invoice Item Suggestions Cache Methods
    # ================================================================

    async def get_invoice_suggestions(
        self,
        company_id: int,
        invoice_item_id: int
    ) -> Optional[dict]:
        """Get cached suggestions for an invoice item"""
        return await self.get(company_id, "invoice_suggestions", str(invoice_item_id))

    async def set_invoice_suggestions(
        self,
        company_id: int,
        invoice_item_id: int,
        data: dict
    ):
        """Cache invoice item suggestions (5 min TTL)"""
        await self.set(
            company_id, "invoice_suggestions", str(invoice_item_id),
            value=data,
            ttl=300  # 5 minutes
        )

    async def invalidate_invoice_suggestions(self, company_id: int, invoice_item_id: Optional[int] = None):
        """Invalidate invoice suggestions cache"""
        if invoice_item_id:
            await self.delete(company_id, "invoice_suggestions", str(invoice_item_id))
        else:
            await self.invalidate_pattern(company_id, "invoice_suggestions:*")


# ================================================================
# Helper Functions
# ================================================================

def hash_filters(**filters) -> str:
    """
    Create a short hash of filter parameters for cache key.

    Filters are sorted to ensure consistent hashing regardless
    of parameter order.
    """
    # Filter out None values and sort
    filtered = {k: v for k, v in filters.items() if v is not None}
    sorted_filters = sorted(filtered.items())
    hash_input = str(sorted_filters).encode()
    return hashlib.md5(hash_input).hexdigest()[:8]


# Global cache instance - import this in other modules
cache_service = CacheService()
