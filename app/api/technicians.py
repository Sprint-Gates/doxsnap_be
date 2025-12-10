from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional
from decimal import Decimal
from app.database import get_db
from app.models import User, Company, Technician
from app.utils.security import verify_token
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


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def require_accounting(user: User = Depends(get_current_user)):
    """Require accounting role (or admin)"""
    if user.role not in ["accounting", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accounting access required"
        )
    return user


class TechnicianCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    notes: Optional[str] = None


class TechnicianUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SalaryBreakdownUpdate(BaseModel):
    """Salary breakdown - accounting only"""
    salary_type: Optional[str] = None  # monthly, hourly, daily
    base_salary: Optional[float] = None
    currency: Optional[str] = None
    hourly_rate: Optional[float] = None
    overtime_rate_multiplier: Optional[float] = None
    working_hours_per_day: Optional[float] = None
    working_days_per_month: Optional[int] = None
    # Allowances
    transport_allowance: Optional[float] = None
    housing_allowance: Optional[float] = None
    food_allowance: Optional[float] = None
    other_allowances: Optional[float] = None
    allowances_notes: Optional[str] = None
    # Deductions
    social_security_rate: Optional[float] = None
    tax_rate: Optional[float] = None
    other_deductions: Optional[float] = None
    deductions_notes: Optional[str] = None


def decimal_to_float(value) -> Optional[float]:
    """Convert Decimal to float for JSON serialization"""
    if value is None:
        return None
    return float(value)


def technician_to_response(technician: Technician, include_salary: bool = False) -> dict:
    """Convert Technician model to response dict"""
    response = {
        "id": technician.id,
        "name": technician.name,
        "email": technician.email,
        "phone": technician.phone,
        "employee_id": technician.employee_id,
        "specialization": technician.specialization,
        "notes": technician.notes,
        "is_active": technician.is_active,
        "created_at": technician.created_at.isoformat(),
        "updated_at": technician.updated_at.isoformat() if technician.updated_at else None
    }

    if include_salary:
        response["salary_breakdown"] = {
            "salary_type": technician.salary_type,
            "base_salary": decimal_to_float(technician.base_salary),
            "currency": technician.currency,
            "hourly_rate": decimal_to_float(technician.hourly_rate),
            "overtime_rate_multiplier": decimal_to_float(technician.overtime_rate_multiplier),
            "working_hours_per_day": decimal_to_float(technician.working_hours_per_day),
            "working_days_per_month": technician.working_days_per_month,
            # Allowances
            "transport_allowance": decimal_to_float(technician.transport_allowance),
            "housing_allowance": decimal_to_float(technician.housing_allowance),
            "food_allowance": decimal_to_float(technician.food_allowance),
            "other_allowances": decimal_to_float(technician.other_allowances),
            "allowances_notes": technician.allowances_notes,
            # Deductions
            "social_security_rate": decimal_to_float(technician.social_security_rate),
            "tax_rate": decimal_to_float(technician.tax_rate),
            "other_deductions": decimal_to_float(technician.other_deductions),
            "deductions_notes": technician.deductions_notes,
            # Computed values
            "total_allowances": decimal_to_float(
                (technician.transport_allowance or 0) +
                (technician.housing_allowance or 0) +
                (technician.food_allowance or 0) +
                (technician.other_allowances or 0)
            ),
            "computed_hourly_rate": compute_hourly_rate(technician)
        }

    return response


def compute_hourly_rate(technician: Technician) -> Optional[float]:
    """Compute hourly rate from salary breakdown"""
    if technician.hourly_rate:
        return float(technician.hourly_rate)

    if technician.base_salary and technician.working_hours_per_day and technician.working_days_per_month:
        hours_per_month = float(technician.working_hours_per_day) * technician.working_days_per_month
        if hours_per_month > 0:
            return float(technician.base_salary) / hours_per_month

    return None


@router.get("/technicians/")
async def get_technicians(
    include_inactive: bool = False,
    search: Optional[str] = None,
    specialization: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all technicians for the current company"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    query = db.query(Technician).filter(Technician.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(Technician.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Technician.name.ilike(search_term)) |
            (Technician.email.ilike(search_term)) |
            (Technician.phone.ilike(search_term)) |
            (Technician.employee_id.ilike(search_term))
        )

    if specialization:
        query = query.filter(Technician.specialization == specialization)

    technicians = query.order_by(Technician.name).all()

    return [technician_to_response(tech) for tech in technicians]


@router.get("/technicians/specializations")
async def get_specializations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get unique specializations for the current company"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    specializations = db.query(Technician.specialization).filter(
        Technician.company_id == user.company_id,
        Technician.specialization.isnot(None),
        Technician.specialization != ""
    ).distinct().all()

    return [s[0] for s in specializations if s[0]]


