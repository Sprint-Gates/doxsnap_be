from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, RolePermission, Permission

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.utils.security import verify_token

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

def require_permission(module: str, action: str):
    """Dependency to check if current user has a specific permission"""
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ):
        # Load permissions of the user's role
        role_permissions = (
            db.query(RolePermission)
            .join(Permission)
            .filter(RolePermission.role_id == current_user.role_id)
            .all()
        )

        allowed = any(
            rp.permission.module == module and rp.permission.action == action
            for rp in role_permissions
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{module}:{action}' not authorized"
            )
        return current_user
    return permission_checker