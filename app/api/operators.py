from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import User, Company, Branch, Client, operator_branches
from app.utils.security import verify_token, get_password_hash
import logging

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


class OperatorCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    phone: Optional[str] = None
    branch_ids: Optional[List[int]] = None


class OperatorUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class BranchAssignment(BaseModel):
    branch_ids: List[int]


def operator_to_response(user: User, db: Session) -> dict:
    """Convert User model to operator response dict"""
    assigned_branches = []
    for branch in user.assigned_branches:
        assigned_branches.append({
            "id": branch.id,
            "name": branch.name,
            "client_name": branch.client.name if branch.client else None
        })

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "role": user.role,
        "is_active": user.is_active,
        "assigned_branches": assigned_branches,
        "branches_count": len(assigned_branches),
        "created_at": user.created_at.isoformat()
    }


@router.get("/operators/")
async def get_operators(
    include_inactive: bool = False,
    search: Optional[str] = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get all operators for the current company (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    query = db.query(User).filter(
        User.company_id == user.company_id,
        User.role == "operator"
    )

    if not include_inactive:
        query = query.filter(User.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (User.name.ilike(search_term)) |
            (User.email.ilike(search_term))
        )

    operators = query.order_by(User.name).all()

    return [operator_to_response(op, db) for op in operators]


@router.get("/operators/{operator_id}")
async def get_operator(
    operator_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Get a specific operator (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
        )

    return operator_to_response(operator, db)


@router.post("/operators/")
async def create_operator(
    data: OperatorCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new operator (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Check if email already exists
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check plan limits
    company = db.query(Company).filter(Company.id == user.company_id).first()
    if company and company.plan:
        current_count = db.query(User).filter(
            User.company_id == user.company_id,
            User.is_active == True
        ).count()
        if current_count >= company.plan.max_users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User limit reached ({company.plan.max_users}). Upgrade your plan to add more users."
            )

    # Validate branch_ids if provided
    branches = []
    if data.branch_ids:
        for branch_id in data.branch_ids:
            branch = db.query(Branch).join(Client).filter(
                Branch.id == branch_id,
                Client.company_id == user.company_id
            ).first()
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Branch with ID {branch_id} not found"
                )
            branches.append(branch)

    try:
        operator = User(
            email=data.email,
            name=data.name,
            hashed_password=get_password_hash(data.password),
            phone=data.phone,
            company_id=user.company_id,
            role="operator",
            is_active=True,
            remaining_documents=company.plan.documents_max if company and company.plan else 100
        )

        # Add branch assignments
        operator.assigned_branches = branches

        db.add(operator)
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' created by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating operator: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating operator: {str(e)}"
        )


@router.put("/operators/{operator_id}")
async def update_operator(
    operator_id: int,
    data: OperatorUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update an operator (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
        )

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(operator, field, value)

        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' updated by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating operator: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating operator: {str(e)}"
        )


@router.delete("/operators/{operator_id}")
async def delete_operator(
    operator_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deactivate an operator (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
        )

    try:
        operator.is_active = False
        db.commit()

        logger.info(f"Operator '{operator.email}' deactivated by '{user.email}'")

        return {
            "success": True,
            "message": f"Operator '{operator.name}' has been deactivated"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating operator: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deactivating operator: {str(e)}"
        )


@router.patch("/operators/{operator_id}/toggle-status")
async def toggle_operator_status(
    operator_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Toggle operator active status (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
        )

    try:
        operator.is_active = not operator.is_active
        db.commit()
        db.refresh(operator)

        status_text = "activated" if operator.is_active else "deactivated"
        logger.info(f"Operator '{operator.email}' {status_text} by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling operator status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling operator status: {str(e)}"
        )


@router.put("/operators/{operator_id}/branches")
async def update_operator_branches(
    operator_id: int,
    data: BranchAssignment,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update operator's branch assignments (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
        )

    # Validate all branch_ids
    branches = []
    for branch_id in data.branch_ids:
        branch = db.query(Branch).join(Client).filter(
            Branch.id == branch_id,
            Client.company_id == user.company_id
        ).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Branch with ID {branch_id} not found"
            )
        branches.append(branch)

    try:
        # Replace all branch assignments
        operator.assigned_branches = branches
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' branches updated by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating operator branches: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating operator branches: {str(e)}"
        )


@router.post("/operators/{operator_id}/branches/{branch_id}")
async def add_operator_to_branch(
    operator_id: int,
    branch_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Add an operator to a branch (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
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

    # Check if already assigned
    if branch in operator.assigned_branches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator is already assigned to this branch"
        )

    try:
        operator.assigned_branches.append(branch)
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' added to branch '{branch.name}' by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error adding operator to branch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding operator to branch: {str(e)}"
        )


@router.delete("/operators/{operator_id}/branches/{branch_id}")
async def remove_operator_from_branch(
    operator_id: int,
    branch_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Remove an operator from a branch (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    operator = db.query(User).filter(
        User.id == operator_id,
        User.company_id == user.company_id,
        User.role == "operator"
    ).first()

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found"
        )

    branch = db.query(Branch).filter(Branch.id == branch_id).first()

    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    if branch not in operator.assigned_branches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator is not assigned to this branch"
        )

    try:
        operator.assigned_branches.remove(branch)
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' removed from branch '{branch.name}' by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error removing operator from branch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error removing operator from branch: {str(e)}"
        )
