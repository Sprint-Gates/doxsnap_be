"""
User Management API - for managing company users
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.models import User, Client, Site, ExternalUserClient
from app.utils.security import get_password_hash, verify_token
from app.utils.limits import check_user_limit, enforce_user_limit

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "operator" # admin, operator, accounting, procurement, general_manager, external-user
    phone: Optional[str] = None

    # External user only
    client_id: Optional[int] = None
    site_ids: Optional[List[int]] = None

    @field_validator("client_id")
    @classmethod
    def validate_client_for_external(cls, v, info):
        if info.data.get("role") == "external-user" and not v:
            raise ValueError("client_id is required for external users")
        return v

    @field_validator("site_ids")
    @classmethod
    def validate_sites_for_external(cls, v, info):
        if info.data.get("role") == "external-user" and not v:
            raise ValueError("At least one site is required for external users")
        return v

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    # PR Approval permissions
    can_approve_pr: Optional[bool] = None
    approval_limit: Optional[float] = None  # None means unlimited
    can_convert_po: Optional[bool] = None  # Can convert approved PRs to POs
    # Work Order Approval permissions
    can_approve_wo: Optional[bool] = None  # Can approve work orders


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    phone: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    # PR Approval permissions
    can_approve_pr: bool = False
    approval_limit: Optional[float] = None  # None means unlimited
    can_convert_po: bool = False  # Can convert approved PRs to POs
    # Work Order Approval permissions
    can_approve_wo: bool = False  # Can approve work orders

    class Config:
        from_attributes = True


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require admin role for user management"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


@router.get("/users/", response_model=List[UserResponse])
async def get_users(
    include_inactive: bool = False,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get all users in the company"""
    query = db.query(User).filter(User.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(User.is_active == True)

    users = query.order_by(User.name).all()
    return users


@router.get("/users/limit-info")
async def get_user_limit_info(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get current user count and limit for the company."""
    limit_info = check_user_limit(db, user.company_id)
    return limit_info


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get a specific user"""
    target_user = db.query(User).filter(
        User.id == user_id,
        User.company_id == user.company_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    return target_user


@router.post("/users/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new user in the company"""
    # Check user limit before creating
    enforce_user_limit(db, user.company_id)

    # Validate role
    valid_roles = ["admin", "operator", "accounting", "procurement", "general_manager", "external-user"]
    
    if data.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Must be one of: {valid_roles}"
        )

    # Check if email already exists
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists"
        )

    try:
        # Start transaction
        new_user = User(
            email=data.email,
            hashed_password=get_password_hash(data.password),
            name=data.name,
            role=data.role,
            phone=data.phone,
            company_id=user.company_id,
            is_active=True
        )

        db.add(new_user)

        # External user handling
        if data.role == "external-user":
            if not data.client_id:
                raise HTTPException(status_code=400, detail="client_id is required for external users")
            if not data.site_ids or len(data.site_ids) == 0:
                raise HTTPException(status_code=400, detail="At least one site is required for external users")

            # Validate client belongs to same company
            client = db.query(Client).filter(
                Client.id == data.client_id,
                Client.company_id == user.company_id
            ).first()
            if not client:
                raise HTTPException(status_code=400, detail="Invalid client")

            # Validate sites belong to client
            sites = db.query(Site).filter(
                Site.id.in_(data.site_ids),
                Site.client_id == client.id
            ).all()
            if len(sites) != len(data.site_ids):
                raise HTTPException(
                    status_code=400,
                    detail="One or more sites do not belong to the selected client"
                )

            # Create ExternalUserClient entry
            euc = ExternalUserClient(
                user=new_user,
                client=client,
                company_id=user.company_id
            )
            euc.sites = sites
            db.add(euc)

        db.commit()
        db.refresh(new_user)

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create user") from e

    return new_user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a user"""
    target_user = db.query(User).filter(
        User.id == user_id,
        User.company_id == user.company_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent deactivating yourself
    if user_id == user.id and data.is_active == False:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate your own account"
        )

    # Check user limit when reactivating a user
    if data.is_active == True and not target_user.is_active:
        enforce_user_limit(db, user.company_id)

    # Validate role if provided
    if data.role:
        valid_roles = ["admin", "operator", "accounting", "procurement", "general_manager", "external-user"]
        if data.role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role. Must be one of: {valid_roles}"
            )

    # Check email uniqueness if changed
    if data.email and data.email != target_user.email:
        existing = db.query(User).filter(User.email == data.email).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="A user with this email already exists"
            )

    # Update fields
    if data.name is not None:
        target_user.name = data.name
    if data.email is not None:
        target_user.email = data.email
    if data.role is not None:
        target_user.role = data.role
    if data.phone is not None:
        target_user.phone = data.phone
    if data.is_active is not None:
        target_user.is_active = data.is_active
    # PR Approval permissions
    if data.can_approve_pr is not None:
        target_user.can_approve_pr = data.can_approve_pr
    if data.approval_limit is not None:
        target_user.approval_limit = data.approval_limit
    if data.can_convert_po is not None:
        target_user.can_convert_po = data.can_convert_po
    # Work Order Approval permissions
    if data.can_approve_wo is not None:
        target_user.can_approve_wo = data.can_approve_wo

    db.commit()
    db.refresh(target_user)

    return target_user


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    new_password: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Reset a user's password"""
    target_user = db.query(User).filter(
        User.id == user_id,
        User.company_id == user.company_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if len(new_password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters"
        )

    target_user.hashed_password = get_password_hash(new_password)
    db.commit()

    return {"message": "Password reset successfully"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deactivate a user (soft delete)"""
    target_user = db.query(User).filter(
        User.id == user_id,
        User.company_id == user.company_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_id == user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account"
        )

    target_user.is_active = False
    db.commit()

    return {"message": "User deactivated successfully"}
