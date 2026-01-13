from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import User, Company, Site, AddressBook, operator_sites
from app.utils.security import verify_token, get_password_hash
from app.utils.limits import enforce_user_limit
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
    site_ids: Optional[List[int]] = None  # Sites to assign operator to


class OperatorUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class SiteAssignment(BaseModel):
    site_ids: List[int]


def operator_to_response(user: User, db: Session) -> dict:
    """Convert User model to operator response dict"""
    # Get assigned sites (using operator_sites relationship)
    assigned_sites = []
    for site in user.assigned_sites:
        # Get client name from Address Book if linked
        client_name = None
        if site.address_book_id:
            ab_entry = db.query(AddressBook).filter(AddressBook.id == site.address_book_id).first()
            if ab_entry:
                client_name = ab_entry.alpha_name
        assigned_sites.append({
            "id": site.id,
            "name": site.name,
            "client_name": client_name
        })

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "role": user.role,
        "is_active": user.is_active,
        "assigned_branches": assigned_sites,  # Keep key for frontend compatibility
        "branches_count": len(assigned_sites),  # Keep key for frontend compatibility
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
    enforce_user_limit(db, user.company_id)

    # Get company for plan info
    company = db.query(Company).filter(Company.id == user.company_id).first()

    # Validate site_ids if provided
    sites = []
    if data.site_ids:
        for site_id in data.site_ids:
            # Sites can be linked via address_book_id to customers
            site = db.query(Site).filter(Site.id == site_id).first()
            if not site:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Site with ID {site_id} not found"
                )
            # Verify site belongs to company (via address_book_id)
            if site.address_book_id:
                ab_entry = db.query(AddressBook).filter(
                    AddressBook.id == site.address_book_id,
                    AddressBook.company_id == user.company_id
                ).first()
                if not ab_entry:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Site with ID {site_id} not found in your company"
                    )
            sites.append(site)

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

        # Add site assignments
        operator.assigned_sites = sites

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
async def update_operator_sites(
    operator_id: int,
    data: SiteAssignment,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update operator's site assignments (admin only)"""
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

    # Validate all site_ids
    sites = []
    for site_id in data.site_ids:
        site = db.query(Site).filter(Site.id == site_id).first()
        if not site:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Site with ID {site_id} not found"
            )
        # Verify site belongs to company (via address_book_id)
        if site.address_book_id:
            ab_entry = db.query(AddressBook).filter(
                AddressBook.id == site.address_book_id,
                AddressBook.company_id == user.company_id
            ).first()
            if not ab_entry:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Site with ID {site_id} not found in your company"
                )
        sites.append(site)

    try:
        # Replace all site assignments
        operator.assigned_sites = sites
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' sites updated by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating operator sites: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating operator sites: {str(e)}"
        )


@router.post("/operators/{operator_id}/branches/{branch_id}")
async def add_operator_to_site(
    operator_id: int,
    branch_id: int,  # This is now site_id but keeping param name for API compatibility
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Add an operator to a site (admin only)"""
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

    site = db.query(Site).filter(Site.id == branch_id).first()

    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found"
        )

    # Verify site belongs to company (via address_book_id)
    if site.address_book_id:
        ab_entry = db.query(AddressBook).filter(
            AddressBook.id == site.address_book_id,
            AddressBook.company_id == user.company_id
        ).first()
        if not ab_entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site not found in your company"
            )

    # Check if already assigned
    if site in operator.assigned_sites:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator is already assigned to this site"
        )

    try:
        operator.assigned_sites.append(site)
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' added to site '{site.name}' by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error adding operator to site: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding operator to site: {str(e)}"
        )


@router.delete("/operators/{operator_id}/branches/{branch_id}")
async def remove_operator_from_site(
    operator_id: int,
    branch_id: int,  # This is now site_id but keeping param name for API compatibility
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Remove an operator from a site (admin only)"""
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

    site = db.query(Site).filter(Site.id == branch_id).first()

    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found"
        )

    if site not in operator.assigned_sites:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Operator is not assigned to this site"
        )

    try:
        operator.assigned_sites.remove(site)
        db.commit()
        db.refresh(operator)

        logger.info(f"Operator '{operator.email}' removed from site '{site.name}' by '{user.email}'")

        return operator_to_response(operator, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error removing operator from site: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error removing operator from site: {str(e)}"
        )
