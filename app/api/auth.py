from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.schemas import UserCreate, UserLogin, Token, User as UserSchema, PasswordReset, UserUpdate
from app.services.auth import create_user, authenticate_user, get_user_by_email, get_user_by_id, update_user_profile
from app.utils.security import create_access_token, verify_token
from app.config import settings

router = APIRouter()
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    email = verify_token(credentials.credentials)
    if email is None:
        raise credentials_exception
    
    user = get_user_by_email(db, email=email)
    if user is None:
        raise credentials_exception
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
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


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


@router.post("/reset-password")
async def reset_password(password_reset: PasswordReset, db: Session = Depends(get_db)):
    user = get_user_by_email(db, password_reset.email)
    if not user:
        # Don't reveal whether the email exists or not for security
        return {"message": "If the email exists, a reset link has been sent"}
    
    # TODO: Implement email sending logic
    # For now, just return success message
    return {"message": "If the email exists, a reset link has been sent"}