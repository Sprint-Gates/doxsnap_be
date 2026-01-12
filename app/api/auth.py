from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.schemas import UserCreate, UserLogin, Token, User as UserSchema, PasswordReset, PasswordResetConfirm, UserUpdate, RefreshTokenRequest
from app.services.auth import create_user, authenticate_user, get_user_by_email, get_user_by_id, update_user_profile
from app.utils.security import create_access_token, verify_token, get_password_hash, generate_refresh_token, get_refresh_token_expiry
from app.config import settings
from app.services.otp import OTPService
from app.models import RefreshToken, Company

router = APIRouter()
security = HTTPBearer(auto_error=False)


def get_subscription_info(user, db: Session) -> dict:
    """
    Get detailed subscription information for a user's company.
    Returns dict with subscription status, days remaining, warning flags, etc.
    """
    result = {
        "active": True,
        "reason": None,
        "subscription_status": None,
        "subscription_end": None,
        "days_remaining": None,
        "is_trial": False,
        "show_warning": False,
        "warning_message": None
    }

    if not user.company_id:
        return result  # No company = no restriction

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        return result

    result["subscription_status"] = company.subscription_status
    result["subscription_end"] = company.subscription_end.isoformat() if company.subscription_end else None
    result["is_trial"] = company.subscription_status == "trial"

    # Calculate days remaining
    if company.subscription_end:
        now = datetime.utcnow()
        delta = company.subscription_end - now
        result["days_remaining"] = max(0, delta.days)

        # Show warning if 3 days or less remaining
        if 0 < delta.days <= 3:
            result["show_warning"] = True
            if company.subscription_status == "trial":
                result["warning_message"] = f"Your trial expires in {delta.days} day{'s' if delta.days != 1 else ''}. Upgrade now to continue using CoreSRP."
            else:
                result["warning_message"] = f"Your subscription expires in {delta.days} day{'s' if delta.days != 1 else ''}. Renew now to avoid interruption."

    # Check subscription status
    if company.subscription_status == "cancelled":
        result["active"] = False
        result["reason"] = "Subscription has been cancelled"
        return result

    if company.subscription_status == "suspended":
        result["active"] = False
        result["reason"] = "Subscription has been suspended"
        return result

    # Check if trial or subscription has expired
    if company.subscription_end and company.subscription_end < datetime.utcnow():
        result["active"] = False
        result["days_remaining"] = 0
        if company.subscription_status == "trial":
            result["reason"] = "Trial period has expired. Please upgrade to continue."
        else:
            result["reason"] = "Subscription has expired. Please renew to continue."
        return result

    return result


def check_subscription_active(user, db: Session) -> dict:
    """
    Check if user's company has an active subscription.
    Returns dict with 'active' boolean and 'reason' string.
    """
    info = get_subscription_info(user, db)
    return {"active": info["active"], "reason": info["reason"]}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    import logging
    logger = logging.getLogger(__name__)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Check if credentials were provided (auto_error=False means this can be None)
    if credentials is None:
        logger.error("[get_current_user] No credentials provided - credentials is None")
        raise credentials_exception

    logger.info(f"[get_current_user] Credentials scheme: {credentials.scheme}, token length: {len(credentials.credentials) if credentials.credentials else 0}")

    email = verify_token(credentials.credentials)
    if email is None:
        logger.error("[get_current_user] Token verification failed - email is None")
        raise credentials_exception

    logger.info(f"[get_current_user] Token verified for email: {email}")

    user = get_user_by_email(db, email=email)
    if user is None:
        logger.error(f"[get_current_user] User not found for email: {email}")
        raise credentials_exception

    logger.info(f"[get_current_user] User found: {user.email}")
    return user


