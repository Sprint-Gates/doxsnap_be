"""
Calendar & Scheduling API endpoints for work order visit scheduling
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date, time, timedelta
import json
import logging

from app.database import get_db
from app.models import (
    User, WorkOrder, CalendarSlot, WorkOrderSlotAssignment, CalendarTemplate,
    Technician, Site, HandHeldDevice
)
from app.api.auth import verify_token
from jose import jwt
from app.config import settings

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)


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


def get_current_user_or_hhd(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """Authenticate either a User or HHD device"""
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

        technician_id = payload.get("technician_id")
        return HHDContext(device, technician_id)

    email = sub
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get authenticated user (admin portal only)"""
    token = credentials.credentials
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


# ============ Pydantic Schemas ============

class CalendarSlotCreate(BaseModel):
    slot_date: date
    start_time: str  # "09:00" format
    end_time: str    # "10:00" format
    max_capacity: Optional[int] = 1
    technician_id: Optional[int] = None  # Address book ID (employee) - named for backwards compat
    site_id: Optional[int] = None
    notes: Optional[str] = None


class CalendarSlotBulkCreate(BaseModel):
    """Create multiple slots at once"""
    slot_date: date
    start_hour: int  # 8 for 8:00 AM
    end_hour: int    # 17 for 5:00 PM
    slot_duration_minutes: Optional[int] = 60
    max_capacity: Optional[int] = 1
    technician_id: Optional[int] = None
    site_id: Optional[int] = None
    break_start_hour: Optional[int] = None  # 12 for lunch break
    break_end_hour: Optional[int] = None    # 13


class CalendarSlotUpdate(BaseModel):
    max_capacity: Optional[int] = None
    status: Optional[str] = None  # available, blocked
    notes: Optional[str] = None


class WorkOrderAssign(BaseModel):
    work_order_id: int
    notes: Optional[str] = None


class CalendarTemplateCreate(BaseModel):
    name: str
    days_of_week: List[int]  # [0,1,2,3,4] for Mon-Fri
    start_hour: Optional[int] = 8
    end_hour: Optional[int] = 17
    slot_duration_minutes: Optional[int] = 60
    break_start_hour: Optional[int] = None
    break_end_hour: Optional[int] = None
    default_capacity: Optional[int] = 1
    technician_id: Optional[int] = None


class CalendarTemplateUpdate(BaseModel):
    name: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None
    slot_duration_minutes: Optional[int] = None
    break_start_hour: Optional[int] = None
    break_end_hour: Optional[int] = None
    default_capacity: Optional[int] = None
    technician_id: Optional[int] = None
    is_active: Optional[bool] = None


class GenerateSlotsRequest(BaseModel):
    template_id: int
    start_date: date
    end_date: date
    site_id: Optional[int] = None


# ============ Helper Functions ============

def time_str_to_time(time_str: str) -> time:
    """Convert "HH:MM" string to time object"""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]))


def slot_to_response(slot: CalendarSlot, include_assignments: bool = False) -> dict:
    """Convert CalendarSlot model to response dict"""
    response = {
        "id": slot.id,
        "slot_date": slot.slot_date.isoformat(),
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "max_capacity": slot.max_capacity,
        "current_bookings": slot.current_bookings,
        "status": slot.status,
        "notes": slot.notes,
        "is_active": slot.is_active,
        "created_at": slot.created_at.isoformat() if slot.created_at else None,
    }

    if slot.technician:
        response["technician"] = {
            "id": slot.technician.id,
            "name": slot.technician.name,
            "specialization": slot.technician.specialization
        }
    else:
        response["technician"] = None

    if slot.site:
        response["site"] = {
            "id": slot.site.id,
            "name": slot.site.name,
            "code": slot.site.code
        }
    else:
        response["site"] = None

    if include_assignments and slot.assignments:
        response["assignments"] = []
        for assignment in slot.assignments:
            if assignment.status != "cancelled":
                wo = assignment.work_order
                response["assignments"].append({
                    "assignment_id": assignment.id,
                    "work_order_id": wo.id,
                    "wo_number": wo.wo_number,
                    "title": wo.title,
                    "status": wo.status,
                    "priority": wo.priority,
                    "assignment_status": assignment.status
                })

    return response


