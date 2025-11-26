from fastapi import HTTPException, status
import logging
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from passlib.hash import bcrypt
from app.utils.auth_utils import (
    get_password_hash,
    verify_password,
    validate_password_complexity,
    validate_email_format,
    create_access_token,
    create_refresh_token
)
from app.models import User, Auth, RefreshToken, Company
from app.company.schema import SignupCompanyRequest

# Configure logger
logger = logging.getLogger(__name__)

ACTION_SIGNUP = "USER_SIGNUP"

def signup_company_admin(db: Session, data: SignupCompanyRequest, ip_address: str):
     # Pre-check: Company uniqueness
    existing_company = db.query(Company).filter(
        Company.company_name == data.company_name
    ).first()
    if existing_company:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company name already used"
        )
    
    # Pre-checks: Email Uniqueness
    existing_user = db.query(User).filter(User.user_email == data.user_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
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
    
    hashed_password = get_password_hash(data.user_password)

    try:
        # Single transaction
        new_company = Company(company_name=data.company_name)
        db.add(new_company)

        new_user = User(
            user_email=data.user_email,
            user_name="test",
            user_company_id=new_company.company_id,
            user_role="CLIENT_ADMIN",
            is_verified=False  # recommended
        )
        db.add(new_user)

        new_auth = Auth(
            auth_user_id=new_user.user_id,
            auth_password_hash=hashed_password
        )
        db.add(new_auth)

        db.commit()
        db.refresh(new_user)

    except Exception as e:
        db.rollback()
        logger.error(f"Signup transaction failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signup failed test"
        )
    
    # Tokens
    access_token = create_access_token(str(new_user.user_id))
    refresh_token_str = create_refresh_token()

    refresh_token = RefreshToken(
        rftk_user_id=new_user.user_id,
        rftk_token=refresh_token_str,
        rftk_expires_at=datetime.utcnow() + timedelta(days=30),
        rftk_issued_from_ip=ip_address
    )
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "Bearer"
    }