async def get_current_active_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Get current user and verify their subscription is active.
    Use this for protected routes that require an active subscription.
    """
    user = await get_current_user(credentials, db)

    subscription_check = check_subscription_active(user, db)
    if not subscription_check["active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=subscription_check["reason"]
        )

    return user


@router.post("/register", response_model=UserSchema)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    try:
        db_user = create_user(db=db, user=user)
        return db_user
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error creating user"
        )


@router.post("/login", response_model=Token)
async def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    user = authenticate_user(db, user_credentials.email, user_credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    # Create refresh token
    refresh_token_str = generate_refresh_token()
    refresh_token_expiry = get_refresh_token_expiry()

    # Store refresh token in database
    db_refresh_token = RefreshToken(
        user_id=user.id,
        token=refresh_token_str,
        expires_at=refresh_token_expiry
    )
    db.add(db_refresh_token)
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,  # Convert to seconds
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": user.is_active,
            "phone": user.phone
        }
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Get a new access token using a refresh token"""
    # Find the refresh token in database
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token == request.refresh_token,
        RefreshToken.is_revoked == False
    ).first()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if token is expired
    if db_token.expires_at < datetime.utcnow():
        # Revoke the expired token
        db_token.is_revoked = True
        db_token.revoked_at = datetime.utcnow()
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get the user
    user = get_user_by_id(db, db_token.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Revoke old refresh token
    db_token.is_revoked = True
    db_token.revoked_at = datetime.utcnow()

    # Create new access token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    # Create new refresh token
    new_refresh_token_str = generate_refresh_token()
    new_refresh_token_expiry = get_refresh_token_expiry()

    new_db_refresh_token = RefreshToken(
        user_id=user.id,
        token=new_refresh_token_str,
        expires_at=new_refresh_token_expiry
    )
    db.add(new_db_refresh_token)
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token_str,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60
    }


@router.post("/logout")
async def logout(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
    current_user: UserSchema = Depends(get_current_user)
):
    """Logout and revoke the refresh token"""
    db_token = db.query(RefreshToken).filter(
        RefreshToken.token == request.refresh_token,
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False
    ).first()

    if db_token:
        db_token.is_revoked = True
        db_token.revoked_at = datetime.utcnow()
        db.commit()

    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserSchema)
async def read_users_me(current_user: UserSchema = Depends(get_current_user)):
    return current_user


@router.get("/quota")
async def get_user_quota(
    response: Response,
    current_user: UserSchema = Depends(get_current_user)
):
    """Get user's document processing quota"""
    # Add cache control headers to ensure fresh quota data
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    return {
        "remaining_documents": current_user.remaining_documents,
        "max_free_documents": 5,
        "used_documents": 5 - current_user.remaining_documents
    }


@router.get("/login-page", response_class=HTMLResponse)
async def login_page():
    """Serve the login HTML page"""
    template_path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "login.html")
    
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Login template not found"
        )


@router.get("/dashboard", response_class=HTMLResponse)
async def quota_dashboard():
    """Serve the quota dashboard HTML page"""
    template_path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "quota_dashboard.html")
    
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard template not found"
        )


@router.put("/profile", response_model=UserSchema)
async def update_profile(
    user_update: UserUpdate,
    current_user: UserSchema = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user profile information"""
    try:
        updated_user = update_user_profile(db, current_user.id, user_update)
        return updated_user
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error updating profile"
        )


@router.post("/forgot-password")
async def forgot_password(password_reset: PasswordReset, db: Session = Depends(get_db)):
    """
    Request a password reset OTP.
    Sends an OTP code to the user's email if it exists.
    """
    user = get_user_by_email(db, password_reset.email)

    # Always return success message to prevent email enumeration
    if not user:
        return {
            "success": True,
            "message": "If the email exists, a password reset code has been sent"
        }

    # Create OTP and send email
    otp_service = OTPService()
    otp_record = otp_service.create_otp(db, password_reset.email, purpose="password_reset")

    # Send OTP email
    email_sent = otp_service.send_otp_email(
        email=password_reset.email,
        otp_code=otp_record.otp_code,
        purpose="password_reset"
    )

    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send password reset email"
        )

    return {
        "success": True,
        "message": "If the email exists, a password reset code has been sent",
        "expires_in_minutes": 10
    }


@router.post("/reset-password")
async def reset_password(password_reset: PasswordResetConfirm, db: Session = Depends(get_db)):
    """
    Reset password using OTP code.
    Verifies the OTP and updates the user's password.
    """
    # Verify the OTP first
    otp_service = OTPService()
    verification_result = otp_service.verify_otp(
        db=db,
        email=password_reset.email,
        otp_code=password_reset.otp_code,
        purpose="password_reset"
    )

    if not verification_result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=verification_result["message"]
        )

    # Get user and update password
    user = get_user_by_email(db, password_reset.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Update password
    user.hashed_password = get_password_hash(password_reset.new_password)
    db.commit()

    return {
        "success": True,
        "message": "Password has been reset successfully"
    }


@router.get("/subscription-status")
async def get_subscription_status(
    current_user: UserSchema = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current subscription status including warning info.
    This endpoint doesn't block expired users so they can see their status.
    """
    info = get_subscription_info(current_user, db)
    return info