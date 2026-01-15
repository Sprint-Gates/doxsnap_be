# Rate Limiting Documentation

## Overview

CoreSRP implements rate limiting to protect against brute force attacks, API abuse, and denial of service attempts. The implementation uses [slowapi](https://github.com/laurentS/slowapi), a rate limiting library for FastAPI based on [limits](https://limits.readthedocs.io/).

## Configuration

Rate limiting is configured in `/app/utils/rate_limiter.py`.

### Rate Limits by Endpoint Type

| Endpoint Category | Endpoint | Limit | Purpose |
|-------------------|----------|-------|---------|
| **Authentication** | `/api/auth/login` | 5/minute | Prevent brute force login attempts |
| | `/api/auth/register` | 3/minute | Prevent registration abuse |
| | `/api/auth/forgot-password` | 3/minute | Prevent password reset abuse |
| **OTP** | `/api/otp/send` | 3/minute | Prevent OTP flooding |
| | `/api/otp/verify` | 5/minute | Prevent OTP brute force |
| | `/api/otp/resend` | 3/minute | Prevent OTP resend abuse |
| **Mobile (HHD)** | `/api/hhd/login` | 5/minute | Prevent mobile login brute force |
| | `/api/hhd/refresh` | 10/minute | Allow reasonable token refresh |
| **Client Portal** | `/api/client/login` | 5/minute | Prevent client login brute force |
| **Platform Admin** | `/api/platform-admin/setup` | 3/hour | Prevent admin setup abuse |

### Available Rate Limit Configurations

```python
class RateLimits:
    # Authentication endpoints
    LOGIN = "5/minute"
    FORGOT_PASSWORD = "3/minute"
    REGISTER = "3/minute"

    # OTP endpoints
    OTP_SEND = "3/minute"
    OTP_VERIFY = "5/minute"
    OTP_RESEND = "3/minute"

    # Mobile/HHD endpoints
    HHD_LOGIN = "5/minute"
    HHD_REFRESH = "10/minute"

    # Client Portal endpoints
    CLIENT_LOGIN = "5/minute"
    CLIENT_REGISTER = "3/minute"

    # General API limits
    GENERAL = "100/minute"
    BULK_OPERATIONS = "10/minute"
    EXPORT = "5/minute"

    # Admin endpoints
    ADMIN = "200/minute"
    PLATFORM_ADMIN_SETUP = "3/hour"
```

## How It Works

### IP Detection

The rate limiter identifies clients by their IP address. It handles proxied requests by checking:

1. `X-Forwarded-For` header (for load balancers/reverse proxies)
2. `X-Real-IP` header (for nginx)
3. Direct client IP (fallback)

```python
def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    return get_remote_address(request)
```

### Applying Rate Limits

Rate limits are applied using decorators on endpoint functions:

```python
from app.utils.rate_limiter import limiter, RateLimits

@router.post("/login")
@limiter.limit(RateLimits.LOGIN)
async def login(request: Request, credentials: LoginRequest):
    # ... endpoint logic
```

**Important**: The `request: Request` parameter is required for rate-limited endpoints.

## Response Format

When a rate limit is exceeded, the API returns:

**HTTP Status**: `429 Too Many Requests`

**Response Body**:
```json
{
    "error": "rate_limit_exceeded",
    "detail": "Too many requests. Please try again later.",
    "limit_info": "5 per 1 minute",
    "retry_after": "60 seconds"
}
```

**Response Headers**:
- `Retry-After: 60` - Seconds until the client can retry
- `X-RateLimit-Limit: 5 per 1 minute` - The applied rate limit

## Adding Rate Limiting to New Endpoints

### Step 1: Import the limiter

```python
from app.utils.rate_limiter import limiter, RateLimits
```

### Step 2: Add Request parameter

Ensure your endpoint accepts a `Request` parameter:

```python
from fastapi import Request

async def my_endpoint(request: Request, ...):
```

### Step 3: Apply the decorator

```python
@router.post("/my-endpoint")
@limiter.limit(RateLimits.GENERAL)  # or custom limit like "10/minute"
async def my_endpoint(request: Request):
    pass
```

### Step 4: (Optional) Add custom rate limit

Add a new constant to `RateLimits` class in `rate_limiter.py`:

```python
class RateLimits:
    # ... existing limits
    MY_CUSTOM_LIMIT = "20/minute"
```

## Rate Limit String Format

Rate limits use the following format:

- `"5/minute"` - 5 requests per minute
- `"100/hour"` - 100 requests per hour
- `"1000/day"` - 1000 requests per day
- `"5/second"` - 5 requests per second

## Storage Backend

By default, slowapi uses an in-memory storage backend. For production deployments with multiple server instances, consider using Redis:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_client_ip,
    storage_uri="redis://localhost:6379"
)
```

## Monitoring & Logging

Rate limit events are logged with the following information:

- Client IP address
- Request path
- Rate limit that was exceeded

```python
logger.warning(f"Rate limit exceeded for IP {client_ip} on {request.url.path}: {limit_info}")
```

## Security Considerations

1. **IP Spoofing**: The `X-Forwarded-For` header can be spoofed. Ensure your reverse proxy/load balancer is configured to overwrite this header with the actual client IP.

2. **Distributed Attacks**: In-memory storage won't protect against distributed attacks across multiple server instances. Use Redis for production.

3. **Authenticated vs Unauthenticated**: Currently, rate limits are per-IP. For authenticated endpoints, you might want to also implement per-user rate limiting.

4. **Exemptions**: Be careful about adding rate limit exemptions. Each exemption is a potential attack vector.

## Troubleshooting

### Rate limits not working

1. Ensure the `request: Request` parameter is included in the endpoint function
2. Verify the decorator is applied after the route decorator
3. Check that the limiter is added to app state in `main.py`

### Getting 429 during development

During development, you might hit rate limits frequently. Options:

1. Increase limits temporarily in `RateLimits` class
2. Clear the rate limit store (restart server for in-memory)
3. Use different IP addresses (e.g., localhost vs 127.0.0.1)

### Rate limits not shared across workers

If using multiple uvicorn workers, each worker has its own in-memory store. Use Redis for shared rate limiting:

```bash
# Install redis support
pip install redis

# Configure in rate_limiter.py
limiter = Limiter(
    key_func=get_client_ip,
    storage_uri="redis://localhost:6379"
)
```

## Related Files

- `/app/utils/rate_limiter.py` - Rate limiting configuration and utilities
- `/app/main.py` - Rate limiter initialization and exception handler registration
- `/app/api/auth.py` - Authentication endpoint rate limits
- `/app/api/otp.py` - OTP endpoint rate limits
- `/app/api/hhd_auth.py` - Mobile authentication rate limits
- `/app/api/client_portal.py` - Client portal rate limits
