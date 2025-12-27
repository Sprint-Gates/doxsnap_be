"""
Attendance API endpoints for tracking technician availability
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging

from app.database import get_db
from app.models import User, Technician, TechnicianAttendance, AddressBook
from app.api.auth import verify_token

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)


# ============ Pydantic Schemas ============

class AttendanceCreate(BaseModel):
    technician_id: int
    date: date
    status: str = "present"  # present, absent, late, half_day, on_leave, holiday
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    break_duration_minutes: Optional[int] = 0
    hours_worked: Optional[float] = None
    overtime_hours: Optional[float] = 0
    leave_type: Optional[str] = None
    leave_approved: Optional[bool] = False
    check_in_location: Optional[str] = None
    check_out_location: Optional[str] = None
    notes: Optional[str] = None


class AttendanceUpdate(BaseModel):
    status: Optional[str] = None
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    break_duration_minutes: Optional[int] = None
    hours_worked: Optional[float] = None
    overtime_hours: Optional[float] = None
    leave_type: Optional[str] = None
    leave_approved: Optional[bool] = None
    check_in_location: Optional[str] = None
    check_out_location: Optional[str] = None
    notes: Optional[str] = None


class BulkAttendanceCreate(BaseModel):
    date: date
    records: List[dict]  # List of {technician_id, status, notes, etc.}


# AddressBook-based attendance schemas
class EmployeeAttendanceCreate(BaseModel):
    """Create attendance record using AddressBook employee ID"""
    address_book_id: int
    date: date
    status: str = "present"  # present, absent, late, half_day, on_leave, holiday
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    break_duration_minutes: Optional[int] = 0
    hours_worked: Optional[float] = None
    overtime_hours: Optional[float] = 0
    leave_type: Optional[str] = None
    leave_approved: Optional[bool] = False
    check_in_location: Optional[str] = None
    check_out_location: Optional[str] = None
    notes: Optional[str] = None


class BulkEmployeeAttendanceCreate(BaseModel):
    """Create bulk attendance using AddressBook employee IDs"""
    date: date
    records: List[dict]  # List of {address_book_id, status, notes, etc.}


# ============ Dependencies ============

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin_or_accounting(user: User = Depends(get_current_user)):
    """Require admin or accounting role"""
    if user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or accounting access required")
    return user


# ============ Helper Functions ============

def decimal_to_float(val):
    """Convert Decimal to float for JSON serialization"""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return val


def calculate_hours_worked(check_in: datetime, check_out: datetime, break_minutes: int = 0) -> float:
    """Calculate hours worked from check-in/check-out times"""
    if not check_in or not check_out:
        return None

    duration = check_out - check_in
    total_minutes = duration.total_seconds() / 60
    worked_minutes = total_minutes - break_minutes
    return round(worked_minutes / 60, 2)


def attendance_to_response(attendance: TechnicianAttendance, include_technician: bool = False, include_employee: bool = False) -> dict:
    """Convert Attendance model to response dict"""
    response = {
        "id": attendance.id,
        "company_id": attendance.company_id,
        "technician_id": attendance.technician_id,  # Legacy
        "address_book_id": attendance.address_book_id,  # New AddressBook-based
        "date": attendance.date.isoformat() if attendance.date else None,
        "status": attendance.status,
        "check_in": attendance.check_in.isoformat() if attendance.check_in else None,
        "check_out": attendance.check_out.isoformat() if attendance.check_out else None,
        "break_duration_minutes": attendance.break_duration_minutes,
        "hours_worked": decimal_to_float(attendance.hours_worked),
        "overtime_hours": decimal_to_float(attendance.overtime_hours),
        "leave_type": attendance.leave_type,
        "leave_approved": attendance.leave_approved,
        "leave_approved_by": attendance.leave_approved_by,
        "check_in_location": attendance.check_in_location,
        "check_out_location": attendance.check_out_location,
        "notes": attendance.notes,
        "created_by": attendance.created_by,
        "updated_by": attendance.updated_by,
        "created_at": attendance.created_at.isoformat() if attendance.created_at else None,
        "updated_at": attendance.updated_at.isoformat() if attendance.updated_at else None
    }

    # Legacy technician info
    if include_technician and attendance.technician:
        response["technician"] = {
            "id": attendance.technician.id,
            "name": attendance.technician.name,
            "employee_id": attendance.technician.employee_id,
            "specialization": attendance.technician.specialization
        }

    # New AddressBook employee info
    if include_employee and attendance.address_book:
        response["employee"] = {
            "address_book_id": attendance.address_book.id,
            "address_number": attendance.address_book.address_number,
            "name": attendance.address_book.alpha_name,
            "employee_id": attendance.address_book.employee_id,
            "specialization": attendance.address_book.specialization,
            "phone": attendance.address_book.phone_primary,
            "email": attendance.address_book.email
        }

    return response


# ============ Endpoints ============

@router.get("/attendance/")
async def get_attendance_records(
    start_date: Optional[date] = Query(None, description="Start date for filtering"),
    end_date: Optional[date] = Query(None, description="End date for filtering"),
    technician_id: Optional[int] = Query(None, description="Filter by technician"),
    status: Optional[str] = Query(None, description="Filter by status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get attendance records for the company"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(TechnicianAttendance).filter(TechnicianAttendance.company_id == user.company_id)

    # Apply date filters
    if start_date:
        query = query.filter(TechnicianAttendance.date >= start_date)
    if end_date:
        query = query.filter(TechnicianAttendance.date <= end_date)

    # Apply technician filter
    if technician_id:
        query = query.filter(TechnicianAttendance.technician_id == technician_id)

    # Apply status filter
    if status:
        query = query.filter(TechnicianAttendance.status == status)

    records = query.order_by(TechnicianAttendance.date.desc(), TechnicianAttendance.technician_id).all()

    return [attendance_to_response(record, include_technician=True) for record in records]


@router.get("/attendance/daily/{record_date}")
async def get_daily_attendance(
    record_date: date,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get attendance for all technicians on a specific date"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get all active technicians
    technicians = db.query(Technician).filter(
        Technician.company_id == user.company_id,
        Technician.is_active == True
    ).order_by(Technician.name).all()

    # Get existing attendance records for the date
    existing_records = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.company_id == user.company_id,
        TechnicianAttendance.date == record_date
    ).all()

    # Create a map of technician_id -> attendance record
    attendance_map = {record.technician_id: record for record in existing_records}

    # Build response with all technicians
    result = []
    for tech in technicians:
        if tech.id in attendance_map:
            record = attendance_map[tech.id]
            result.append(attendance_to_response(record, include_technician=True))
        else:
            # No record exists, return placeholder
            result.append({
                "id": None,
                "company_id": user.company_id,
                "technician_id": tech.id,
                "date": record_date.isoformat(),
                "status": None,  # Not marked yet
                "check_in": None,
                "check_out": None,
                "break_duration_minutes": 0,
                "hours_worked": None,
                "overtime_hours": 0,
                "leave_type": None,
                "leave_approved": False,
                "leave_approved_by": None,
                "check_in_location": None,
                "check_out_location": None,
                "notes": None,
                "created_at": None,
                "updated_at": None,
                "technician": {
                    "id": tech.id,
                    "name": tech.name,
                    "employee_id": tech.employee_id,
                    "specialization": tech.specialization
                }
            })

    return result


@router.get("/attendance/summary")
async def get_attendance_summary(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    technician_id: Optional[int] = Query(None, description="Filter by technician"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get attendance summary for a date range"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.company_id == user.company_id,
        TechnicianAttendance.date >= start_date,
        TechnicianAttendance.date <= end_date
    )

    if technician_id:
        query = query.filter(TechnicianAttendance.technician_id == technician_id)

    records = query.all()

    # Calculate summary stats
    summary = {
        "total_records": len(records),
        "present": sum(1 for r in records if r.status == "present"),
        "absent": sum(1 for r in records if r.status == "absent"),
        "late": sum(1 for r in records if r.status == "late"),
        "half_day": sum(1 for r in records if r.status == "half_day"),
        "on_leave": sum(1 for r in records if r.status == "on_leave"),
        "holiday": sum(1 for r in records if r.status == "holiday"),
        "total_hours_worked": sum(float(r.hours_worked or 0) for r in records),
        "total_overtime_hours": sum(float(r.overtime_hours or 0) for r in records),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }

    # Get per-technician breakdown if not filtered
    if not technician_id:
        technician_stats = {}
        for record in records:
            tech_id = record.technician_id
            if tech_id not in technician_stats:
                technician_stats[tech_id] = {
                    "technician_id": tech_id,
                    "technician_name": record.technician.name if record.technician else "Unknown",
                    "present": 0,
                    "absent": 0,
                    "late": 0,
                    "on_leave": 0,
                    "hours_worked": 0,
                    "overtime_hours": 0
                }

            stats = technician_stats[tech_id]
            if record.status == "present":
                stats["present"] += 1
            elif record.status == "absent":
                stats["absent"] += 1
            elif record.status == "late":
                stats["late"] += 1
            elif record.status in ["on_leave", "half_day"]:
                stats["on_leave"] += 1

            stats["hours_worked"] += float(record.hours_worked or 0)
            stats["overtime_hours"] += float(record.overtime_hours or 0)

        summary["by_technician"] = list(technician_stats.values())

    return summary


@router.get("/attendance/{attendance_id}")
async def get_attendance_record(
    attendance_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific attendance record"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    record = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.id == attendance_id,
        TechnicianAttendance.company_id == user.company_id
    ).first()

    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    return attendance_to_response(record, include_technician=True)


@router.post("/attendance/")
async def create_attendance_record(
    data: AttendanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new attendance record"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify technician belongs to company
    technician = db.query(Technician).filter(
        Technician.id == data.technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technician not found")

    # Check if record already exists for this technician and date
    existing = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.technician_id == data.technician_id,
        TechnicianAttendance.date == data.date,
        TechnicianAttendance.company_id == user.company_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attendance record already exists for {technician.name} on {data.date}"
        )

    try:
        # Calculate hours worked if check-in/check-out provided
        hours_worked = data.hours_worked
        if not hours_worked and data.check_in and data.check_out:
            hours_worked = calculate_hours_worked(data.check_in, data.check_out, data.break_duration_minutes or 0)

        record = TechnicianAttendance(
            company_id=user.company_id,
            technician_id=data.technician_id,
            date=data.date,
            status=data.status,
            check_in=data.check_in,
            check_out=data.check_out,
            break_duration_minutes=data.break_duration_minutes or 0,
            hours_worked=hours_worked,
            overtime_hours=data.overtime_hours or 0,
            leave_type=data.leave_type,
            leave_approved=data.leave_approved or False,
            check_in_location=data.check_in_location,
            check_out_location=data.check_out_location,
            notes=data.notes,
            created_by=user.id
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        logger.info(f"Attendance record created for technician {technician.name} on {data.date} by {user.email}")
        return attendance_to_response(record, include_technician=True)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating attendance record: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating attendance record: {str(e)}")


@router.post("/attendance/bulk")
async def create_bulk_attendance(
    data: BulkAttendanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create attendance records for multiple technicians at once"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    created = []
    errors = []

    for record_data in data.records:
        technician_id = record_data.get("technician_id")

        # Verify technician belongs to company
        technician = db.query(Technician).filter(
            Technician.id == technician_id,
            Technician.company_id == user.company_id
        ).first()

        if not technician:
            errors.append({"technician_id": technician_id, "error": "Technician not found"})
            continue

        # Check if record already exists
        existing = db.query(TechnicianAttendance).filter(
            TechnicianAttendance.technician_id == technician_id,
            TechnicianAttendance.date == data.date,
            TechnicianAttendance.company_id == user.company_id
        ).first()

        if existing:
            # Update existing record
            existing.status = record_data.get("status", existing.status)
            existing.notes = record_data.get("notes", existing.notes)
            existing.check_in = record_data.get("check_in", existing.check_in)
            existing.check_out = record_data.get("check_out", existing.check_out)
            existing.leave_type = record_data.get("leave_type", existing.leave_type)
            existing.updated_by = user.id
            created.append(attendance_to_response(existing, include_technician=True))
        else:
            # Create new record
            try:
                record = TechnicianAttendance(
                    company_id=user.company_id,
                    technician_id=technician_id,
                    date=data.date,
                    status=record_data.get("status", "present"),
                    check_in=record_data.get("check_in"),
                    check_out=record_data.get("check_out"),
                    break_duration_minutes=record_data.get("break_duration_minutes", 0),
                    hours_worked=record_data.get("hours_worked"),
                    overtime_hours=record_data.get("overtime_hours", 0),
                    leave_type=record_data.get("leave_type"),
                    leave_approved=record_data.get("leave_approved", False),
                    notes=record_data.get("notes"),
                    created_by=user.id
                )
                db.add(record)
                db.flush()
                created.append(attendance_to_response(record, include_technician=True))
            except Exception as e:
                errors.append({"technician_id": technician_id, "error": str(e)})

    try:
        db.commit()
        logger.info(f"Bulk attendance created/updated for {len(created)} technicians on {data.date} by {user.email}")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in bulk attendance creation: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating attendance records: {str(e)}")

    return {
        "created": len(created),
        "errors": len(errors),
        "records": created,
        "error_details": errors if errors else None
    }


@router.put("/attendance/{attendance_id}")
async def update_attendance_record(
    attendance_id: int,
    data: AttendanceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an attendance record"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    record = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.id == attendance_id,
        TechnicianAttendance.company_id == user.company_id
    ).first()

    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    try:
        update_data = data.dict(exclude_unset=True)

        for field, value in update_data.items():
            if value is not None:
                setattr(record, field, value)

        # Recalculate hours if check-in/check-out updated
        if ("check_in" in update_data or "check_out" in update_data) and record.check_in and record.check_out:
            if "hours_worked" not in update_data:
                record.hours_worked = calculate_hours_worked(
                    record.check_in,
                    record.check_out,
                    record.break_duration_minutes or 0
                )

        record.updated_by = user.id
        db.commit()
        db.refresh(record)

        logger.info(f"Attendance record {attendance_id} updated by {user.email}")
        return attendance_to_response(record, include_technician=True)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating attendance record: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error updating attendance record: {str(e)}")


@router.delete("/attendance/{attendance_id}")
async def delete_attendance_record(
    attendance_id: int,
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Delete an attendance record (admin/accounting only)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    record = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.id == attendance_id,
        TechnicianAttendance.company_id == user.company_id
    ).first()

    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    try:
        db.delete(record)
        db.commit()
        logger.info(f"Attendance record {attendance_id} deleted by {user.email}")
        return {"success": True, "message": "Attendance record deleted"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting attendance record: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting attendance record: {str(e)}")


@router.patch("/attendance/{attendance_id}/approve-leave")
async def approve_leave(
    attendance_id: int,
    approved: bool = True,
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Approve or reject leave request (admin/accounting only)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    record = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.id == attendance_id,
        TechnicianAttendance.company_id == user.company_id
    ).first()

    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    if record.status != "on_leave":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This record is not a leave request")

    record.leave_approved = approved
    record.leave_approved_by = user.id
    record.updated_by = user.id

    db.commit()
    db.refresh(record)

    action = "approved" if approved else "rejected"
    logger.info(f"Leave request {attendance_id} {action} by {user.email}")

    return attendance_to_response(record, include_technician=True)


@router.get("/attendance/technician/{technician_id}/monthly")
async def get_technician_monthly_attendance(
    technician_id: int,
    year: int = Query(..., description="Year"),
    month: int = Query(..., description="Month (1-12)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get monthly attendance for a specific technician"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify technician belongs to company
    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id
    ).first()

    if not technician:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technician not found")

    # Calculate date range for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    records = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.technician_id == technician_id,
        TechnicianAttendance.company_id == user.company_id,
        TechnicianAttendance.date >= start_date,
        TechnicianAttendance.date <= end_date
    ).order_by(TechnicianAttendance.date).all()

    # Build calendar view
    calendar = {}
    current = start_date
    while current <= end_date:
        calendar[current.isoformat()] = None
        current += timedelta(days=1)

    # Fill in attendance data
    for record in records:
        calendar[record.date.isoformat()] = attendance_to_response(record)

    # Summary stats
    summary = {
        "present": sum(1 for r in records if r.status == "present"),
        "absent": sum(1 for r in records if r.status == "absent"),
        "late": sum(1 for r in records if r.status == "late"),
        "half_day": sum(1 for r in records if r.status == "half_day"),
        "on_leave": sum(1 for r in records if r.status == "on_leave"),
        "holiday": sum(1 for r in records if r.status == "holiday"),
        "total_hours": sum(float(r.hours_worked or 0) for r in records),
        "total_overtime": sum(float(r.overtime_hours or 0) for r in records),
        "working_days": len([r for r in records if r.status in ["present", "late", "half_day"]])
    }

    return {
        "technician": {
            "id": technician.id,
            "name": technician.name,
            "employee_id": technician.employee_id
        },
        "year": year,
        "month": month,
        "calendar": calendar,
        "summary": summary
    }


# ============ Employee Attendance Endpoints (AddressBook-based) ============

@router.get("/attendance/employees/")
async def get_employee_attendance_records(
    start_date: Optional[date] = Query(None, description="Start date for filtering"),
    end_date: Optional[date] = Query(None, description="End date for filtering"),
    address_book_id: Optional[int] = Query(None, description="Filter by employee (AddressBook ID)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get attendance records for employees (AddressBook-based)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.company_id == user.company_id,
        TechnicianAttendance.address_book_id.isnot(None)  # Only AddressBook-linked records
    )

    if start_date:
        query = query.filter(TechnicianAttendance.date >= start_date)
    if end_date:
        query = query.filter(TechnicianAttendance.date <= end_date)
    if address_book_id:
        query = query.filter(TechnicianAttendance.address_book_id == address_book_id)
    if status:
        query = query.filter(TechnicianAttendance.status == status)

    records = query.order_by(TechnicianAttendance.date.desc(), TechnicianAttendance.address_book_id).all()

    return [attendance_to_response(record, include_employee=True) for record in records]


@router.get("/attendance/employees/daily/{record_date}")
async def get_daily_employee_attendance(
    record_date: date,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get attendance for all employees (AddressBook) on a specific date"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get all active employees from AddressBook
    employees = db.query(AddressBook).filter(
        AddressBook.company_id == user.company_id,
        AddressBook.search_type == 'E',  # Employee type
        AddressBook.is_active == True
    ).order_by(AddressBook.alpha_name).all()

    # Get existing attendance records for the date (AddressBook-linked)
    existing_records = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.company_id == user.company_id,
        TechnicianAttendance.date == record_date,
        TechnicianAttendance.address_book_id.isnot(None)
    ).all()

    # Create a map of address_book_id -> attendance record
    attendance_map = {record.address_book_id: record for record in existing_records}

    # Build response with all employees
    result = []
    for emp in employees:
        if emp.id in attendance_map:
            record = attendance_map[emp.id]
            result.append(attendance_to_response(record, include_employee=True))
        else:
            # No record exists, return placeholder
            result.append({
                "id": None,
                "company_id": user.company_id,
                "technician_id": None,
                "address_book_id": emp.id,
                "date": record_date.isoformat(),
                "status": None,
                "check_in": None,
                "check_out": None,
                "break_duration_minutes": 0,
                "hours_worked": None,
                "overtime_hours": 0,
                "leave_type": None,
                "leave_approved": False,
                "leave_approved_by": None,
                "check_in_location": None,
                "check_out_location": None,
                "notes": None,
                "created_at": None,
                "updated_at": None,
                "employee": {
                    "address_book_id": emp.id,
                    "address_number": emp.address_number,
                    "name": emp.alpha_name,
                    "employee_id": emp.employee_id,
                    "specialization": emp.specialization,
                    "phone": emp.phone_primary,
                    "email": emp.email
                }
            })

    return result


@router.post("/attendance/employees/")
async def create_employee_attendance_record(
    data: EmployeeAttendanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new attendance record for an employee (AddressBook-based)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify employee exists and is an Employee type
    employee = db.query(AddressBook).filter(
        AddressBook.id == data.address_book_id,
        AddressBook.company_id == user.company_id,
        AddressBook.search_type == 'E'
    ).first()

    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    # Check if record already exists for this employee and date
    existing = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.address_book_id == data.address_book_id,
        TechnicianAttendance.date == data.date,
        TechnicianAttendance.company_id == user.company_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attendance record already exists for {employee.alpha_name} on {data.date}"
        )

    try:
        # Calculate hours worked if check-in/check-out provided
        hours_worked = data.hours_worked
        if not hours_worked and data.check_in and data.check_out:
            hours_worked = calculate_hours_worked(data.check_in, data.check_out, data.break_duration_minutes or 0)

        record = TechnicianAttendance(
            company_id=user.company_id,
            address_book_id=data.address_book_id,
            date=data.date,
            status=data.status,
            check_in=data.check_in,
            check_out=data.check_out,
            break_duration_minutes=data.break_duration_minutes or 0,
            hours_worked=hours_worked,
            overtime_hours=data.overtime_hours or 0,
            leave_type=data.leave_type,
            leave_approved=data.leave_approved or False,
            check_in_location=data.check_in_location,
            check_out_location=data.check_out_location,
            notes=data.notes,
            created_by=user.id
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        logger.info(f"Attendance record created for employee {employee.alpha_name} on {data.date} by {user.email}")
        return attendance_to_response(record, include_employee=True)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating attendance record: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating attendance record: {str(e)}")


@router.post("/attendance/employees/bulk")
async def create_bulk_employee_attendance(
    data: BulkEmployeeAttendanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create attendance records for multiple employees at once (AddressBook-based)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    created = []
    errors = []

    for record_data in data.records:
        address_book_id = record_data.get("address_book_id")

        # Verify employee exists
        employee = db.query(AddressBook).filter(
            AddressBook.id == address_book_id,
            AddressBook.company_id == user.company_id,
            AddressBook.search_type == 'E'
        ).first()

        if not employee:
            errors.append({"address_book_id": address_book_id, "error": "Employee not found"})
            continue

        # Check if record already exists
        existing = db.query(TechnicianAttendance).filter(
            TechnicianAttendance.address_book_id == address_book_id,
            TechnicianAttendance.date == data.date,
            TechnicianAttendance.company_id == user.company_id
        ).first()

        if existing:
            # Update existing record
            existing.status = record_data.get("status", existing.status)
            existing.notes = record_data.get("notes", existing.notes)
            existing.check_in = record_data.get("check_in", existing.check_in)
            existing.check_out = record_data.get("check_out", existing.check_out)
            existing.leave_type = record_data.get("leave_type", existing.leave_type)
            existing.updated_by = user.id
            created.append(attendance_to_response(existing, include_employee=True))
        else:
            # Create new record
            try:
                record = TechnicianAttendance(
                    company_id=user.company_id,
                    address_book_id=address_book_id,
                    date=data.date,
                    status=record_data.get("status", "present"),
                    check_in=record_data.get("check_in"),
                    check_out=record_data.get("check_out"),
                    break_duration_minutes=record_data.get("break_duration_minutes", 0),
                    hours_worked=record_data.get("hours_worked"),
                    overtime_hours=record_data.get("overtime_hours", 0),
                    leave_type=record_data.get("leave_type"),
                    notes=record_data.get("notes"),
                    created_by=user.id
                )
                db.add(record)
                db.flush()
                created.append(attendance_to_response(record, include_employee=True))
            except Exception as e:
                errors.append({"address_book_id": address_book_id, "error": str(e)})

    db.commit()

    logger.info(f"Bulk attendance created: {len(created)} records by {user.email}")
    return {
        "date": data.date.isoformat(),
        "created": len(created),
        "errors": len(errors),
        "records": created,
        "error_details": errors if errors else None
    }


@router.get("/attendance/employees/{address_book_id}/monthly")
async def get_employee_monthly_attendance(
    address_book_id: int,
    year: int = Query(..., description="Year"),
    month: int = Query(..., description="Month (1-12)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get monthly attendance for a specific employee (AddressBook-based)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify employee exists
    employee = db.query(AddressBook).filter(
        AddressBook.id == address_book_id,
        AddressBook.company_id == user.company_id,
        AddressBook.search_type == 'E'
    ).first()

    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    # Calculate date range for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    records = db.query(TechnicianAttendance).filter(
        TechnicianAttendance.address_book_id == address_book_id,
        TechnicianAttendance.company_id == user.company_id,
        TechnicianAttendance.date >= start_date,
        TechnicianAttendance.date <= end_date
    ).order_by(TechnicianAttendance.date).all()

    # Build calendar view
    calendar = {}
    current = start_date
    while current <= end_date:
        calendar[current.isoformat()] = None
        current += timedelta(days=1)

    # Fill in attendance data
    for record in records:
        calendar[record.date.isoformat()] = attendance_to_response(record)

    # Summary stats
    summary = {
        "present": sum(1 for r in records if r.status == "present"),
        "absent": sum(1 for r in records if r.status == "absent"),
        "late": sum(1 for r in records if r.status == "late"),
        "half_day": sum(1 for r in records if r.status == "half_day"),
        "on_leave": sum(1 for r in records if r.status == "on_leave"),
        "holiday": sum(1 for r in records if r.status == "holiday"),
        "total_hours": sum(float(r.hours_worked or 0) for r in records),
        "total_overtime": sum(float(r.overtime_hours or 0) for r in records),
        "working_days": len([r for r in records if r.status in ["present", "late", "half_day"]])
    }

    return {
        "employee": {
            "address_book_id": employee.id,
            "address_number": employee.address_number,
            "name": employee.alpha_name,
            "employee_id": employee.employee_id
        },
        "year": year,
        "month": month,
        "calendar": calendar,
        "summary": summary
    }