@router.get("/technicians/{technician_id}")
async def get_technician(
    technician_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific technician"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    return technician_to_response(technician)


@router.post("/technicians/")
async def create_technician(
    data: TechnicianCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new technician (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Check if employee_id already exists within the company
    if data.employee_id:
        existing = db.query(Technician).filter(
            Technician.company_id == user.company_id,
            Technician.employee_id == data.employee_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee ID already exists"
            )

    try:
        technician = Technician(
            company_id=user.company_id,
            name=data.name,
            email=data.email,
            phone=data.phone,
            employee_id=data.employee_id,
            specialization=data.specialization,
            notes=data.notes
        )

        db.add(technician)
        db.commit()
        db.refresh(technician)

        logger.info(f"Technician '{technician.name}' created by '{user.email}'")

        return technician_to_response(technician)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating technician: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating technician: {str(e)}"
        )


@router.put("/technicians/{technician_id}")
async def update_technician(
    technician_id: int,
    data: TechnicianUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a technician (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    # Check if employee_id already exists for another technician
    if data.employee_id:
        existing = db.query(Technician).filter(
            Technician.company_id == user.company_id,
            Technician.employee_id == data.employee_id,
            Technician.id != technician_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee ID already exists"
            )

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(technician, field, value)

        db.commit()
        db.refresh(technician)

        logger.info(f"Technician '{technician.name}' updated by '{user.email}'")

        return technician_to_response(technician)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating technician: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating technician: {str(e)}"
        )


@router.delete("/technicians/{technician_id}")
async def delete_technician(
    technician_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deactivate a technician (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    try:
        technician.is_active = False
        db.commit()

        logger.info(f"Technician '{technician.name}' deactivated by '{user.email}'")

        return {
            "success": True,
            "message": f"Technician '{technician.name}' has been deactivated"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating technician: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deactivating technician: {str(e)}"
        )


@router.patch("/technicians/{technician_id}/toggle-status")
async def toggle_technician_status(
    technician_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Toggle technician active status (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    try:
        technician.is_active = not technician.is_active
        db.commit()
        db.refresh(technician)

        status_text = "activated" if technician.is_active else "deactivated"
        logger.info(f"Technician '{technician.name}' {status_text} by '{user.email}'")

        return technician_to_response(technician)

    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling technician status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling technician status: {str(e)}"
        )


# ============================================================================
# Salary Breakdown Endpoints (Accounting Only)
# ============================================================================

@router.get("/technicians/{technician_id}/salary")
async def get_technician_salary(
    technician_id: int,
    user: User = Depends(require_accounting),
    db: Session = Depends(get_db)
):
    """Get technician salary breakdown (accounting only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    return technician_to_response(technician, include_salary=True)


@router.put("/technicians/{technician_id}/salary")
async def update_technician_salary(
    technician_id: int,
    data: SalaryBreakdownUpdate,
    user: User = Depends(require_accounting),
    db: Session = Depends(get_db)
):
    """Update technician salary breakdown (accounting only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    # Validate salary_type if provided
    if data.salary_type and data.salary_type not in ["monthly", "hourly", "daily"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="salary_type must be 'monthly', 'hourly', or 'daily'"
        )

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(technician, field, value)

        db.commit()
        db.refresh(technician)

        logger.info(f"Technician '{technician.name}' salary updated by '{user.email}'")

        return technician_to_response(technician, include_salary=True)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating technician salary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating technician salary: {str(e)}"
        )


@router.get("/technicians/salary/all")
async def get_all_technicians_with_salary(
    include_inactive: bool = False,
    user: User = Depends(require_accounting),
    db: Session = Depends(get_db)
):
    """Get all technicians with salary breakdown (accounting only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    query = db.query(Technician).filter(Technician.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(Technician.is_active == True)

    technicians = query.order_by(Technician.name).all()

    return [technician_to_response(tech, include_salary=True) for tech in technicians]


@router.get("/technicians/{technician_id}/hourly-cost")
async def get_technician_hourly_cost(
    technician_id: int,
    user: User = Depends(require_accounting),
    db: Session = Depends(get_db)
):
    """Get technician's effective hourly cost for work order calculations (accounting only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    hourly_rate = compute_hourly_rate(technician)
    overtime_rate = None
    if hourly_rate and technician.overtime_rate_multiplier:
        overtime_rate = hourly_rate * float(technician.overtime_rate_multiplier)

    # Calculate hourly cost including allowances
    hourly_allowances = 0.0
    if technician.working_hours_per_day and technician.working_days_per_month:
        hours_per_month = float(technician.working_hours_per_day) * technician.working_days_per_month
        if hours_per_month > 0:
            total_allowances = (
                float(technician.transport_allowance or 0) +
                float(technician.housing_allowance or 0) +
                float(technician.food_allowance or 0) +
                float(technician.other_allowances or 0)
            )
            hourly_allowances = total_allowances / hours_per_month

    total_hourly_cost = (hourly_rate or 0) + hourly_allowances

    return {
        "technician_id": technician.id,
        "technician_name": technician.name,
        "currency": technician.currency,
        "base_hourly_rate": hourly_rate,
        "hourly_allowances": round(hourly_allowances, 2) if hourly_allowances else None,
        "total_hourly_cost": round(total_hourly_cost, 2) if total_hourly_cost else None,
        "overtime_hourly_rate": round(overtime_rate, 2) if overtime_rate else None,
        "overtime_multiplier": decimal_to_float(technician.overtime_rate_multiplier)
    }
