"""
Exchange Rate Service
Handles fetching exchange rates from external API and caching.
"""
import httpx
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models import ExchangeRate, ExchangeRateLog, Company

logger = logging.getLogger(__name__)

# In-memory cache for exchange rates
_rate_cache: Dict[str, Dict[str, Any]] = {}
CACHE_DURATION = timedelta(hours=1)

# Exchange rate API configuration
# Using exchangerate-api.com free tier
EXCHANGE_RATE_API_BASE = "https://api.exchangerate-api.com/v4/latest"


class ExchangeRateService:
    """Service for managing exchange rates"""

    @staticmethod
    async def fetch_rates_from_api(base_currency: str) -> Optional[Dict[str, Decimal]]:
        """
        Fetch exchange rates from external API.
        Returns dict of currency_code -> rate
        """
        cache_key = f"api_{base_currency}"

        # Check cache first
        if cache_key in _rate_cache:
            cached = _rate_cache[cache_key]
            if datetime.utcnow() < cached["expires_at"]:
                logger.debug(f"Using cached rates for {base_currency}")
                return cached["rates"]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{EXCHANGE_RATE_API_BASE}/{base_currency}")

                if response.status_code != 200:
                    logger.error(f"Exchange rate API error: {response.status_code}")
                    return None

                data = response.json()
                rates = {
                    code: Decimal(str(rate))
                    for code, rate in data.get("rates", {}).items()
                }

                # Cache the results
                _rate_cache[cache_key] = {
                    "rates": rates,
                    "expires_at": datetime.utcnow() + CACHE_DURATION,
                    "fetched_at": datetime.utcnow()
                }

                logger.info(f"Fetched {len(rates)} exchange rates for {base_currency}")
                return rates

        except Exception as e:
            logger.error(f"Error fetching exchange rates: {e}")
            return None

    @staticmethod
    async def get_rate(
        db: Session,
        company_id: int,
        from_currency: str,
        to_currency: str
    ) -> Optional[Decimal]:
        """
        Get exchange rate between two currencies.
        First checks for manual override in DB, then falls back to API.
        """
        # Same currency, rate is 1
        if from_currency.upper() == to_currency.upper():
            return Decimal("1")

        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        # Check for manual override in database
        manual_rate = db.query(ExchangeRate).filter(
            ExchangeRate.company_id == company_id,
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
            ExchangeRate.source == "manual",
            ExchangeRate.is_active == True
        ).first()

        if manual_rate:
            logger.debug(f"Using manual rate for {from_currency}/{to_currency}: {manual_rate.rate}")
            return manual_rate.rate

        # Fetch from API
        rates = await ExchangeRateService.fetch_rates_from_api(from_currency)
        if rates and to_currency in rates:
            return rates[to_currency]

        # Try inverse rate
        inverse_rates = await ExchangeRateService.fetch_rates_from_api(to_currency)
        if inverse_rates and from_currency in inverse_rates:
            inverse_rate = inverse_rates[from_currency]
            if inverse_rate > 0:
                return Decimal("1") / inverse_rate

        logger.warning(f"Could not find rate for {from_currency}/{to_currency}")
        return None

    @staticmethod
    async def convert_amount(
        db: Session,
        company_id: int,
        amount: Decimal,
        from_currency: str,
        to_currency: str
    ) -> Optional[Decimal]:
        """Convert an amount from one currency to another"""
        rate = await ExchangeRateService.get_rate(db, company_id, from_currency, to_currency)
        if rate is None:
            return None
        return amount * rate

    @staticmethod
    def set_manual_rate(
        db: Session,
        company_id: int,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        user_email: str
    ) -> ExchangeRate:
        """Set a manual exchange rate override"""
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        # Check if rate already exists
        existing = db.query(ExchangeRate).filter(
            ExchangeRate.company_id == company_id,
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency
        ).first()

        if existing:
            existing.rate = rate
            existing.source = "manual"
            existing.effective_date = datetime.utcnow().date()
            existing.updated_at = datetime.utcnow()
        else:
            existing = ExchangeRate(
                company_id=company_id,
                from_currency=from_currency,
                to_currency=to_currency,
                rate=rate,
                source="manual",
                effective_date=datetime.utcnow().date()
            )
            db.add(existing)

        # Log the change
        log_entry = ExchangeRateLog(
            company_id=company_id,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            source="manual",
            api_provider=f"Manual override by {user_email}"
        )
        db.add(log_entry)

        db.commit()
        db.refresh(existing)

        # Invalidate cache for this currency pair
        cache_key = f"api_{from_currency}"
        if cache_key in _rate_cache:
            del _rate_cache[cache_key]

        logger.info(f"Manual rate set: {from_currency}/{to_currency} = {rate}")
        return existing

    @staticmethod
    def delete_manual_rate(
        db: Session,
        company_id: int,
        from_currency: str,
        to_currency: str
    ) -> bool:
        """Delete a manual rate override (reverts to API rate)"""
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        existing = db.query(ExchangeRate).filter(
            ExchangeRate.company_id == company_id,
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
            ExchangeRate.source == "manual"
        ).first()

        if existing:
            db.delete(existing)
            db.commit()
            logger.info(f"Manual rate deleted: {from_currency}/{to_currency}")
            return True

        return False

    @staticmethod
    async def refresh_rates(
        db: Session,
        company_id: int,
        base_currency: str
    ) -> Dict[str, Any]:
        """
        Force refresh rates from API and store in database.
        Also logs the fetch for history.
        """
        base_currency = base_currency.upper()

        # Clear cache
        cache_key = f"api_{base_currency}"
        if cache_key in _rate_cache:
            del _rate_cache[cache_key]

        # Fetch fresh rates
        rates = await ExchangeRateService.fetch_rates_from_api(base_currency)

        if not rates:
            return {"success": False, "message": "Failed to fetch rates from API"}

        # Get company's supported currencies
        from app.api.companies import SUPPORTED_CURRENCIES
        supported_codes = [c["code"] for c in SUPPORTED_CURRENCIES]

        stored_count = 0
        for to_currency, rate in rates.items():
            if to_currency not in supported_codes:
                continue
            if to_currency == base_currency:
                continue

            # Log the fetch
            log_entry = ExchangeRateLog(
                company_id=company_id,
                from_currency=base_currency,
                to_currency=to_currency,
                rate=rate,
                source="api",
                api_provider="exchangerate-api.com"
            )
            db.add(log_entry)
            stored_count += 1

        db.commit()

        return {
            "success": True,
            "message": f"Refreshed {stored_count} exchange rates",
            "rates_count": stored_count,
            "base_currency": base_currency
        }

    @staticmethod
    def get_rate_history(
        db: Session,
        company_id: int,
        from_currency: Optional[str] = None,
        to_currency: Optional[str] = None,
        limit: int = 100
    ):
        """Get exchange rate history/logs"""
        query = db.query(ExchangeRateLog).filter(
            ExchangeRateLog.company_id == company_id
        )

        if from_currency:
            query = query.filter(ExchangeRateLog.from_currency == from_currency.upper())
        if to_currency:
            query = query.filter(ExchangeRateLog.to_currency == to_currency.upper())

        return query.order_by(ExchangeRateLog.fetched_at.desc()).limit(limit).all()

    @staticmethod
    def get_manual_rates(db: Session, company_id: int):
        """Get all manual rate overrides for a company"""
        return db.query(ExchangeRate).filter(
            ExchangeRate.company_id == company_id,
            ExchangeRate.source == "manual",
            ExchangeRate.is_active == True
        ).all()
