"""
Business logic for user signup
"""

import logging
from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status

from app.models import User, Auth, RefreshToken
from app.signup.schema import SignupRequest
from app.auth_utils import (
get_password_hash,
validate_password_complexity,
create_access_token,
create_refresh_token,
)

# Configure logger

logger = logging.getLogger(__name__)

# Service-specific constants

REFRESH_TOKEN_EXPIRE_DAYS = 7
ACTION_SIGNUP = "USER_SIGNUP"

def signup_user(db: Session, data: SignupRequest, ip_address: str) -> JSONResponse:
    """
    Create a new user, hash password, create auth record, and issue tokens.
    Args:
        db: Database session
        data: Signup request containing email, password, username, and avatar
        ip_address: IP address of the signup request

    Returns:
        JSONResponse: Access token in response body and refresh token in cookie

    Raises:
        HTTPException: If email already registered or password invalid
    """
    logger.info(f"Signup attempt for email '{data.email}'", extra={"action": ACTION_SIGNUP})

    # Check if email is already registered
    existing_user = db.query(User).filter(User.user_email == data.email).first()
    if existing_user:
        logger.warning(f"Signup failed: email already registered ({data.email})", extra={"action": ACTION_SIGNUP})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    # Validate password complexity
    if not validate_password_complexity(data.password):
        logger.warning(f"Signup failed: weak password for email {data.email}", extra={"action": ACTION_SIGNUP})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password does not meet complexity requirements")

    # Create user record
    user = User(
        user_email=data.email,
        user_name=data.user_name,
        user_avatar=data.user_avatar,
        is_verified=0
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Hash password and create auth record
    hashed_password = get_password_hash(data.password)
    auth = Auth(
        auth_user_id=user.user_id,
        auth_password_hash=hashed_password,
        auth_failed_login_attempts=0,
        auth_is_locked_until=None,
        auth_password_updated_at=datetime.utcnow()
    )
    db.add(auth)
    db.commit()

    # Issue access and refresh tokens
    access_token = create_access_token({"sub": str(user.user_id)})
    refresh_token_str = create_refresh_token()

    # Create refresh token record in DB
    refresh_token = RefreshToken(
        reftok_user_id=user.user_id,
        reftok_token=refresh_token_str,
        reftok_expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        reftok_issued_from_ip=ip_address
    )
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)

    logger.info(f"User {user.user_id} signed up successfully", extra={"action": ACTION_SIGNUP})

    # Prepare response
    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": str(user.user_id),
            "is_verified": False
        }
    )

    # Set Refresh Token in HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        secure=True,          # Enable HTTPS only in production
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/"
    )

    return response