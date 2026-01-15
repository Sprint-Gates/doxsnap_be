"""
Rate Limiting Configuration for CoreSRP API

This module provides rate limiting functionality to protect the API from:
- Brute force attacks on login endpoints
- OTP/verification code abuse
- Password reset abuse
- General API abuse/DDoS

Uses slowapi for rate limiting with the following default limits:
- Login: 5 attempts per minute per IP
- OTP endpoints: 3 attempts per minute per IP
- Forgot password: 3 attempts per minute per IP
- HHD mobile login: 5 attempts per minute per IP
- General API: 100 requests per minute per IP

Usage:
    from app.utils.rate_limiter import limiter, RateLimits

    @router.post("/my-endpoint")
    @limiter.limit(RateLimits.GENERAL)
    async def my_endpoint(request: Request):
        pass

Note: The `request: Request` parameter is REQUIRED for rate-limited endpoints.

For full documentation, see /docs/RATE_LIMITING.md
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """
    Get the client IP address from the request.
    Handles cases where the app is behind a proxy/load balancer.
    """
    # Check for X-Forwarded-For header (common for proxies/load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded_for.split(",")[0].strip()

    # Check for X-Real-IP header (nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client IP
    return get_remote_address(request)


# Initialize the limiter with custom key function
limiter = Limiter(key_func=get_client_ip)


# Rate limit configurations
class RateLimits:
    """Rate limit configurations for different endpoint types"""

    # Authentication endpoints
    LOGIN = "5/minute"              # 5 attempts per minute for login
    FORGOT_PASSWORD = "3/minute"    # 3 attempts per minute for password reset
    REGISTER = "3/minute"           # 3 attempts per minute for registration

    # OTP endpoints (security-sensitive)
    OTP_SEND = "3/minute"           # 3 OTP sends per minute
    OTP_VERIFY = "5/minute"         # 5 OTP verifications per minute
    OTP_RESEND = "3/minute"         # 3 OTP resends per minute

    # Mobile/HHD endpoints
    HHD_LOGIN = "5/minute"          # 5 HHD login attempts per minute
    HHD_REFRESH = "10/minute"       # 10 token refreshes per minute

    # Client Portal endpoints
    CLIENT_LOGIN = "5/minute"       # 5 client login attempts per minute
    CLIENT_REGISTER = "3/minute"    # 3 client registrations per minute

    # General API rate limits
    GENERAL = "100/minute"          # 100 requests per minute for general endpoints
    BULK_OPERATIONS = "10/minute"   # 10 bulk operations per minute
    EXPORT = "5/minute"             # 5 exports per minute

    # Admin endpoints (more permissive for legitimate admin work)
    ADMIN = "200/minute"            # 200 requests per minute for admin

    # Platform admin (super admin)
    PLATFORM_ADMIN_SETUP = "3/hour"  # 3 setup attempts per hour


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Custom handler for rate limit exceeded errors.
    Returns a JSON response with details about the rate limit.
    """
    from fastapi.responses import JSONResponse

    # Extract the limit info
    limit_info = str(exc.detail) if hasattr(exc, 'detail') else "Rate limit exceeded"

    # Log the rate limit hit
    client_ip = get_client_ip(request)
    logger.warning(f"Rate limit exceeded for IP {client_ip} on {request.url.path}: {limit_info}")

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": "Too many requests. Please try again later.",
            "limit_info": limit_info,
            "retry_after": "60 seconds"
        },
        headers={
            "Retry-After": "60",
            "X-RateLimit-Limit": limit_info
        }
    )
