"""
Technicians API - Backward compatibility layer for work orders.

Technicians have been migrated to AddressBook with search_type='E' (Employee).
This module provides backward-compatible endpoints that the Work Orders UI uses.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from app.database import get_db
from app.models import Technician, User, AddressBook
from app.utils.security import verify_token
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


# ============================================================================
# Response Schema (matching frontend Technician interface)
# ============================================================================

class TechnicianResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True
    address_book_id: Optional[int] = None

    class Config:
        from_attributes = True


class TechnicianCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    notes: Optional[str] = None


class TechnicianUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class TechnicianHourlyCost(BaseModel):
    technician_id: int
    technician_name: str
    hourly_cost: float
    currency: str
    calculation_basis: str


# ============================================================================
# Auth Helpers
# ============================================================================

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


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


# ============================================================================
# Helper: Convert AddressBook Employee to Technician format
# ============================================================================

def employee_to_technician(ab: AddressBook) -> dict:
    """Convert AddressBook employee entry to Technician response format"""
    return {
        "id": ab.id,  # Use address_book ID as technician ID
        "name": ab.alpha_name or ab.mailing_name or "Unknown",
        "email": ab.email,
        "phone": ab.phone_primary,
        "employee_id": ab.employee_id,
        "specialization": ab.specialization,
        "notes": ab.notes,
        "is_active": ab.is_active,
        "address_book_id": ab.id
    }


# ============================================================================
# CRUD Endpoints - Fetching from AddressBook (search_type='E')
# ============================================================================

@router.get("/technicians/", response_model=List[TechnicianResponse])
async def get_technicians(
    include_inactive: bool = Query(False, description="Include inactive technicians"),
    search: Optional[str] = Query(None, description="Search by name, email, or employee ID"),
    specialization: Optional[str] = Query(None, description="Filter by specialization"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all technicians (employees) for the company.

    This endpoint fetches from AddressBook where search_type='E' (Employee).
    """
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    query = db.query(AddressBook).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"  # Employee type
    )

    if not include_inactive:
        query = query.filter(AddressBook.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.mailing_name.ilike(search_term),
                AddressBook.email.ilike(search_term),
                AddressBook.employee_id.ilike(search_term),
                AddressBook.phone_primary.ilike(search_term)
            )
        )

    if specialization:
        query = query.filter(AddressBook.specialization == specialization)

    employees = query.order_by(AddressBook.alpha_name).all()

    return [employee_to_technician(emp) for emp in employees]


@router.get("/technicians/specializations", response_model=List[str])
async def get_technician_specializations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get unique list of technician/employee specializations"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    result = db.query(AddressBook.specialization).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E",
        AddressBook.specialization.isnot(None),
        AddressBook.is_active == True
    ).distinct().all()

    return [r[0] for r in result if r[0]]


