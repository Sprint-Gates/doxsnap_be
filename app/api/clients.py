from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import Client, User
from app.utils.security import verify_token
from app.schemas import ClientCreate, ClientUpdate, Client as ClientSchema
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


@router.get("/", response_model=List[ClientSchema])
async def get_clients(
    include_inactive: bool = Query(False, description="Include inactive clients"),
    search: Optional[str] = Query(None, description="Search by name or code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all clients for the current user's company"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    query = db.query(Client).filter(Client.company_id == current_user.company_id)

    if not include_inactive:
        query = query.filter(Client.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Client.name.ilike(search_term)) |
            (Client.code.ilike(search_term))
        )

    return query.order_by(Client.name).offset(skip).limit(limit).all()


@router.get("/{client_id}", response_model=ClientSchema)
async def get_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific client by ID"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return client


@router.post("/", response_model=ClientSchema, status_code=status.HTTP_201_CREATED)
async def create_client(
    client_data: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new client"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    # Check for duplicate code within company
    if client_data.code:
        existing = db.query(Client).filter(
            Client.company_id == current_user.company_id,
            Client.code == client_data.code
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Client code already exists")

    client = Client(
        company_id=current_user.company_id,
        **client_data.model_dump()
    )

    db.add(client)
    db.commit()
    db.refresh(client)

    logger.info(f"Created client {client.id} '{client.name}' for company {current_user.company_id}")

    return client


@router.put("/{client_id}", response_model=ClientSchema)
async def update_client(
    client_id: int,
    client_data: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a client"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Check for duplicate code if updating code
    if client_data.code and client_data.code != client.code:
        existing = db.query(Client).filter(
            Client.company_id == current_user.company_id,
            Client.code == client_data.code,
            Client.id != client_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Client code already exists")

    update_data = client_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(client, key, value)

    db.commit()
    db.refresh(client)

    logger.info(f"Updated client {client.id} '{client.name}'")

    return client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a client (soft delete by setting is_active=False)"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Soft delete
    client.is_active = False
    db.commit()

    logger.info(f"Soft deleted client {client.id} '{client.name}'")

    return None


@router.patch("/{client_id}/toggle-status", response_model=ClientSchema)
async def toggle_client_status(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Toggle a client's active status"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.is_active = not client.is_active
    db.commit()
    db.refresh(client)

    status_str = "activated" if client.is_active else "deactivated"
    logger.info(f"Client {client.id} '{client.name}' {status_str}")

    return client
