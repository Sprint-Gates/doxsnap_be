from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from app.database import get_db
from app.models import Warehouse, User
from app.api.auth import get_current_user

router = APIRouter()
security = HTTPBearer()


class WarehouseCreate(BaseModel):
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_name: Optional[str] = None
    capacity: Optional[str] = None
    notes: Optional[str] = None
    is_main: Optional[bool] = False


class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_name: Optional[str] = None
    capacity: Optional[str] = None
    notes: Optional[str] = None
    is_main: Optional[bool] = None
    is_active: Optional[bool] = None


class WarehouseResponse(BaseModel):
    id: int
    name: str
    code: Optional[str]
    address: Optional[str]
    city: Optional[str]
    country: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    manager_name: Optional[str]
    capacity: Optional[str]
    notes: Optional[str]
    is_main: bool
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


def warehouse_to_response(warehouse: Warehouse) -> WarehouseResponse:
    return WarehouseResponse(
        id=warehouse.id,
        name=warehouse.name,
        code=warehouse.code,
        address=warehouse.address,
        city=warehouse.city,
        country=warehouse.country,
        phone=warehouse.phone,
        email=warehouse.email,
        manager_name=warehouse.manager_name,
        capacity=warehouse.capacity,
        notes=warehouse.notes,
        is_main=warehouse.is_main or False,
        is_active=warehouse.is_active,
        created_at=warehouse.created_at.isoformat() if warehouse.created_at else "",
        updated_at=warehouse.updated_at.isoformat() if warehouse.updated_at else ""
    )


@router.get("/warehouses", response_model=List[WarehouseResponse])
async def get_warehouses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False, description="Include inactive warehouses"),
    search: Optional[str] = Query(None, description="Search by name, code, or city")
):
    """Get all warehouses for the current user's company"""
    query = db.query(Warehouse).filter(Warehouse.company_id == current_user.company_id)

    if not include_inactive:
        query = query.filter(Warehouse.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Warehouse.name.ilike(search_term),
                Warehouse.code.ilike(search_term),
                Warehouse.city.ilike(search_term),
                Warehouse.manager_name.ilike(search_term)
            )
        )

    warehouses = query.order_by(Warehouse.name).all()
    return [warehouse_to_response(w) for w in warehouses]


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
async def get_warehouse(
    warehouse_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific warehouse by ID"""
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )

    return warehouse_to_response(warehouse)


@router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    warehouse_data: WarehouseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new warehouse"""
    # Check if warehouse with same name already exists for this company
    existing = db.query(Warehouse).filter(
        Warehouse.name == warehouse_data.name,
        Warehouse.company_id == current_user.company_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A warehouse with this name already exists"
        )

    # Check if code is provided and unique
    if warehouse_data.code:
        existing_code = db.query(Warehouse).filter(
            Warehouse.code == warehouse_data.code,
            Warehouse.company_id == current_user.company_id
        ).first()
        if existing_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A warehouse with this code already exists"
            )

    # If setting as main, clear any existing main warehouse
    if warehouse_data.is_main:
        db.query(Warehouse).filter(
            Warehouse.company_id == current_user.company_id,
            Warehouse.is_main == True
        ).update({"is_main": False})

    warehouse = Warehouse(
        company_id=current_user.company_id,
        name=warehouse_data.name,
        code=warehouse_data.code,
        address=warehouse_data.address,
        city=warehouse_data.city,
        country=warehouse_data.country,
        phone=warehouse_data.phone,
        email=warehouse_data.email,
        manager_name=warehouse_data.manager_name,
        capacity=warehouse_data.capacity,
        notes=warehouse_data.notes,
        is_main=warehouse_data.is_main or False,
        is_active=True
    )

    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)

    return warehouse_to_response(warehouse)


@router.put("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
async def update_warehouse(
    warehouse_id: int,
    warehouse_data: WarehouseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a warehouse"""
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )

    # Check for duplicate name if name is being updated
    if warehouse_data.name and warehouse_data.name != warehouse.name:
        existing = db.query(Warehouse).filter(
            Warehouse.name == warehouse_data.name,
            Warehouse.company_id == current_user.company_id,
            Warehouse.id != warehouse_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A warehouse with this name already exists"
            )

    # Check for duplicate code if code is being updated
    if warehouse_data.code and warehouse_data.code != warehouse.code:
        existing_code = db.query(Warehouse).filter(
            Warehouse.code == warehouse_data.code,
            Warehouse.company_id == current_user.company_id,
            Warehouse.id != warehouse_id
        ).first()
        if existing_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A warehouse with this code already exists"
            )

    # If setting as main, clear any existing main warehouse
    if warehouse_data.is_main:
        db.query(Warehouse).filter(
            Warehouse.company_id == current_user.company_id,
            Warehouse.is_main == True,
            Warehouse.id != warehouse_id
        ).update({"is_main": False})

    # Update fields that are provided
    update_data = warehouse_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(warehouse, field, value)

    db.commit()
    db.refresh(warehouse)

    return warehouse_to_response(warehouse)


@router.patch("/warehouses/{warehouse_id}/toggle-status", response_model=WarehouseResponse)
async def toggle_warehouse_status(
    warehouse_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle warehouse active status (enable/disable)"""
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )

    warehouse.is_active = not warehouse.is_active
    db.commit()
    db.refresh(warehouse)

    return warehouse_to_response(warehouse)


@router.patch("/warehouses/{warehouse_id}/set-main", response_model=WarehouseResponse)
async def set_main_warehouse(
    warehouse_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set a warehouse as the main warehouse for invoice receiving"""
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )

    if not warehouse.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot set an inactive warehouse as main"
        )

    # Clear any existing main warehouse
    db.query(Warehouse).filter(
        Warehouse.company_id == current_user.company_id,
        Warehouse.is_main == True
    ).update({"is_main": False})

    # Set this warehouse as main
    warehouse.is_main = True
    db.commit()
    db.refresh(warehouse)

    return warehouse_to_response(warehouse)


@router.get("/warehouses/main", response_model=Optional[WarehouseResponse])
async def get_main_warehouse(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the main warehouse for the company"""
    warehouse = db.query(Warehouse).filter(
        Warehouse.company_id == current_user.company_id,
        Warehouse.is_main == True,
        Warehouse.is_active == True
    ).first()

    if not warehouse:
        return None

    return warehouse_to_response(warehouse)


@router.delete("/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_warehouse(
    warehouse_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a warehouse (hard delete)"""
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )

    db.delete(warehouse)
    db.commit()

    return None
