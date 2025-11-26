"""
Business logic for user signup
"""

import logging
from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from secrets import token_urlsafe

from app.models import User, Auth, RefreshToken, EmailVerification
from app.signup.schema import SignupRequest
from app.utils.auth_utils import (
    get_password_hash,
    validate_password_complexity,
    validate_email_format,
    create_access_token,
    create_refresh_token,
)
from app.utils.email_ver_utils import(
    send_verification_email,
    generate_verification_token
)

# Configure logger
logger = logging.getLogger(__name__)

# Service-specific constants
REFRESH_TOKEN_EXPIRE_DAYS = 7
ACTION_SIGNUP = "USER_SIGNUP"

# Signup flow

def signup_user(db: Session, data: SignupRequest, ip_address: str) -> JSONResponse:
    """
    Create a new user, hash password, create auth record,
    generate verification token, send email, and issue tokens.
    """

    logger.info(
        f"Signup attempt for email '{data.user_email}'",
        extra={"action": ACTION_SIGNUP},
    )

    # Check if email already registered
    existing_user = (
        db.query(User).filter(User.user_email == data.user_email).first()
    )
    if existing_user:
        logger.warning(
            f"Signup failed: email already registered ({data.user_email})",
            extra={"action": ACTION_SIGNUP},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    
    # Validate email format
    if not validate_email_format(data.user_email):
        logger.warning(
            f"Signup failed: invalid email format ({data.user_email})",
            extra={"action": ACTION_SIGNUP},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format",
        )

    # Validate password strength
    if not validate_password_complexity(data.user_password):
        logger.warning(
            f"Signup failed: weak password for {data.user_email}",
            extra={"action": ACTION_SIGNUP},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password should caintain at least 8 characters, 1 Upper character, and 1 Special characters",
        )

    # Create user
    user = User(
        user_email=data.user_email,
        user_name=data.user_name,
        user_avatar=data.user_avatar,
        user_is_verified=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create auth/password record
    hashed_password = get_password_hash(data.user_password)
    auth = Auth(
        auth_user_id=user.user_id,
        auth_password_hash=hashed_password,
        auth_failed_login_attempts=0,
        auth_is_locked_until=None,
        auth_password_updated_at=datetime.utcnow(),
    )
    db.add(auth)
    db.commit()

    # Email verification step
    verification_token = generate_verification_token()
    email_verification = EmailVerification(
        emvr_user_id=user.user_id,
        emvr_token=verification_token,
        emvr_expires_at=datetime.utcnow() + timedelta(hours=24)
    )
    db.add(email_verification)
    db.commit()

    # Send verification email
    send_verification_email(user.user_email, verification_token)


    # Issue access + refresh tokens
    access_token = create_access_token({"sub": str(user.user_id)})
    refresh_token_str = create_refresh_token()

    refresh_token = RefreshToken(
        rftk_user_id=user.user_id,
        rftk_token=refresh_token_str,
        rftk_expires_at=datetime.utcnow()
        + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        rftk_issued_from_ip=ip_address,
    )
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)

    logger.info(
        f"User {user.user_id} created successfully",
        extra={"action": ACTION_SIGNUP},
    )

    # Response to client
    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": str(user.user_id),
            "is_verified": False,
            "message": "Signup successful. Please verify your email.",
        }
    )

    # Set refresh token in cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        secure=True,      # enable HTTPS in production
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )

    return response
