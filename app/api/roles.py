from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.utils.security import verify_token
import logging
from app.models import Role, RolePermission, User, Permission

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)  # verify_token returns the email directly

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


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user

class RoleCreate(BaseModel):
    name: str
    description: str


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class RoleResponse(BaseModel):
    id: int
    name: str
    description: str

    class Config:
        from_attributes = True

class PermissionResponse(BaseModel):
    id: int
    module: str
    action: str

    class Config:
        from_attributes = True


class RolePermissionUpdate(BaseModel):
    permission_ids: List[int]

class PermissionCreate(BaseModel):
    module: str
    action: str

class PermissionUpdate(BaseModel):
    module: Optional[str] = None
    action: Optional[str] = None


@router.post("/roles", status_code=201)
def create_role(
    data: RoleCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not user.company_id:
        raise HTTPException(status_code=400, detail="No company context")

    existing = db.query(Role).filter(
        Role.company_id == user.company_id,
        Role.name == data.name
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role already exists")

    role = Role(
        name=data.name,
        company_id=user.company_id,
        description=data.description
    )
    db.add(role)
    db.commit()
    db.refresh(role)

    return {"success": True, "role": role}


@router.get("/roles", response_model=List[RoleResponse])
def list_roles(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Role).filter(Role.company_id == user.company_id).all()


@router.put("/roles/{role_id}")
def update_role(
    role_id: int,
    data: RoleUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(
        Role.id == role_id,
        Role.company_id == user.company_id
    ).first()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if data.name:
        role.name = data.name

    if data.description:
        role.description = data.description

    db.commit()
    return {"success": True}


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(
        Role.id == role_id,
        Role.company_id == user.company_id
    ).first()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Safety: prevent deleting role in use
    users_count = db.query(User).filter(User.role_id == role.id).count()
    if users_count > 0:
        raise HTTPException(
            status_code=400,
            detail="Role is assigned to users"
        )

    db.delete(role)
    db.commit()

    return {"success": True}

@router.get("/permissions", response_model=List[PermissionResponse])
def list_permissions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Permission).order_by(
        Permission.module,
        Permission.action
    ).all()

@router.get("/roles/{role_id}/permissions")
def get_role_permissions(
    role_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(
        Role.id == role_id,
        Role.company_id == user.company_id
    ).first()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    permissions = (
        db.query(Permission)
        .join(RolePermission)
        .filter(RolePermission.role_id == role.id)
        .all()
    )

    return {"permissions": permissions}


@router.put("/roles/{role_id}/permissions")
def update_role_permissions(
    role_id: int,
    data: RolePermissionUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    role = db.query(Role).filter(
        Role.id == role_id,
        Role.company_id == user.company_id
    ).first()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Clear existing permissions
    db.query(RolePermission).filter(
        RolePermission.role_id == role.id
    ).delete()

    # Assign new permissions
    for perm_id in data.permission_ids:
        db.add(RolePermission(
            role_id=role.id,
            permission_id=perm_id
        ))

    db.commit()
    return {"success": True}

@router.post("/permissions", status_code=201)
def create_permission(
    data: PermissionCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    # Prevent duplicate module/action
    existing = db.query(Permission).filter(
        Permission.module == data.module,
        Permission.action == data.action
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Permission already exists")

    perm = Permission(module=data.module, action=data.action)
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return {"success": True, "permission": perm}


@router.put("/permissions/{permission_id}")
def update_permission(
    permission_id: int,
    data: PermissionUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    perm = db.query(Permission).filter(Permission.id == permission_id).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")

    if data.module:
        perm.module = data.module
    if data.action:
        perm.action = data.action

    # Optional: check uniqueness after update
    duplicate = db.query(Permission).filter(
        Permission.id != perm.id,
        Permission.module == perm.module,
        Permission.action == perm.action
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="Duplicate permission exists")

    db.commit()
    return {"success": True, "permission": perm}


@router.delete("/permissions/{permission_id}")
def delete_permission(
    permission_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    perm = db.query(Permission).filter(Permission.id == permission_id).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")

    # Optional: prevent deleting a permission that is assigned to roles
    assigned = db.query(RolePermission).filter(RolePermission.permission_id == perm.id).count()
    if assigned > 0:
        raise HTTPException(status_code=400, detail="Permission is assigned to roles")

    db.delete(perm)
    db.commit()
    return {"success": True} 