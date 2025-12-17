from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import time
from app.database import get_db
from app.models import Technician, Branch, TechnicianBranchShift, User
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


# ==========================
# Pydantic Schemas
# ==========================

class ShiftCreate(BaseModel):
    technician_id: int
    branch_id: int
    day_of_week: int  # 0 = Monday, 6 = Sunday
    start_time: time
    end_time: time
    is_active: Optional[bool] = True


class ShiftUpdate(BaseModel):
    day_of_week: Optional[int] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_active: Optional[bool] = None


class ShiftResponse(BaseModel):
    id: int
    technician_id: int
    technician_name: str
    branch_id: int
    branch_name: str
    day_of_week: int
    start_time: str
    end_time: str
    is_active: bool

    class Config:
        from_attributes = True


# ==========================
# Helper functions
# ==========================

def shift_to_response(shift: TechnicianBranchShift) -> dict:
    """Convert model to response dict"""
    return {
        "id": shift.id,
        "technician_id": shift.technician_id,
        "technician_name": shift.technician.name if shift.technician else "",
        "branch_id": shift.branch_id,
        "branch_name": shift.branch.name if shift.branch else "",
        "day_of_week": shift.day_of_week,
        "start_time": shift.start_time.isoformat(),
        "end_time": shift.end_time.isoformat(),
        "is_active": shift.is_active
    }


# ==========================
# CRUD Endpoints
# ==========================

@router.get("/shifts/")
async def get_shifts(
    branch_id: Optional[int] = None,
    technician_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve shifts, optionally filtered by branch or technician"""
    query = db.query(TechnicianBranchShift)

    if branch_id:
        query = query.filter(TechnicianBranchShift.branch_id == branch_id)
    if technician_id:
        query = query.filter(TechnicianBranchShift.technician_id == technician_id)

    shifts = query.order_by(
        TechnicianBranchShift.technician_id,
        TechnicianBranchShift.day_of_week,
        TechnicianBranchShift.start_time
    ).all()

    return [shift_to_response(s) for s in shifts]


@router.post("/shifts/")
async def create_shift(
    data: ShiftCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new technician branch shift (admin only)"""
    try:
        # Validate time range
        if data.start_time >= data.end_time:
            raise HTTPException(status_code=400, detail="start_time must be before end_time")

        # Validate technician exists and is active
        technician = db.query(Technician).filter(
            Technician.id == data.technician_id,
            Technician.is_active == True
        ).first()
        if not technician:
            raise HTTPException(status_code=400, detail=f"Technician {data.technician_id} not found or inactive")

        # Validate branch exists and is active
        branch = db.query(Branch).filter(
            Branch.id == data.branch_id,
            Branch.is_active == True
        ).first()
        if not branch:
            raise HTTPException(status_code=400, detail=f"Branch {data.branch_id} not found or inactive")

        # Prevent overlapping shifts
        overlap = db.query(TechnicianBranchShift).filter(
            TechnicianBranchShift.technician_id == data.technician_id,
            TechnicianBranchShift.branch_id == data.branch_id,
            TechnicianBranchShift.day_of_week == data.day_of_week,
            TechnicianBranchShift.is_active == True,
            ((TechnicianBranchShift.start_time <= data.start_time) & (TechnicianBranchShift.end_time > data.start_time)) |
            ((TechnicianBranchShift.start_time < data.end_time) & (TechnicianBranchShift.end_time >= data.end_time)) |
            ((TechnicianBranchShift.start_time >= data.start_time) & (TechnicianBranchShift.end_time <= data.end_time))
        ).first()

        if overlap:
            raise HTTPException(status_code=400, detail="Overlapping shift exists")

        # Create the shift
        shift = TechnicianBranchShift(
            technician_id=data.technician_id,
            branch_id=data.branch_id,
            day_of_week=data.day_of_week,
            start_time=data.start_time,
            end_time=data.end_time,
            is_active=data.is_active
        )

        db.add(shift)
        db.commit()
        db.refresh(shift)

        logger.info(f"Shift created: Technician {shift.technician_id} Branch {shift.branch_id}")

        return shift_to_response(shift)

    except HTTPException:
        # Re-raise HTTPExceptions without wrapping
        raise

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating shift: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating shift: {str(e)}"
        )

@router.put("/shifts/{shift_id}")
async def update_shift(
    shift_id: int,
    data: ShiftUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a shift (admin only)"""
    shift = db.query(TechnicianBranchShift).get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(shift, field, value)

        if shift.start_time >= shift.end_time:
            raise HTTPException(status_code=400, detail="start_time must be before end_time")

        db.commit()
        db.refresh(shift)

        logger.info(f"Shift updated: {shift.id}")

        return shift_to_response(shift)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating shift: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating shift: {str(e)}")


@router.delete("/shifts/{shift_id}")
async def delete_shift(
    shift_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete a shift (admin only)"""
    shift = db.query(TechnicianBranchShift).get(shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")

    try:
        shift.is_active = False
        db.commit()
        logger.info(f"Shift deactivated: {shift.id}")
        return {"success": True, "message": f"Shift {shift.id} deactivated"}

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting shift: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting shift: {str(e)}")
