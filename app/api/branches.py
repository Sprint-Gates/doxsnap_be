from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import Branch, Client, User, Company, Project, HandHeldDevice
from app.utils.security import verify_token
from jose import jwt
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


# ============ HHD Authentication Support ============

class HHDContext:
    """Context object for HHD authentication - mimics User for compatibility"""
    def __init__(self, device: HandHeldDevice, technician_id: Optional[int] = None):
        self.device = device
        self.company_id = device.company_id
        self.id = technician_id
        self.email = f"hhd:{device.device_code}"
        self.name = device.device_name
        self.role = "technician"


def verify_token_payload(token: str) -> Optional[dict]:
    """Verify token and return full payload"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except:
        return None


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


def get_current_user_or_hhd(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """Authenticate either a User or HHD device."""
    token = credentials.credentials
    payload = verify_token_payload(token)

    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    sub = payload.get("sub")
    token_type = payload.get("type")

    if token_type == "hhd" or (sub and sub.startswith("hhd:")):
        device_id = payload.get("device_id")
        if not device_id:
            try:
                device_id = int(sub.split(":")[1])
            except:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid HHD token")

        device = db.query(HandHeldDevice).filter(
            HandHeldDevice.id == device_id,
            HandHeldDevice.is_active == True
        ).first()

        if not device:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device not found or inactive")

        return HHDContext(device, payload.get("technician_id"))

    email = sub
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


class BranchCreate(BaseModel):
    client_id: int
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    manager_name: Optional[str] = None
    notes: Optional[str] = None


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    manager_name: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


def branch_to_response(branch: Branch, db: Session) -> dict:
    """Convert Branch model to response dict"""
    projects_count = db.query(Project).filter(Project.branch_id == branch.id).count()
    operators_count = len(branch.operators) if branch.operators else 0

    return {
        "id": branch.id,
        "client_id": branch.client_id,
        "client_name": branch.client.name if branch.client else None,
        "name": branch.name,
        "code": branch.code,
        "address": branch.address,
        "city": branch.city,
        "country": branch.country,
        "phone": branch.phone,
        "email": branch.email,
        "manager_name": branch.manager_name,
        "notes": branch.notes,
        "is_active": branch.is_active,
        "projects_count": projects_count,
        "operators_count": operators_count,
        "created_at": branch.created_at.isoformat()
    }


@router.get("/branches/")
async def get_branches(
    client_id: Optional[int] = None,
    include_inactive: bool = False,
    search: Optional[str] = None,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all branches for the current company (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated"
        )

    # For HHD devices, show all branches from company's clients
    if isinstance(auth_context, HHDContext):
        query = db.query(Branch).join(Client).filter(Client.company_id == auth_context.company_id)
    # For operators, only show branches they're assigned to
    elif auth_context.role == "operator":
        branch_ids = [b.id for b in auth_context.assigned_branches]
        query = db.query(Branch).filter(Branch.id.in_(branch_ids))
    else:
        # For admins, show all branches from company's clients
        query = db.query(Branch).join(Client).filter(Client.company_id == auth_context.company_id)

    if client_id:
        query = query.filter(Branch.client_id == client_id)

    if not include_inactive:
        query = query.filter(Branch.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Branch.name.ilike(search_term)) |
            (Branch.code.ilike(search_term)) |
            (Branch.city.ilike(search_term))
        )

    branches = query.order_by(Branch.name).all()

    return [branch_to_response(branch, db) for branch in branches]


@router.get("/branches/{branch_id}")
async def get_branch(
    branch_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a specific branch (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated"
        )

    branch = db.query(Branch).join(Client).filter(
        Branch.id == branch_id,
        Client.company_id == auth_context.company_id
    ).first()

    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    # Operators can only access their assigned branches (HHD has full access)
    if not isinstance(auth_context, HHDContext) and auth_context.role == "operator":
        if branch.id not in [b.id for b in auth_context.assigned_branches]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this branch"
            )

    return branch_to_response(branch, db)


@router.post("/branches/")
async def create_branch(
    data: BranchCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new branch (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Verify client belongs to company
    client = db.query(Client).filter(
        Client.id == data.client_id,
        Client.company_id == user.company_id
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    # Check plan limits
    company = db.query(Company).filter(Company.id == user.company_id).first()
    if company and company.plan:
        current_count = db.query(Branch).join(Client).filter(
            Client.company_id == user.company_id,
            Branch.is_active == True
        ).count()
        if current_count >= company.plan.max_branches:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Branch limit reached ({company.plan.max_branches}). Upgrade your plan to add more branches."
            )

    try:
        branch = Branch(
            client_id=data.client_id,
            name=data.name,
            code=data.code,
            address=data.address,
            city=data.city,
            country=data.country,
            phone=data.phone,
            email=data.email,
            manager_name=data.manager_name,
            notes=data.notes
        )
        db.add(branch)
        db.commit()
        db.refresh(branch)

        logger.info(f"Branch '{branch.name}' created by '{user.email}'")

        return branch_to_response(branch, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating branch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating branch: {str(e)}"
        )


@router.put("/branches/{branch_id}")
async def update_branch(
    branch_id: int,
    data: BranchUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a branch (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    branch = db.query(Branch).join(Client).filter(
        Branch.id == branch_id,
        Client.company_id == user.company_id
    ).first()

    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(branch, field, value)

        db.commit()
        db.refresh(branch)

        logger.info(f"Branch '{branch.name}' updated by '{user.email}'")

        return branch_to_response(branch, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating branch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating branch: {str(e)}"
        )


@router.delete("/branches/{branch_id}")
async def delete_branch(
    branch_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete a branch (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    branch = db.query(Branch).join(Client).filter(
        Branch.id == branch_id,
        Client.company_id == user.company_id
    ).first()

    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    try:
        branch.is_active = False
        db.commit()

        logger.info(f"Branch '{branch.name}' deactivated by '{user.email}'")

        return {
            "success": True,
            "message": f"Branch '{branch.name}' has been deactivated"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting branch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting branch: {str(e)}"
        )


@router.patch("/branches/{branch_id}/toggle-status")
async def toggle_branch_status(
    branch_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Toggle branch active status (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    branch = db.query(Branch).join(Client).filter(
        Branch.id == branch_id,
        Client.company_id == user.company_id
    ).first()

    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    try:
        branch.is_active = not branch.is_active
        db.commit()
        db.refresh(branch)

        status_text = "activated" if branch.is_active else "deactivated"
        logger.info(f"Branch '{branch.name}' {status_text} by '{user.email}'")

        return branch_to_response(branch, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling branch status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling branch status: {str(e)}"
        )
