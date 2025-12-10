from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import Client, User, Company
from app.utils.security import verify_token
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


class ClientCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ClientResponse(BaseModel):
    id: int
    name: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    city: Optional[str]
    country: Optional[str]
    tax_number: Optional[str]
    contact_person: Optional[str]
    notes: Optional[str]
    is_active: bool
    branches_count: int
    created_at: str

    class Config:
        from_attributes = True


def client_to_response(client: Client, db: Session) -> dict:
    """Convert Client model to response dict"""
    from app.models import Branch
    branches_count = db.query(Branch).filter(Branch.client_id == client.id).count()

    return {
        "id": client.id,
        "name": client.name,
        "email": client.email,
        "phone": client.phone,
        "address": client.address,
        "city": client.city,
        "country": client.country,
        "tax_number": client.tax_number,
        "contact_person": client.contact_person,
        "notes": client.notes,
        "is_active": client.is_active,
        "branches_count": branches_count,
        "created_at": client.created_at.isoformat()
    }


@router.get("/clients/")
async def get_clients(
    include_inactive: bool = False,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all clients for the current company"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    query = db.query(Client).filter(Client.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(Client.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Client.name.ilike(search_term)) |
            (Client.email.ilike(search_term)) |
            (Client.contact_person.ilike(search_term))
        )

    clients = query.order_by(Client.name).all()

    return [client_to_response(client, db) for client in clients]


@router.get("/clients/{client_id}")
async def get_client(
    client_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific client"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == user.company_id
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    return client_to_response(client, db)


@router.post("/clients/")
async def create_client(
    data: ClientCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new client (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Check plan limits
    company = db.query(Company).filter(Company.id == user.company_id).first()
    if company and company.plan:
        current_count = db.query(Client).filter(
            Client.company_id == user.company_id,
            Client.is_active == True
        ).count()
        if current_count >= company.plan.max_clients:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Client limit reached ({company.plan.max_clients}). Upgrade your plan to add more clients."
            )

    try:
        client = Client(
            company_id=user.company_id,
            name=data.name,
            email=data.email,
            phone=data.phone,
            address=data.address,
            city=data.city,
            country=data.country,
            tax_number=data.tax_number,
            contact_person=data.contact_person,
            notes=data.notes
        )
        db.add(client)
        db.commit()
        db.refresh(client)

        logger.info(f"Client '{client.name}' created by '{user.email}'")

        return client_to_response(client, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating client: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating client: {str(e)}"
        )


@router.put("/clients/{client_id}")
async def update_client(
    client_id: int,
    data: ClientUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a client (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == user.company_id
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(client, field, value)

        db.commit()
        db.refresh(client)

        logger.info(f"Client '{client.name}' updated by '{user.email}'")

        return client_to_response(client, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating client: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating client: {str(e)}"
        )


@router.delete("/clients/{client_id}")
async def delete_client(
    client_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete a client (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == user.company_id
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    try:
        client.is_active = False
        db.commit()

        logger.info(f"Client '{client.name}' deactivated by '{user.email}'")

        return {
            "success": True,
            "message": f"Client '{client.name}' has been deactivated"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting client: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting client: {str(e)}"
        )


@router.patch("/clients/{client_id}/toggle-status")
async def toggle_client_status(
    client_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Toggle client active status (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == user.company_id
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    try:
        client.is_active = not client.is_active
        db.commit()
        db.refresh(client)

        status_text = "activated" if client.is_active else "deactivated"
        logger.info(f"Client '{client.name}' {status_text} by '{user.email}'")

        return client_to_response(client, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling client status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling client status: {str(e)}"
        )