def update_slot_status(slot: CalendarSlot):
    """Update slot status based on bookings"""
    active_assignments = [a for a in slot.assignments if a.status != "cancelled"]
    slot.current_bookings = len(active_assignments)

    if slot.status != "blocked":
        if slot.current_bookings >= slot.max_capacity:
            slot.status = "fully_booked"
        else:
            slot.status = "available"


# ============ Calendar Slot Endpoints ============

@router.get("/slots")
async def list_calendar_slots(
    start_date: Optional[date] = Query(None, description="Filter by start date"),
    end_date: Optional[date] = Query(None, description="Filter by end date"),
    technician_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="available, fully_booked, blocked"),
    include_assignments: bool = Query(False),
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """List calendar slots with optional filters"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(CalendarSlot).filter(
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.is_active == True
    )

    if start_date:
        query = query.filter(CalendarSlot.slot_date >= start_date)
    if end_date:
        query = query.filter(CalendarSlot.slot_date <= end_date)
    if technician_id:
        query = query.filter(CalendarSlot.technician_id == technician_id)
    if site_id:
        query = query.filter(CalendarSlot.site_id == site_id)
    if status:
        query = query.filter(CalendarSlot.status == status)

    if include_assignments:
        query = query.options(
            joinedload(CalendarSlot.assignments).joinedload(WorkOrderSlotAssignment.work_order),
            joinedload(CalendarSlot.technician),
            joinedload(CalendarSlot.site)
        )
    else:
        query = query.options(
            joinedload(CalendarSlot.technician),
            joinedload(CalendarSlot.site)
        )

    slots = query.order_by(CalendarSlot.slot_date, CalendarSlot.start_time).all()

    return [slot_to_response(s, include_assignments) for s in slots]


@router.get("/slots/{slot_id}")
async def get_calendar_slot(
    slot_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a single calendar slot by ID"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    slot = db.query(CalendarSlot).options(
        joinedload(CalendarSlot.assignments).joinedload(WorkOrderSlotAssignment.work_order),
        joinedload(CalendarSlot.technician),
        joinedload(CalendarSlot.site)
    ).filter(
        CalendarSlot.id == slot_id,
        CalendarSlot.company_id == auth_context.company_id
    ).first()

    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    return slot_to_response(slot, include_assignments=True)


@router.post("/slots")
async def create_calendar_slot(
    slot_data: CalendarSlotCreate,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a single calendar slot"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    start_time = time_str_to_time(slot_data.start_time)
    end_time = time_str_to_time(slot_data.end_time)

    if start_time >= end_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start time must be before end time")

    # Check for existing slot at same time
    existing = db.query(CalendarSlot).filter(
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.slot_date == slot_data.slot_date,
        CalendarSlot.start_time == start_time,
        CalendarSlot.address_book_id == slot_data.technician_id,  # technician_id is actually address_book_id
        CalendarSlot.is_active == True
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A slot already exists for this date, time, and technician"
        )

    slot = CalendarSlot(
        company_id=auth_context.company_id,
        slot_date=slot_data.slot_date,
        start_time=start_time,
        end_time=end_time,
        max_capacity=slot_data.max_capacity,
        address_book_id=slot_data.technician_id,  # Use address_book_id, not technician_id
        site_id=slot_data.site_id,
        notes=slot_data.notes,
        created_by=auth_context.id
    )

    db.add(slot)
    db.commit()
    db.refresh(slot)

    return slot_to_response(slot)


@router.post("/slots/bulk")
async def create_calendar_slots_bulk(
    bulk_data: CalendarSlotBulkCreate,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create multiple hourly slots for a day"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    if bulk_data.start_hour >= bulk_data.end_hour:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start hour must be before end hour")

    created_slots = []
    duration = bulk_data.slot_duration_minutes

    current_hour = bulk_data.start_hour
    current_minute = 0

    while current_hour < bulk_data.end_hour:
        # Skip break time
        if bulk_data.break_start_hour and bulk_data.break_end_hour:
            if bulk_data.break_start_hour <= current_hour < bulk_data.break_end_hour:
                current_hour = bulk_data.break_end_hour
                current_minute = 0
                continue

        start_t = time(current_hour, current_minute)

        # Calculate end time
        end_minute = current_minute + duration
        end_hour = current_hour + (end_minute // 60)
        end_minute = end_minute % 60

        if end_hour > bulk_data.end_hour or (end_hour == bulk_data.end_hour and end_minute > 0):
            break

        end_t = time(end_hour, end_minute)

        # Check for existing slot
        existing = db.query(CalendarSlot).filter(
            CalendarSlot.company_id == auth_context.company_id,
            CalendarSlot.slot_date == bulk_data.slot_date,
            CalendarSlot.start_time == start_t,
            CalendarSlot.address_book_id == bulk_data.technician_id,  # technician_id is actually address_book_id
            CalendarSlot.is_active == True
        ).first()

        if not existing:
            slot = CalendarSlot(
                company_id=auth_context.company_id,
                slot_date=bulk_data.slot_date,
                start_time=start_t,
                end_time=end_t,
                max_capacity=bulk_data.max_capacity,
                address_book_id=bulk_data.technician_id,  # Use address_book_id, not technician_id
                site_id=bulk_data.site_id,
                created_by=auth_context.id
            )
            db.add(slot)
            created_slots.append(slot)

        # Move to next slot
        current_minute += duration
        current_hour += current_minute // 60
        current_minute = current_minute % 60

    db.commit()

    # Refresh all slots
    for slot in created_slots:
        db.refresh(slot)

    return {
        "message": f"Created {len(created_slots)} slots",
        "slots": [slot_to_response(s) for s in created_slots]
    }


@router.put("/slots/{slot_id}")
async def update_calendar_slot(
    slot_id: int,
    update_data: CalendarSlotUpdate,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a calendar slot"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    slot = db.query(CalendarSlot).filter(
        CalendarSlot.id == slot_id,
        CalendarSlot.company_id == auth_context.company_id
    ).first()

    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    if update_data.max_capacity is not None:
        slot.max_capacity = update_data.max_capacity
    if update_data.status is not None:
        slot.status = update_data.status
    if update_data.notes is not None:
        slot.notes = update_data.notes

    update_slot_status(slot)
    db.commit()
    db.refresh(slot)

    return slot_to_response(slot)


@router.delete("/slots/{slot_id}")
async def delete_calendar_slot(
    slot_id: int,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (soft) a calendar slot"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    slot = db.query(CalendarSlot).filter(
        CalendarSlot.id == slot_id,
        CalendarSlot.company_id == auth_context.company_id
    ).first()

    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    # Check for active assignments
    active_assignments = [a for a in slot.assignments if a.status not in ["cancelled", "completed"]]
    if active_assignments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete slot with {len(active_assignments)} active assignment(s)"
        )

    slot.is_active = False
    db.commit()

    return {"message": "Slot deleted successfully"}


# ============ Work Order Assignment Endpoints ============

@router.post("/slots/{slot_id}/assign")
async def assign_work_order_to_slot(
    slot_id: int,
    assign_data: WorkOrderAssign,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign a work order to a calendar slot"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    slot = db.query(CalendarSlot).options(
        joinedload(CalendarSlot.assignments)
    ).filter(
        CalendarSlot.id == slot_id,
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.is_active == True
    ).first()

    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    if slot.status == "blocked":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slot is blocked")

    # Check capacity
    active_assignments = [a for a in slot.assignments if a.status != "cancelled"]
    if len(active_assignments) >= slot.max_capacity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slot is at full capacity")

    # Verify work order exists and belongs to company
    work_order = db.query(WorkOrder).filter(
        WorkOrder.id == assign_data.work_order_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()

    if not work_order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Check if already assigned to this slot
    existing = db.query(WorkOrderSlotAssignment).filter(
        WorkOrderSlotAssignment.work_order_id == assign_data.work_order_id,
        WorkOrderSlotAssignment.calendar_slot_id == slot_id
    ).first()

    if existing:
        if existing.status == "cancelled":
            existing.status = "scheduled"
            existing.assigned_at = datetime.now()
            existing.assigned_by = auth_context.id
            existing.notes = assign_data.notes
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Work order already assigned to this slot")
    else:
        assignment = WorkOrderSlotAssignment(
            work_order_id=assign_data.work_order_id,
            calendar_slot_id=slot_id,
            assigned_by=auth_context.id,
            notes=assign_data.notes
        )
        db.add(assignment)

    # Update work order scheduled times based on slot
    slot_datetime_start = datetime.combine(slot.slot_date, slot.start_time)
    slot_datetime_end = datetime.combine(slot.slot_date, slot.end_time)

    if not work_order.scheduled_start or slot_datetime_start < work_order.scheduled_start:
        work_order.scheduled_start = slot_datetime_start
    if not work_order.scheduled_end or slot_datetime_end > work_order.scheduled_end:
        work_order.scheduled_end = slot_datetime_end

    update_slot_status(slot)
    db.commit()
    db.refresh(slot)

    return {
        "message": "Work order assigned to slot",
        "slot": slot_to_response(slot, include_assignments=True)
    }


@router.delete("/slots/{slot_id}/assign/{work_order_id}")
async def remove_work_order_from_slot(
    slot_id: int,
    work_order_id: int,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a work order from a calendar slot"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    slot = db.query(CalendarSlot).filter(
        CalendarSlot.id == slot_id,
        CalendarSlot.company_id == auth_context.company_id
    ).first()

    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slot not found")

    assignment = db.query(WorkOrderSlotAssignment).filter(
        WorkOrderSlotAssignment.calendar_slot_id == slot_id,
        WorkOrderSlotAssignment.work_order_id == work_order_id
    ).first()

    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    assignment.status = "cancelled"
    update_slot_status(slot)
    db.commit()

    return {"message": "Work order removed from slot"}


@router.get("/work-order/{work_order_id}/slots")
async def get_work_order_slots(
    work_order_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all slots assigned to a work order"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    work_order = db.query(WorkOrder).filter(
        WorkOrder.id == work_order_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()

    if not work_order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    assignments = db.query(WorkOrderSlotAssignment).options(
        joinedload(WorkOrderSlotAssignment.calendar_slot).joinedload(CalendarSlot.technician),
        joinedload(WorkOrderSlotAssignment.calendar_slot).joinedload(CalendarSlot.site)
    ).filter(
        WorkOrderSlotAssignment.work_order_id == work_order_id,
        WorkOrderSlotAssignment.status != "cancelled"
    ).all()

    return [{
        "assignment_id": a.id,
        "status": a.status,
        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        "slot": slot_to_response(a.calendar_slot)
    } for a in assignments]


# ============ Calendar View Endpoints ============

@router.get("/week")
async def get_week_view(
    week_start: Optional[date] = Query(None, description="Start of week (defaults to current week Monday)"),
    technician_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get week view with all slots, assignments, and unassigned work orders"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Calculate week range
    if not week_start:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday

    week_end = week_start + timedelta(days=6)

    query = db.query(CalendarSlot).options(
        joinedload(CalendarSlot.assignments).joinedload(WorkOrderSlotAssignment.work_order),
        joinedload(CalendarSlot.technician),
        joinedload(CalendarSlot.site)
    ).filter(
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.slot_date >= week_start,
        CalendarSlot.slot_date <= week_end,
        CalendarSlot.is_active == True
    )

    if technician_id:
        query = query.filter(CalendarSlot.technician_id == technician_id)
    if site_id:
        query = query.filter(CalendarSlot.site_id == site_id)

    slots = query.order_by(CalendarSlot.slot_date, CalendarSlot.start_time).all()

    # Group by day
    slots_by_day = {}
    current_date = week_start
    while current_date <= week_end:
        slots_by_day[current_date.isoformat()] = []
        current_date += timedelta(days=1)

    for slot in slots:
        day_key = slot.slot_date.isoformat()
        if day_key in slots_by_day:
            slots_by_day[day_key].append(slot_to_response(slot, include_assignments=True))

    # Also fetch work orders with scheduled_start but no slot assignment
    # These are "unassigned" work orders that should still appear on the calendar
    week_start_dt = datetime.combine(week_start, time.min)
    week_end_dt = datetime.combine(week_end, time.max)

    # Get IDs of work orders that already have slot assignments
    assigned_wo_ids = db.query(WorkOrderSlotAssignment.work_order_id).filter(
        WorkOrderSlotAssignment.status != "cancelled"
    ).subquery()

    unassigned_wos = db.query(WorkOrder).options(
        joinedload(WorkOrder.site)
    ).filter(
        WorkOrder.company_id == auth_context.company_id,
        WorkOrder.scheduled_start >= week_start_dt,
        WorkOrder.scheduled_start <= week_end_dt,
        WorkOrder.status.notin_(["completed", "cancelled"]),
        ~WorkOrder.id.in_(assigned_wo_ids)
    )

    if site_id:
        unassigned_wos = unassigned_wos.filter(WorkOrder.site_id == site_id)

    unassigned_work_orders = unassigned_wos.all()

    # Group unassigned WOs by day
    unassigned_by_day = {}
    for wo in unassigned_work_orders:
        if wo.scheduled_start:
            day_key = wo.scheduled_start.date().isoformat()
            if day_key not in unassigned_by_day:
                unassigned_by_day[day_key] = []
            unassigned_by_day[day_key].append({
                "id": wo.id,
                "wo_number": wo.wo_number,
                "title": wo.title,
                "status": wo.status,
                "priority": wo.priority,
                "site_id": wo.site_id,
                "site_name": wo.site.name if wo.site else None,
                "scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
                "scheduled_end": wo.scheduled_end.isoformat() if wo.scheduled_end else None,
                "is_unassigned": True
            })

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "slots_by_day": slots_by_day,
        "unassigned_work_orders": unassigned_by_day
    }


@router.get("/month")
async def get_month_view(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    technician_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get month overview with slot counts per day"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    query = db.query(CalendarSlot).filter(
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.slot_date >= month_start,
        CalendarSlot.slot_date <= month_end,
        CalendarSlot.is_active == True
    )

    if technician_id:
        query = query.filter(CalendarSlot.technician_id == technician_id)
    if site_id:
        query = query.filter(CalendarSlot.site_id == site_id)

    slots = query.all()

    # Group by day with counts
    days = {}
    for slot in slots:
        day_key = slot.slot_date.isoformat()
        if day_key not in days:
            days[day_key] = {
                "total_slots": 0,
                "available_slots": 0,
                "booked_slots": 0,
                "blocked_slots": 0
            }

        days[day_key]["total_slots"] += 1
        if slot.status == "available":
            days[day_key]["available_slots"] += 1
        elif slot.status == "fully_booked":
            days[day_key]["booked_slots"] += 1
        elif slot.status == "blocked":
            days[day_key]["blocked_slots"] += 1

    return {
        "year": year,
        "month": month,
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "days": days
    }


@router.get("/day/{day_date}")
async def get_day_view(
    day_date: date,
    technician_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get detailed day view with hourly breakdown"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(CalendarSlot).options(
        joinedload(CalendarSlot.assignments).joinedload(WorkOrderSlotAssignment.work_order),
        joinedload(CalendarSlot.technician),
        joinedload(CalendarSlot.site)
    ).filter(
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.slot_date == day_date,
        CalendarSlot.is_active == True
    )

    if technician_id:
        query = query.filter(CalendarSlot.technician_id == technician_id)
    if site_id:
        query = query.filter(CalendarSlot.site_id == site_id)

    slots = query.order_by(CalendarSlot.start_time).all()

    return {
        "date": day_date.isoformat(),
        "day_name": day_date.strftime("%A"),
        "slots": [slot_to_response(s, include_assignments=True) for s in slots]
    }


@router.get("/technician/{technician_id}")
async def get_technician_schedule(
    technician_id: int,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a technician's schedule"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == auth_context.company_id
    ).first()

    if not technician:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technician not found")

    # Default to current week if no dates provided
    if not start_date:
        today = date.today()
        start_date = today - timedelta(days=today.weekday())
    if not end_date:
        end_date = start_date + timedelta(days=6)

    slots = db.query(CalendarSlot).options(
        joinedload(CalendarSlot.assignments).joinedload(WorkOrderSlotAssignment.work_order),
        joinedload(CalendarSlot.site)
    ).filter(
        CalendarSlot.company_id == auth_context.company_id,
        CalendarSlot.technician_id == technician_id,
        CalendarSlot.slot_date >= start_date,
        CalendarSlot.slot_date <= end_date,
        CalendarSlot.is_active == True
    ).order_by(CalendarSlot.slot_date, CalendarSlot.start_time).all()

    return {
        "technician": {
            "id": technician.id,
            "name": technician.name,
            "specialization": technician.specialization
        },
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "slots": [slot_to_response(s, include_assignments=True) for s in slots]
    }


# ============ Template Endpoints ============

@router.get("/templates")
async def list_templates(
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List calendar templates"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    templates = db.query(CalendarTemplate).options(
        joinedload(CalendarTemplate.technician)
    ).filter(
        CalendarTemplate.company_id == auth_context.company_id,
        CalendarTemplate.is_active == True
    ).all()

    return [{
        "id": t.id,
        "name": t.name,
        "days_of_week": json.loads(t.days_of_week),
        "start_hour": t.start_hour,
        "end_hour": t.end_hour,
        "slot_duration_minutes": t.slot_duration_minutes,
        "break_start_hour": t.break_start_hour,
        "break_end_hour": t.break_end_hour,
        "default_capacity": t.default_capacity,
        "technician": {
            "id": t.technician.id,
            "name": t.technician.name
        } if t.technician else None,
        "created_at": t.created_at.isoformat() if t.created_at else None
    } for t in templates]


@router.post("/templates")
async def create_template(
    template_data: CalendarTemplateCreate,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a calendar template"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    if template_data.start_hour >= template_data.end_hour:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start hour must be before end hour")

    for day in template_data.days_of_week:
        if day < 0 or day > 6:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Days of week must be 0-6")

    template = CalendarTemplate(
        company_id=auth_context.company_id,
        name=template_data.name,
        days_of_week=json.dumps(template_data.days_of_week),
        start_hour=template_data.start_hour,
        end_hour=template_data.end_hour,
        slot_duration_minutes=template_data.slot_duration_minutes,
        break_start_hour=template_data.break_start_hour,
        break_end_hour=template_data.break_end_hour,
        default_capacity=template_data.default_capacity,
        technician_id=template_data.technician_id
    )

    db.add(template)
    db.commit()
    db.refresh(template)

    return {
        "id": template.id,
        "name": template.name,
        "message": "Template created successfully"
    }


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    update_data: CalendarTemplateUpdate,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a calendar template"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    template = db.query(CalendarTemplate).filter(
        CalendarTemplate.id == template_id,
        CalendarTemplate.company_id == auth_context.company_id
    ).first()

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    if update_data.name is not None:
        template.name = update_data.name
    if update_data.days_of_week is not None:
        template.days_of_week = json.dumps(update_data.days_of_week)
    if update_data.start_hour is not None:
        template.start_hour = update_data.start_hour
    if update_data.end_hour is not None:
        template.end_hour = update_data.end_hour
    if update_data.slot_duration_minutes is not None:
        template.slot_duration_minutes = update_data.slot_duration_minutes
    if update_data.break_start_hour is not None:
        template.break_start_hour = update_data.break_start_hour
    if update_data.break_end_hour is not None:
        template.break_end_hour = update_data.break_end_hour
    if update_data.default_capacity is not None:
        template.default_capacity = update_data.default_capacity
    if update_data.technician_id is not None:
        template.technician_id = update_data.technician_id
    if update_data.is_active is not None:
        template.is_active = update_data.is_active

    db.commit()
    db.refresh(template)

    return {"message": "Template updated successfully"}


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a calendar template"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    template = db.query(CalendarTemplate).filter(
        CalendarTemplate.id == template_id,
        CalendarTemplate.company_id == auth_context.company_id
    ).first()

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    template.is_active = False
    db.commit()

    return {"message": "Template deleted successfully"}


@router.post("/slots/generate")
async def generate_slots_from_template(
    request: GenerateSlotsRequest,
    auth_context = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate slots for a date range using a template"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    template = db.query(CalendarTemplate).filter(
        CalendarTemplate.id == request.template_id,
        CalendarTemplate.company_id == auth_context.company_id,
        CalendarTemplate.is_active == True
    ).first()

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    if request.start_date > request.end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Start date must be before end date")

    days_of_week = json.loads(template.days_of_week)
    created_count = 0
    skipped_count = 0

    current_date = request.start_date
    while current_date <= request.end_date:
        # Check if this day is in the template
        if current_date.weekday() in days_of_week:
            # Generate slots for this day
            current_hour = template.start_hour
            current_minute = 0
            duration = template.slot_duration_minutes

            while current_hour < template.end_hour:
                # Skip break time
                if template.break_start_hour and template.break_end_hour:
                    if template.break_start_hour <= current_hour < template.break_end_hour:
                        current_hour = template.break_end_hour
                        current_minute = 0
                        continue

                start_t = time(current_hour, current_minute)

                # Calculate end time
                end_minute = current_minute + duration
                end_hour = current_hour + (end_minute // 60)
                end_minute = end_minute % 60

                if end_hour > template.end_hour or (end_hour == template.end_hour and end_minute > 0):
                    break

                end_t = time(end_hour, end_minute)

                # Check for existing slot (template technician_id is legacy, don't use it)
                existing = db.query(CalendarSlot).filter(
                    CalendarSlot.company_id == auth_context.company_id,
                    CalendarSlot.slot_date == current_date,
                    CalendarSlot.start_time == start_t,
                    CalendarSlot.site_id == request.site_id,
                    CalendarSlot.is_active == True
                ).first()

                if not existing:
                    slot = CalendarSlot(
                        company_id=auth_context.company_id,
                        slot_date=current_date,
                        start_time=start_t,
                        end_time=end_t,
                        max_capacity=template.default_capacity,
                        # Don't use technician_id from template - it's legacy
                        site_id=request.site_id,
                        created_by=auth_context.id
                    )
                    db.add(slot)
                    created_count += 1
                else:
                    skipped_count += 1

                # Move to next slot
                current_minute += duration
                current_hour += current_minute // 60
                current_minute = current_minute % 60

        current_date += timedelta(days=1)

    db.commit()

    return {
        "message": f"Generated {created_count} slots, skipped {skipped_count} existing",
        "created": created_count,
        "skipped": skipped_count
    }