@router.get("/technicians/{technician_id}", response_model=TechnicianResponse)
async def get_technician(
    technician_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific technician (employee from AddressBook)"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    # technician_id is actually address_book_id
    employee = db.query(AddressBook).filter(
        AddressBook.id == technician_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Technician not found")

    return employee_to_technician(employee)


@router.post("/technicians/", response_model=TechnicianResponse)
async def create_technician(
    data: TechnicianCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Create a new technician (creates AddressBook entry with search_type='E').
    """
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    # Generate address number
    from app.api.address_book import generate_next_address_number
    address_number = generate_next_address_number(db, current_user.company_id)

    employee = AddressBook(
        company_id=current_user.company_id,
        address_number=address_number,
        search_type="E",  # Employee
        alpha_name=data.name,
        mailing_name=data.name,
        email=data.email,
        phone_primary=data.phone,
        employee_id=data.employee_id,
        specialization=data.specialization,
        notes=data.notes,
        is_active=True
    )

    db.add(employee)
    db.commit()
    db.refresh(employee)

    logger.info(f"Technician/Employee created: {employee.alpha_name} (ID: {employee.id})")
    return employee_to_technician(employee)


@router.put("/technicians/{technician_id}", response_model=TechnicianResponse)
async def update_technician(
    technician_id: int,
    data: TechnicianUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a technician (employee in AddressBook)"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    employee = db.query(AddressBook).filter(
        AddressBook.id == technician_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Technician not found")

    if data.name is not None:
        employee.alpha_name = data.name
        employee.mailing_name = data.name
    if data.email is not None:
        employee.email = data.email
    if data.phone is not None:
        employee.phone_primary = data.phone
    if data.employee_id is not None:
        employee.employee_id = data.employee_id
    if data.specialization is not None:
        employee.specialization = data.specialization
    if data.notes is not None:
        employee.notes = data.notes
    if data.is_active is not None:
        employee.is_active = data.is_active

    db.commit()
    db.refresh(employee)

    logger.info(f"Technician/Employee updated: {employee.alpha_name} (ID: {employee.id})")
    return employee_to_technician(employee)


@router.delete("/technicians/{technician_id}")
async def delete_technician(
    technician_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Deactivate a technician (soft delete)"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    employee = db.query(AddressBook).filter(
        AddressBook.id == technician_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Technician not found")

    employee.is_active = False
    db.commit()

    logger.info(f"Technician/Employee deactivated: {employee.alpha_name} (ID: {employee.id})")
    return {"success": True, "message": f"Technician '{employee.alpha_name}' has been deactivated"}


@router.patch("/technicians/{technician_id}/toggle-status", response_model=TechnicianResponse)
async def toggle_technician_status(
    technician_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Toggle technician active status"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    employee = db.query(AddressBook).filter(
        AddressBook.id == technician_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Technician not found")

    employee.is_active = not employee.is_active
    db.commit()
    db.refresh(employee)

    status_str = "activated" if employee.is_active else "deactivated"
    logger.info(f"Technician/Employee {status_str}: {employee.alpha_name} (ID: {employee.id})")
    return employee_to_technician(employee)


# ============================================================================
# Salary Endpoints (using AddressBook salary fields)
# ============================================================================

@router.get("/technicians/{technician_id}/salary", response_model=TechnicianResponse)
async def get_technician_salary(
    technician_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get technician with salary breakdown"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    employee = db.query(AddressBook).filter(
        AddressBook.id == technician_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Technician not found")

    return employee_to_technician(employee)


@router.get("/technicians/salary/all", response_model=List[TechnicianResponse])
async def get_all_technicians_with_salary(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all technicians with salary info"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    query = db.query(AddressBook).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    )

    if not include_inactive:
        query = query.filter(AddressBook.is_active == True)

    employees = query.order_by(AddressBook.alpha_name).all()
    return [employee_to_technician(emp) for emp in employees]


@router.get("/technicians/{technician_id}/hourly-cost", response_model=TechnicianHourlyCost)
async def get_technician_hourly_cost(
    technician_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Calculate technician's hourly cost based on salary breakdown"""
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated with user")

    employee = db.query(AddressBook).filter(
        AddressBook.id == technician_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Technician not found")

    # Calculate hourly cost from AddressBook salary fields
    if employee.salary_type == "hourly" and employee.hourly_rate:
        hourly_cost = float(employee.hourly_rate)
    elif employee.base_salary and employee.working_hours_per_day and employee.working_days_per_month:
        monthly_hours = float(employee.working_hours_per_day) * float(employee.working_days_per_month)
        total_monthly = float(employee.base_salary or 0)

        # Add allowances
        total_monthly += float(employee.transport_allowance or 0)
        total_monthly += float(employee.housing_allowance or 0)
        total_monthly += float(employee.food_allowance or 0)
        total_monthly += float(employee.other_allowances or 0)

        hourly_cost = total_monthly / monthly_hours if monthly_hours > 0 else 0
    else:
        hourly_cost = 0

    return TechnicianHourlyCost(
        technician_id=employee.id,
        technician_name=employee.alpha_name or "Unknown",
        hourly_cost=round(hourly_cost, 2),
        currency=employee.salary_currency or "USD",
        calculation_basis=employee.salary_type or "unknown"
    )
