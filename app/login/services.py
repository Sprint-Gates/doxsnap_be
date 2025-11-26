"""
Business logic for user login with modular failed login handling
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models import User, RefreshToken, Auth
from app.login.schema import LoginRequest
from app.utils.auth_utils import verify_password, create_access_token, create_refresh_token

# Configure logger

logger = logging.getLogger(__name__)

# Service-specific constants

MAX_FAILED_ATTEMPTS = 5
LOCK_TIME_MINUTES = 2
ACTION_LOGIN = "USER_LOGIN"

def handle_failed_login(auth: Auth, user_id: str, db: Session) -> None:
    """
    Increment failed login attempts and lock account if necessary.

    Args:
        auth: Auth model for the user
        user_id: User identifier
        db: Database session
    """
    now = datetime.utcnow()
    auth.auth_failed_login_attempts += 1
    if auth.auth_failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        auth.auth_is_locked_until = now + timedelta(minutes=LOCK_TIME_MINUTES)
        auth.auth_failed_login_attempts = 0
        logger.warning(f"User {user_id} account locked due to failed login attempts", extra={"action": ACTION_LOGIN})
    db.commit()

def login_user(db: Session, data: LoginRequest, ip_address: str) -> Dict[str, str]:
    """
    Authenticate a user and return access and refresh tokens
    
    Args:
        db: Database session
        data: Login request containing email and password
        ip_address: IP address of the login attempt

    Returns:
        dict: Access token, refresh token, and token type

    Raises:
        HTTPException: For invalid credentials or locked accounts
    """
    logger.info(f"Login attempt for email '{data.user_email}'", extra={"action": ACTION_LOGIN})

    # Retrieve user
    user: Optional[User] = db.query(User).filter(User.user_email == data.user_email).first()
    if not user:
        logger.warning(f"Login failed: user not found ({data.user_email})", extra={"action": ACTION_LOGIN})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    if not user.user_is_verified:
        logger.warning(
            f"Login failed: email not verified for user {user.user_email}",
            extra={"action": ACTION_LOGIN},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email before logging in."
        )

    # Retrieve authentication record
    auth: Optional[Auth] = db.query(Auth).filter(Auth.auth_user_id == user.user_id).first()
    if not auth:
        logger.warning(f"Login failed: auth record not found for user {user.user_id}", extra={"action": ACTION_LOGIN})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    now = datetime.utcnow()

    # Check if account is locked
    if auth.auth_is_locked_until and auth.auth_is_locked_until > now:
        logger.warning(f"Login attempt while account locked for user {user.user_id}", extra={"action": ACTION_LOGIN})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account temporarily locked due to failed login attempts. Try again later."
        )

    # Verify password
    if not verify_password(data.user_password, auth.auth_password_hash):
        handle_failed_login(auth, user.user_id, db)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Successful login
    auth.auth_failed_login_attempts = 0
    auth.auth_is_locked_until = None
    db.commit()

    # Create tokens
    access_token = create_access_token({"sub": str(user.user_id)})
    refresh_token_str = create_refresh_token()

    # Store refresh token in DB
    refresh_token = RefreshToken(
        rftk_user_id=user.user_id,
        rftk_token=refresh_token_str,
        rftk_expires_at=now + timedelta(days=7),
        rftk_issued_from_ip=ip_address
    )
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)

    logger.info(f"User {user.user_id} logged in successfully", extra={"action": ACTION_LOGIN})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer"
    }
