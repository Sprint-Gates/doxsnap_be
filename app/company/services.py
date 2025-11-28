"""
Business logic for company signup
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException

from app.models import User, Auth, RefreshToken, EmailVerification, Company, UserRole
from app.company.schema import SignupRequest
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

def signup_user_company(db: Session, data: SignupRequest, ip_address: str) -> JSONResponse:
    logger.info("Signup attempt", extra={"action": ACTION_SIGNUP, "email": data.user_email})

    # Existing user check
    if db.query(User).filter(User.user_email == data.user_email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Email format
    if not validate_email_format(data.user_email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Company name check
    if db.query(Company).filter(Company.company_name == data.company_name).first():
        raise HTTPException(status_code=409, detail="Company name already exists")

    # Password strength
    if not validate_password_complexity(data.user_password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain ≥8 characters, 1 uppercase letter, and 1 special character",
        )

    try:
        # Create Company
        company = Company(company_name=data.company_name)
        db.add(company)
        db.flush()

        # Create User
        user = User(
            user_email=data.user_email,
            user_name=data.user_name,
            user_company_id=company.company_id,
            user_role=UserRole.CLIENT_ADMIN,
            user_is_verified=False,
        )
        db.add(user)
        db.flush()

        # Auth record
        hashed_password = get_password_hash(data.user_password)
        db.add(Auth(auth_user_id=user.user_id, auth_password_hash=hashed_password))

        # Email verification
        verification_token = generate_verification_token()
        db.add(EmailVerification(
            emvr_user_id=user.user_id,
            emvr_token=verification_token,
            emvr_expires_at=datetime.utcnow() + timedelta(hours=24),
        ))

        send_verification_email(user.user_email, verification_token)

        # Tokens
        access_token = create_access_token({"sub": str(user.user_id)})
        refresh_token_str = create_refresh_token()

        db.add(RefreshToken(
            rftk_user_id=user.user_id,
            rftk_token=refresh_token_str,
            rftk_expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
            rftk_issued_from_ip=ip_address,
        ))

        db.commit()

    except Exception as exc:
        db.rollback()
        logger.error("Signup failed", extra={"error": str(exc), "action": ACTION_SIGNUP})
        raise HTTPException(status_code=500, detail="Signup failed")

    logger.info("User created successfully", extra={"action": ACTION_SIGNUP, "user_id": str(user.user_id)})

    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": str(user.user_id),
            "is_verified": False,
            "message": "Signup successful. Please verify your email.",
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )
    return response