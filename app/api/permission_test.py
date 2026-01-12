"""
Permission Testing API Endpoint

This module provides endpoints to test and verify the permission system.
Useful for frontend development and debugging permission issues.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.models import User, Permission, RolePermission
from app.utils.security import verify_token
from app.utils.permission_seed import PERMISSIONS_DICTIONARY, seed_permissions
import logging

logger = logging.getLogger(__name__)

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


class PermissionCheckRequest(BaseModel):
    module: str
    action: str


class PermissionCheckResponse(BaseModel):
    has_permission: bool
    module: str
    action: str
    user_email: str
    user_role_id: Optional[int]


@router.get("/test/my-permissions")
async def get_my_permissions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all permissions for the current user.
    Useful for debugging and displaying in the frontend.
    """
    if not user.role_id:
        return {
            "user_email": user.email,
            "role_id": None,
            "permissions": [],
            "total": 0
        }

    # Get all permissions for the user's role
    role_permissions = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == user.role_id)
        .all()
    )

    permissions = []
    for rp in role_permissions:
        permission = db.query(Permission).filter(Permission.id == rp.permission_id).first()
        if permission:
            permissions.append({
                "module": permission.module,
                "action": permission.action,
                "permission_string": f"{permission.module}:{permission.action}"
            })

    # Sort by module then action
    permissions.sort(key=lambda x: (x["module"], x["action"]))

    return {
        "user_email": user.email,
        "role_id": user.role_id,
        "permissions": permissions,
        "total": len(permissions)
    }


@router.post("/test/check-permission", response_model=PermissionCheckResponse)
async def check_permission(
    request: PermissionCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check if the current user has a specific permission.
    Useful for testing frontend permission-based UI rendering.
    """
    if not user.role_id:
        return PermissionCheckResponse(
            has_permission=False,
            module=request.module,
            action=request.action,
            user_email=user.email,
            user_role_id=None
        )

    # Check if user has the permission
    role_permissions = (
        db.query(RolePermission)
        .join(Permission)
        .filter(
            RolePermission.role_id == user.role_id,
            Permission.module == request.module,
            Permission.action == request.action
        )
        .first()
    )

    return PermissionCheckResponse(
        has_permission=role_permissions is not None,
        module=request.module,
        action=request.action,
        user_email=user.email,
        user_role_id=user.role_id
    )


@router.get("/test/all-permissions")
async def get_all_permissions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all available permissions in the system.
    Shows what's defined in PERMISSIONS_DICTIONARY vs what's in the database.
    """
    # Get from database
    db_permissions = db.query(Permission).all()
    db_perms_dict = {}
    for p in db_permissions:
        if p.module not in db_perms_dict:
            db_perms_dict[p.module] = []
        db_perms_dict[p.module].append(p.action)

    # Get from dictionary
    dict_perms_dict = {
        module: list(actions.keys())
        for module, actions in PERMISSIONS_DICTIONARY.items()
    }

    # Count totals
    dict_total = sum(len(actions) for actions in PERMISSIONS_DICTIONARY.values())
    db_total = len(db_permissions)

    return {
        "dictionary": {
            "modules": len(PERMISSIONS_DICTIONARY),
            "permissions": dict_total,
            "permissions_by_module": dict_perms_dict
        },
        "database": {
            "modules": len(db_perms_dict),
            "permissions": db_total,
            "permissions_by_module": db_perms_dict
        },
        "status": {
            "in_sync": dict_total == db_total,
            "needs_seeding": dict_total > db_total,
            "missing_count": max(0, dict_total - db_total)
        }
    }


@router.post("/test/seed-permissions")
async def trigger_seed_permissions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually trigger permission seeding.
    Only available to authenticated users.
    """
    try:
        # Count before
        before_count = db.query(Permission).count()

        # Seed
        seed_permissions(db)

        # Count after
        after_count = db.query(Permission).count()
        added = after_count - before_count

        logger.info(f"Permissions seeded by user {user.email}. Added {added} new permissions.")

        return {
            "success": True,
            "message": f"Permissions seeded successfully",
            "before": before_count,
            "after": after_count,
            "added": added
        }
    except Exception as e:
        logger.error(f"Error seeding permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error seeding permissions: {str(e)}"
        )


@router.get("/test/permission-stats")
async def get_permission_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about permissions in the system.
    Shows total permissions, modules, and breakdown.
    """
    # Get all permissions from DB
    all_permissions = db.query(Permission).all()

    # Group by module
    by_module = {}
    for p in all_permissions:
        if p.module not in by_module:
            by_module[p.module] = []
        by_module[p.module].append(p.action)

    # Sort modules
    sorted_modules = sorted(by_module.keys())

    # Create module breakdown
    module_breakdown = [
        {
            "module": module,
            "action_count": len(by_module[module]),
            "actions": sorted(by_module[module])
        }
        for module in sorted_modules
    ]

    return {
        "total_permissions": len(all_permissions),
        "total_modules": len(by_module),
        "modules": module_breakdown,
        "user": {
            "email": user.email,
            "role_id": user.role_id
        }
    }
