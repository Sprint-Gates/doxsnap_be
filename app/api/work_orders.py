"""
Work Orders API endpoints for maintenance management
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import Response, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from pydantic import BaseModel
from typing import Optional, List, Union
from datetime import datetime, date
from decimal import Decimal
import logging
import uuid
import os
import shutil

from app.database import get_db
from app.models import (
    User, WorkOrder, WorkOrderTimeEntry, WorkOrderChecklistItem, WorkOrderSnapshot,
    WorkOrderCompletion, Technician, Equipment, SubEquipment,
    Branch, Floor, Room, Project, work_order_technicians, work_order_technicians_ab,
    HandHeldDevice, ItemMaster, ItemStock, ItemLedger, Account, AddressBook
)
from app.services.journal_posting import JournalPostingService
from app.api.auth import verify_token
from app.utils.security import verify_token as verify_token_raw
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
        self.id = technician_id  # For created_by fields
        self.email = f"hhd:{device.device_code}"
        self.name = device.device_name
        self.role = "technician"  # HHD has technician-level access


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
    """
    Authenticate either a User (admin portal) or HHD device (mobile app).
    Returns User object for admin tokens, or HHDContext for mobile tokens.
    """
    token = credentials.credentials
    payload = verify_token_payload(token)

    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    sub = payload.get("sub")
    token_type = payload.get("type")

    # Check if this is an HHD token
    if token_type == "hhd" or (sub and sub.startswith("hhd:")):
        device_id = payload.get("device_id")
        if not device_id:
            # Try to extract from sub
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

    # Regular user token
    email = sub
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


# ============ Pydantic Schemas ============

class WorkOrderCreate(BaseModel):
    title: str
    description: Optional[str] = None
    notes: Optional[str] = None
    work_order_type: str  # corrective, preventive, operations
    priority: Optional[str] = "medium"
    equipment_id: Optional[int] = None
    sub_equipment_id: Optional[int] = None
    branch_id: Optional[int] = None
    project_id: Optional[int] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    is_billable: Optional[bool] = False
    labor_markup_percent: Optional[float] = 0
    parts_markup_percent: Optional[float] = 0
    technician_ids: Optional[List[int]] = []  # Legacy - use employee_ids instead
    employee_ids: Optional[List[int]] = []  # AddressBook IDs for employees
    assigned_hhd_id: Optional[int] = None  # Direct HHD assignment


class WorkOrderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    work_order_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    equipment_id: Optional[int] = None
    sub_equipment_id: Optional[int] = None
    branch_id: Optional[int] = None
    floor_id: Optional[int] = None
    room_id: Optional[int] = None
    project_id: Optional[int] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    is_billable: Optional[bool] = None
    billing_status: Optional[str] = None
    labor_markup_percent: Optional[float] = None
    parts_markup_percent: Optional[float] = None
    completion_notes: Optional[str] = None
    requires_follow_up: Optional[bool] = None
    follow_up_notes: Optional[str] = None
    assigned_hhd_id: Optional[int] = None  # Direct HHD assignment


class WorkOrderItemIssue(BaseModel):
    """Issue item from HHD stock to work order"""
    item_id: int
    hhd_id: int  # Source HHD
    quantity: float
    notes: Optional[str] = None


class TimeEntryCreate(BaseModel):
    technician_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    break_minutes: Optional[int] = 0
    is_overtime: Optional[bool] = False
    work_description: Optional[str] = None
    notes: Optional[str] = None


class TimeEntryUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    break_minutes: Optional[int] = None
    is_overtime: Optional[bool] = None
    work_description: Optional[str] = None
    notes: Optional[str] = None


# ============ Dependencies ============

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin_or_accounting(user: User = Depends(get_current_user)):
    if user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or accounting access required")
    return user


# ============ Helper Functions ============

def decimal_to_float(val):
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return val


def generate_wo_number(db: Session, company_id: int) -> str:
    """Generate unique work order number"""
    year = datetime.now().year
    prefix = f"WO-{year}-"

    # Get the last WO number for this company this year
    last_wo = db.query(WorkOrder).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.wo_number.like(f"{prefix}%")
    ).order_by(WorkOrder.id.desc()).first()

    if last_wo:
        try:
            last_num = int(last_wo.wo_number.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{new_num:05d}"


def calculate_labor_cost(db: Session, work_order: WorkOrder) -> dict:
    """Calculate labor cost based on time entries and technician rates"""
    total_hours = 0
    total_overtime_hours = 0
    total_cost = 0

    for entry in work_order.time_entries:
        hours = float(entry.hours_worked or 0)
        rate = float(entry.hourly_rate or 0)
        overtime_rate = float(entry.overtime_rate or rate * 1.5)

        if entry.is_overtime:
            total_overtime_hours += hours
            total_cost += hours * overtime_rate
        else:
            total_hours += hours
            total_cost += hours * rate

    return {
        "total_hours": total_hours,
        "total_overtime_hours": total_overtime_hours,
        "total_cost": round(total_cost, 2)
    }


def calculate_parts_cost(work_order: WorkOrder, db: Session = None) -> dict:
    """Calculate parts cost from issued items in item ledger"""
    issued_items_cost = 0

    # Issued items from item ledger (if db session provided)
    if db:
        # Get net issued items cost (ISSUE_WORK_ORDER - RETURN_WORK_ORDER)
        issued_items = db.query(ItemLedger).filter(
            ItemLedger.work_order_id == work_order.id,
            ItemLedger.transaction_type.in_(["ISSUE_WORK_ORDER", "RETURN_WORK_ORDER"])
        ).all()

        for item in issued_items:
            item_cost = float(item.total_cost or 0)
            if item.transaction_type == "ISSUE_WORK_ORDER":
                issued_items_cost += abs(item_cost)
            elif item.transaction_type == "RETURN_WORK_ORDER":
                issued_items_cost -= abs(item_cost)

    total_cost = max(issued_items_cost, 0)

    return {
        "total_cost": round(total_cost, 2),
        "total_price": round(total_cost, 2),
        "issued_items_cost": round(total_cost, 2)
    }


def calculate_billable_amount(work_order: WorkOrder) -> float:
    """Calculate total billable amount with markup"""
    if not work_order.is_billable:
        return 0

    labor_cost = float(work_order.actual_labor_cost or 0)
    parts_cost = float(work_order.actual_parts_cost or 0)

    labor_markup = float(work_order.labor_markup_percent or 0) / 100
    parts_markup = float(work_order.parts_markup_percent or 0) / 100

    billable_labor = labor_cost * (1 + labor_markup)
    billable_parts = parts_cost * (1 + parts_markup)

    return round(billable_labor + billable_parts, 2)


def work_order_to_response(wo: WorkOrder, include_details: bool = False, db: Session = None) -> dict:
    """Convert WorkOrder model to response dict"""
    response = {
        "id": wo.id,
        "wo_number": wo.wo_number,
        "title": wo.title,
        "description": wo.description,
        "notes": wo.notes,
        "work_order_type": wo.work_order_type,
        "priority": wo.priority,
        "status": wo.status,
        "equipment_id": wo.equipment_id,
        "sub_equipment_id": wo.sub_equipment_id,
        "site_id": wo.site_id,
        "branch_id": wo.branch_id,
        "floor_id": wo.floor_id,
        "room_id": wo.room_id,
        "scheduled_start": wo.scheduled_start.isoformat() if wo.scheduled_start else None,
        "scheduled_end": wo.scheduled_end.isoformat() if wo.scheduled_end else None,
        "actual_start": wo.actual_start.isoformat() if wo.actual_start else None,
        "actual_end": wo.actual_end.isoformat() if wo.actual_end else None,
        "is_billable": wo.is_billable,
        "billing_status": wo.billing_status,
        "estimated_labor_cost": decimal_to_float(wo.estimated_labor_cost),
        "estimated_parts_cost": decimal_to_float(wo.estimated_parts_cost),
        "estimated_total_cost": decimal_to_float(wo.estimated_total_cost),
        "actual_labor_cost": decimal_to_float(wo.actual_labor_cost),
        "actual_parts_cost": decimal_to_float(wo.actual_parts_cost),
        "actual_total_cost": decimal_to_float(wo.actual_total_cost),
        "labor_markup_percent": decimal_to_float(wo.labor_markup_percent),
        "parts_markup_percent": decimal_to_float(wo.parts_markup_percent),
        "billable_amount": decimal_to_float(wo.billable_amount),
        "currency": wo.currency,
        "completion_notes": wo.completion_notes,
        "requires_follow_up": wo.requires_follow_up,
        "follow_up_notes": wo.follow_up_notes,
        "approved_by": wo.approved_by,
        "approved_at": wo.approved_at.isoformat() if wo.approved_at else None,
        "is_approved": wo.approved_by is not None,
        "cancelled_by": wo.cancelled_by,
        "cancelled_at": wo.cancelled_at.isoformat() if wo.cancelled_at else None,
        "cancellation_reason": wo.cancellation_reason,
        "is_cancelled": wo.status == "cancelled",
        "created_by": wo.created_by,
        "created_at": wo.created_at.isoformat() if wo.created_at else None,
        "updated_at": wo.updated_at.isoformat() if wo.updated_at else None,
    }

    # Add asset info
    if wo.equipment:
        response["equipment"] = {
            "id": wo.equipment.id,
            "name": wo.equipment.name,
            "code": wo.equipment.code,
            "category": wo.equipment.category
        }
    if wo.sub_equipment:
        response["sub_equipment"] = {
            "id": wo.sub_equipment.id,
            "name": wo.sub_equipment.name,
            "code": wo.sub_equipment.code
        }

    # Add location info
    if wo.site:
        response["site"] = {"id": wo.site.id, "name": wo.site.name}
    if wo.branch:
        response["branch"] = {"id": wo.branch.id, "name": wo.branch.name}
    if wo.floor:
        response["floor"] = {"id": wo.floor.id, "name": wo.floor.name}
    if wo.room:
        response["room"] = {"id": wo.room.id, "name": wo.room.name}

    # Add project info
    response["project_id"] = wo.project_id
    if wo.project:
        response["project"] = {
            "id": wo.project.id,
            "name": wo.project.name,
            "code": wo.project.code
        }
    else:
        response["project"] = None

    # Add HHD assignment
    response["assigned_hhd_id"] = wo.assigned_hhd_id
    if wo.assigned_hhd:
        response["assigned_hhd"] = {
            "id": wo.assigned_hhd.id,
            "device_code": wo.assigned_hhd.device_code,
            "device_name": wo.assigned_hhd.device_name,
            "assigned_technician": {
                "id": wo.assigned_hhd.assigned_technician.id,
                "name": wo.assigned_hhd.assigned_technician.name
            } if wo.assigned_hhd.assigned_technician else None
        }
    else:
        response["assigned_hhd"] = None

    # Add assigned technicians count (legacy)
    response["technicians_count"] = len(wo.assigned_technicians)
    # Add assigned employees count (AddressBook-based)
    response["employees_count"] = len(wo.assigned_employees) if hasattr(wo, 'assigned_employees') else 0
    response["time_entries_count"] = len(wo.time_entries)
    response["checklist_items_count"] = len(wo.checklist_items)
    response["checklist_completed_count"] = sum(1 for item in wo.checklist_items if item.is_completed)

    if include_details:
        # Add full technician list (legacy)
        response["technicians"] = [
            {
                "id": t.id,
                "name": t.name,
                "employee_id": t.employee_id,
                "specialization": t.specialization
            }
            for t in wo.assigned_technicians
        ]

        # Add full employee list (AddressBook-based)
        response["employees"] = [
            {
                "address_book_id": e.id,
                "address_number": e.address_number,
                "name": e.alpha_name,
                "employee_id": e.employee_id,
                "specialization": e.specialization,
                "phone": e.phone_primary,
                "email": e.email
            }
            for e in (wo.assigned_employees if hasattr(wo, 'assigned_employees') else [])
        ]

        # Add time entries
        response["time_entries"] = [
            {
                "id": te.id,
                "technician_id": te.technician_id,
                "technician_name": te.technician.name if te.technician else None,
                "start_time": te.start_time.isoformat() if te.start_time else None,
                "end_time": te.end_time.isoformat() if te.end_time else None,
                "break_minutes": te.break_minutes,
                "hours_worked": decimal_to_float(te.hours_worked),
                "is_overtime": te.is_overtime,
                "hourly_rate": decimal_to_float(te.hourly_rate),
                "total_cost": decimal_to_float(te.total_cost),
                "work_description": te.work_description,
                "notes": te.notes
            }
            for te in wo.time_entries
        ]

        # Add checklist items (sorted by item_number)
        sorted_checklist = sorted(wo.checklist_items, key=lambda x: x.item_number)
        response["checklist_items"] = [
            {
                "id": item.id,
                "item_number": item.item_number,
                "description": item.description,
                "is_completed": item.is_completed,
                "completed_by": item.completed_by,
                "completed_by_name": item.completer.name if item.completer else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "notes": item.notes
            }
            for item in sorted_checklist
        ]

        # Add issued items (from item ledger)
        response["issued_items"] = []
        if db:
            issued_items = db.query(ItemLedger).filter(
                ItemLedger.work_order_id == wo.id,
                ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
            ).all()
            response["issued_items"] = [
                {
                    "id": item.id,
                    "item_id": item.item_id,
                    "item_code": item.item.item_number if item.item else None,
                    "item_name": item.item.description if item.item else None,
                    "quantity": item.quantity,
                    "unit_cost": decimal_to_float(item.unit_cost),
                    "total_cost": decimal_to_float(item.total_cost),
                    "notes": item.notes,
                    "created_at": item.created_at.isoformat() if item.created_at else None
                }
                for item in issued_items
            ]

    return response


# ============ Work Order Endpoints ============

@router.get("/work-orders/")
async def get_work_orders(
    status: Optional[str] = Query(None, description="Filter by status"),
    work_order_type: Optional[str] = Query(None, description="Filter by type"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    branch_id: Optional[int] = Query(None, description="Filter by branch"),
    equipment_id: Optional[int] = Query(None, description="Filter by equipment"),
    technician_id: Optional[int] = Query(None, description="Filter by assigned technician"),
    hhd_id: Optional[int] = Query(None, description="Filter by assigned HHD"),
    is_billable: Optional[bool] = Query(None, description="Filter by billable status"),
    search: Optional[str] = Query(None, description="Search in WO number and title"),
    include_details: bool = Query(False, description="Include full details (technicians, time entries, etc.)"),
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all work orders for the company (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # For HHD authentication, force filter by assigned HHD
    if isinstance(auth_context, HHDContext):
        hhd_id = auth_context.device.id

    query = db.query(WorkOrder).filter(WorkOrder.company_id == auth_context.company_id)

    # If include_details, eagerly load relationships
    if include_details:
        query = query.options(
            joinedload(WorkOrder.equipment),
            joinedload(WorkOrder.sub_equipment),
            joinedload(WorkOrder.site),
            joinedload(WorkOrder.branch),
            joinedload(WorkOrder.floor),
            joinedload(WorkOrder.room),
            joinedload(WorkOrder.project),
            joinedload(WorkOrder.assigned_hhd).joinedload(HandHeldDevice.assigned_technician),
            joinedload(WorkOrder.assigned_technicians),
            joinedload(WorkOrder.assigned_employees),
            joinedload(WorkOrder.time_entries).joinedload(WorkOrderTimeEntry.technician),
            joinedload(WorkOrder.checklist_items)
        )

    if status:
        query = query.filter(WorkOrder.status == status)
    if work_order_type:
        query = query.filter(WorkOrder.work_order_type == work_order_type)
    if priority:
        query = query.filter(WorkOrder.priority == priority)
    if branch_id:
        query = query.filter(WorkOrder.branch_id == branch_id)
    if equipment_id:
        query = query.filter(WorkOrder.equipment_id == equipment_id)
    if is_billable is not None:
        query = query.filter(WorkOrder.is_billable == is_billable)
    if technician_id:
        query = query.join(work_order_technicians).filter(
            work_order_technicians.c.technician_id == technician_id
        )
    if hhd_id:
        query = query.filter(WorkOrder.assigned_hhd_id == hhd_id)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                WorkOrder.wo_number.ilike(search_term),
                WorkOrder.title.ilike(search_term)
            )
        )

    work_orders = query.order_by(WorkOrder.created_at.desc()).all()
    return [work_order_to_response(wo, include_details=include_details) for wo in work_orders]


@router.get("/work-orders/{wo_id}")
async def get_work_order(
    wo_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a specific work order with full details (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.equipment),
        joinedload(WorkOrder.sub_equipment),
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.branch),
        joinedload(WorkOrder.floor),
        joinedload(WorkOrder.room),
        joinedload(WorkOrder.project),
        joinedload(WorkOrder.assigned_hhd).joinedload(HandHeldDevice.assigned_technician),
        joinedload(WorkOrder.assigned_technicians),
        joinedload(WorkOrder.time_entries).joinedload(WorkOrderTimeEntry.technician),
        joinedload(WorkOrder.checklist_items)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()

    # For HHD authentication, verify the work order is assigned to this HHD
    if isinstance(auth_context, HHDContext) and wo:
        if wo.assigned_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work order not assigned to this device")

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    return work_order_to_response(wo, include_details=True, db=db)


@router.post("/work-orders/")
async def create_work_order(
    data: WorkOrderCreate,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Create a new work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Validate work order type
    valid_types = ["corrective", "preventive", "operations"]
    if data.work_order_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid work order type. Must be one of: {', '.join(valid_types)}"
        )

    # Get location context from equipment if provided
    branch_id = data.branch_id
    floor_id = None
    room_id = None

    if data.equipment_id:
        equipment = db.query(Equipment).filter(Equipment.id == data.equipment_id).first()
        if equipment:
            room_id = equipment.room_id
            if equipment.room:
                floor_id = equipment.room.floor_id
                if equipment.room.floor:
                    branch_id = equipment.room.floor.branch_id

    # Validate HHD if provided
    if data.assigned_hhd_id:
        hhd = db.query(HandHeldDevice).filter(
            HandHeldDevice.id == data.assigned_hhd_id,
            HandHeldDevice.company_id == user.company_id,
            HandHeldDevice.is_active == True
        ).first()
        if not hhd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid HHD selected"
            )

    # Validate scheduled dates if both provided
    if data.scheduled_start and data.scheduled_end:
        if data.scheduled_start >= data.scheduled_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled start date must be before end date"
            )

    # Get markup percentages from project if assigned, otherwise use provided values
    labor_markup = data.labor_markup_percent or 0
    parts_markup = data.parts_markup_percent or 0

    if data.project_id:
        project = db.query(Project).filter(Project.id == data.project_id).first()
        if project:
            # Use project markup if not explicitly provided in request
            if not data.labor_markup_percent and project.labor_markup_percent:
                labor_markup = float(project.labor_markup_percent)
            if not data.parts_markup_percent and project.parts_markup_percent:
                parts_markup = float(project.parts_markup_percent)

    try:
        wo = WorkOrder(
            company_id=user.company_id,
            wo_number=generate_wo_number(db, user.company_id),
            title=data.title,
            description=data.description,
            notes=data.notes,
            work_order_type=data.work_order_type,
            priority=data.priority or "medium",
            status="draft",
            equipment_id=data.equipment_id,
            sub_equipment_id=data.sub_equipment_id,
            branch_id=branch_id,
            floor_id=floor_id,
            room_id=room_id,
            project_id=data.project_id,
            assigned_hhd_id=data.assigned_hhd_id,
            scheduled_start=data.scheduled_start,
            scheduled_end=data.scheduled_end,
            is_billable=data.is_billable or False,
            labor_markup_percent=labor_markup,
            parts_markup_percent=parts_markup,
            created_by=user.id
        )

        db.add(wo)
        db.flush()

        # Assign technicians if provided
        if data.technician_ids:
            technicians = db.query(Technician).filter(
                Technician.id.in_(data.technician_ids),
                Technician.company_id == user.company_id,
                Technician.is_active == True
            ).all()

            for tech in technicians:
                # Get hourly rate from technician's salary config
                hourly_rate = None
                if tech.hourly_rate:
                    hourly_rate = tech.hourly_rate
                elif tech.base_salary and tech.working_hours_per_day and tech.working_days_per_month:
                    hours_per_month = float(tech.working_hours_per_day) * float(tech.working_days_per_month)
                    if hours_per_month > 0:
                        hourly_rate = float(tech.base_salary) / hours_per_month

                db.execute(
                    work_order_technicians.insert().values(
                        work_order_id=wo.id,
                        technician_id=tech.id,
                        hourly_rate=hourly_rate
                    )
                )

        # Assign employees (AddressBook) if provided
        if data.employee_ids:
            employees = db.query(AddressBook).filter(
                AddressBook.id.in_(data.employee_ids),
                AddressBook.company_id == user.company_id,
                AddressBook.search_type == 'E',  # Must be Employee type
                AddressBook.is_active == True
            ).all()

            for emp in employees:
                # Get hourly rate from employee's salary config
                hourly_rate = None
                if emp.hourly_rate:
                    hourly_rate = emp.hourly_rate
                elif emp.base_salary and emp.working_hours_per_day and emp.working_days_per_month:
                    hours_per_month = float(emp.working_hours_per_day) * float(emp.working_days_per_month)
                    if hours_per_month > 0:
                        hourly_rate = float(emp.base_salary) / hours_per_month

                db.execute(
                    work_order_technicians_ab.insert().values(
                        work_order_id=wo.id,
                        address_book_id=emp.id,
                        hourly_rate=hourly_rate
                    )
                )

        db.commit()
        db.refresh(wo)

        logger.info(f"Work order {wo.wo_number} created by {user.email}")
        return work_order_to_response(wo)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating work order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating work order: {str(e)}"
        )


@router.put("/work-orders/{wo_id}")
async def update_work_order(
    wo_id: int,
    data: WorkOrderUpdate,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Update a work order (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()

    # For HHD authentication, verify the work order is assigned to this HHD
    if isinstance(auth_context, HHDContext) and wo:
        if wo.assigned_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work order not assigned to this device")

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Prevent editing approved work orders
    if wo.approved_by is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit an approved work order"
        )

    # Validate HHD if being updated (admin only - HHD can't reassign)
    if data.assigned_hhd_id is not None:
        if isinstance(auth_context, HHDContext):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="HHD cannot reassign work orders")
        if data.assigned_hhd_id != 0:  # 0 means clear assignment
            hhd = db.query(HandHeldDevice).filter(
                HandHeldDevice.id == data.assigned_hhd_id,
                HandHeldDevice.company_id == auth_context.company_id,
                HandHeldDevice.is_active == True
            ).first()
            if not hhd:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid HHD selected"
                )

    # Validate scheduled dates - check both new values and existing values
    scheduled_start = data.scheduled_start if data.scheduled_start is not None else wo.scheduled_start
    scheduled_end = data.scheduled_end if data.scheduled_end is not None else wo.scheduled_end
    if scheduled_start and scheduled_end:
        if scheduled_start >= scheduled_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled start date must be before end date"
            )

    try:
        update_data = data.dict(exclude_unset=True)

        # Handle clearing HHD assignment
        if update_data.get('assigned_hhd_id') == 0:
            update_data['assigned_hhd_id'] = None

        # If project is being changed, inherit markup from new project (unless explicitly provided)
        if 'project_id' in update_data and update_data['project_id']:
            new_project = db.query(Project).filter(Project.id == update_data['project_id']).first()
            if new_project:
                # Only update markup if not explicitly provided in this update
                if 'labor_markup_percent' not in update_data and new_project.labor_markup_percent:
                    update_data['labor_markup_percent'] = float(new_project.labor_markup_percent)
                if 'parts_markup_percent' not in update_data and new_project.parts_markup_percent:
                    update_data['parts_markup_percent'] = float(new_project.parts_markup_percent)

        for field, value in update_data.items():
            if value is not None or field == 'assigned_hhd_id':
                setattr(wo, field, value)

        wo.updated_by = auth_context.id

        # Recalculate costs if status changed to completed
        if data.status == "completed":
            labor = calculate_labor_cost(db, wo)
            wo.actual_labor_cost = labor["total_cost"]

            parts = calculate_parts_cost(wo, db)
            wo.actual_parts_cost = parts["total_cost"]
            wo.actual_total_cost = labor["total_cost"] + parts["total_cost"]

            if wo.is_billable:
                wo.billable_amount = calculate_billable_amount(wo)
                if not wo.billing_status:
                    wo.billing_status = "pending"

            wo.completed_at = datetime.utcnow()

        db.commit()
        db.refresh(wo)

        # Auto-post journal entry if work order completed and accounting is set up
        if data.status == "completed" and auth_context.company_id:
            try:
                has_accounts = db.query(Account).filter(
                    Account.company_id == auth_context.company_id
                ).first()

                if has_accounts:
                    journal_service = JournalPostingService(db, auth_context.company_id, auth_context.id)
                    journal_entry = journal_service.post_work_order_completion(wo, post_immediately=True)
                    if journal_entry:
                        logger.info(f"Auto-posted journal entry {journal_entry.entry_number} for work order {wo.wo_number}")
            except Exception as e:
                logger.warning(f"Failed to auto-post journal entry for work order {wo.id}: {e}")
                # Don't fail the work order update if journal posting fails

        logger.info(f"Work order {wo.wo_number} updated by {auth_context.email}")
        return work_order_to_response(wo, include_details=True)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating work order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating work order: {str(e)}"
        )


@router.delete("/work-orders/{wo_id}")
async def delete_work_order(
    wo_id: int,
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Delete a work order (admin/accounting only)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    if wo.status not in ["draft", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete draft or cancelled work orders"
        )

    try:
        db.delete(wo)
        db.commit()
        logger.info(f"Work order {wo.wo_number} deleted by {user.email}")
        return {"success": True, "message": f"Work order {wo.wo_number} deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting work order: {str(e)}"
        )


@router.post("/work-orders/{wo_id}/approve")
async def approve_work_order(
    wo_id: int,
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Approve a work order (admin/accounting only). Once approved, it cannot be edited."""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.equipment),
        joinedload(WorkOrder.sub_equipment),
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.branch),
        joinedload(WorkOrder.floor),
        joinedload(WorkOrder.room),
        joinedload(WorkOrder.project),
        joinedload(WorkOrder.assigned_hhd).joinedload(HandHeldDevice.assigned_technician),
        joinedload(WorkOrder.assigned_technicians),
        joinedload(WorkOrder.time_entries).joinedload(WorkOrderTimeEntry.technician),
        joinedload(WorkOrder.checklist_items)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    if wo.approved_by is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Work order is already approved"
        )

    if wo.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed work orders can be approved"
        )

    # Check if all checklist items are completed
    if wo.checklist_items:
        incomplete_items = [item for item in wo.checklist_items if not item.is_completed]
        if incomplete_items:
            incomplete_count = len(incomplete_items)
            total_count = len(wo.checklist_items)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve: {incomplete_count} of {total_count} checklist items are not completed"
            )

    try:
        # Convert reserved items to permanent deductions
        # Get all issued items for this work order
        issued_items = db.query(ItemLedger).filter(
            ItemLedger.work_order_id == wo_id,
            ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
        ).all()

        returned_items = db.query(ItemLedger).filter(
            ItemLedger.work_order_id == wo_id,
            ItemLedger.transaction_type == "RETURN_WORK_ORDER"
        ).all()

        # Calculate net issued per item per HHD
        net_issued = {}  # {(item_id, hhd_id): quantity}
        for entry in issued_items:
            key = (entry.item_id, entry.from_hhd_id)
            net_issued[key] = net_issued.get(key, 0) + abs(float(entry.quantity or 0))

        for entry in returned_items:
            key = (entry.item_id, entry.to_hhd_id)
            net_issued[key] = net_issued.get(key, 0) - abs(float(entry.quantity or 0))

        # Finalize stock: move from reserved to actual deduction
        for (item_id, hhd_id), qty in net_issued.items():
            if qty > 0 and hhd_id:
                # First try direct HHD stock
                hhd_stock = db.query(ItemStock).filter(
                    ItemStock.item_id == item_id,
                    ItemStock.handheld_device_id == hhd_id
                ).first()

                # If no direct HHD stock, check if HHD has a linked warehouse
                if not hhd_stock:
                    hhd = db.query(HandHeldDevice).filter(HandHeldDevice.id == hhd_id).first()
                    if hhd and hhd.warehouse_id:
                        hhd_stock = db.query(ItemStock).filter(
                            ItemStock.item_id == item_id,
                            ItemStock.warehouse_id == hhd.warehouse_id
                        ).first()

                if hhd_stock:
                    # Release reservation and deduct from on-hand
                    current_reserved = float(hhd_stock.quantity_reserved or 0)
                    current_on_hand = float(hhd_stock.quantity_on_hand or 0)

                    hhd_stock.quantity_reserved = max(0, current_reserved - qty)
                    hhd_stock.quantity_on_hand = max(0, current_on_hand - qty)
                    hhd_stock.last_movement_date = datetime.utcnow()

        wo.approved_by = user.id
        wo.approved_at = datetime.utcnow()
        db.commit()
        db.refresh(wo)
        logger.info(f"Work order {wo.wo_number} approved by {user.email}")
        return work_order_to_response(wo, include_details=True)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error approving work order: {str(e)}"
        )


class CancelWorkOrderRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/work-orders/{wo_id}/cancel")
async def cancel_work_order(
    wo_id: int,
    request: CancelWorkOrderRequest = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a work order and reverse all stock movements.

    This handles two scenarios:
    1. Pre-approval cancellation: Items were reserved but not deducted - releases reservations
    2. Post-approval cancellation: Items were deducted - adds them back to stock

    Creates CANCEL_WORK_ORDER ledger entries for audit trail.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.equipment),
        joinedload(WorkOrder.sub_equipment),
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.branch),
        joinedload(WorkOrder.floor),
        joinedload(WorkOrder.room),
        joinedload(WorkOrder.project),
        joinedload(WorkOrder.assigned_hhd).joinedload(HandHeldDevice.assigned_technician),
        joinedload(WorkOrder.assigned_technicians),
        joinedload(WorkOrder.time_entries).joinedload(WorkOrderTimeEntry.technician),
        joinedload(WorkOrder.checklist_items)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Cannot cancel already cancelled work orders
    if wo.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Work order is already cancelled"
        )

    # Check if work order was approved (stock was deducted vs just reserved)
    was_approved = wo.approved_by is not None

    try:
        # Get all issued items for this work order
        issued_items = db.query(ItemLedger).filter(
            ItemLedger.work_order_id == wo_id,
            ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
        ).all()

        returned_items = db.query(ItemLedger).filter(
            ItemLedger.work_order_id == wo_id,
            ItemLedger.transaction_type == "RETURN_WORK_ORDER"
        ).all()

        # Calculate net issued per item per HHD (issues - returns)
        net_issued = {}  # {(item_id, hhd_id): {'quantity': qty, 'unit_cost': cost, 'unit': unit}}
        for entry in issued_items:
            key = (entry.item_id, entry.from_hhd_id)
            if key not in net_issued:
                net_issued[key] = {
                    'quantity': 0,
                    'unit_cost': float(entry.unit_cost or 0),
                    'unit': entry.unit
                }
            net_issued[key]['quantity'] += abs(float(entry.quantity or 0))

        for entry in returned_items:
            key = (entry.item_id, entry.to_hhd_id)
            if key in net_issued:
                net_issued[key]['quantity'] -= abs(float(entry.quantity or 0))

        # Reverse stock for each item
        items_reversed = 0
        for (item_id, hhd_id), data in net_issued.items():
            qty = data['quantity']
            if qty <= 0 or not hhd_id:
                continue  # Nothing to reverse

            # Find the stock record - try direct HHD first, then linked warehouse
            stock = db.query(ItemStock).filter(
                ItemStock.item_id == item_id,
                ItemStock.handheld_device_id == hhd_id
            ).first()

            # If no direct HHD stock, check linked warehouse
            if not stock:
                hhd = db.query(HandHeldDevice).filter(HandHeldDevice.id == hhd_id).first()
                if hhd and hhd.warehouse_id:
                    stock = db.query(ItemStock).filter(
                        ItemStock.item_id == item_id,
                        ItemStock.warehouse_id == hhd.warehouse_id
                    ).first()

            if stock:
                if was_approved:
                    # Post-approval: Items were deducted from quantity_on_hand
                    # Need to add them back
                    current_on_hand = float(stock.quantity_on_hand or 0)
                    stock.quantity_on_hand = current_on_hand + qty
                else:
                    # Pre-approval: Items were only reserved
                    # Need to release the reservation
                    current_reserved = float(stock.quantity_reserved or 0)
                    stock.quantity_reserved = max(0, current_reserved - qty)

                stock.last_movement_date = datetime.utcnow()

            # Get item info for ledger entry
            item = db.query(ItemMaster).filter(ItemMaster.id == item_id).first()

            # Create cancellation ledger entry for audit trail
            transaction_number = generate_ledger_transaction_number(db, user.company_id, "CAN")

            # Calculate balance after reversal
            balance_after = None
            if stock:
                on_hand = float(stock.quantity_on_hand or 0)
                reserved = float(stock.quantity_reserved or 0)
                balance_after = on_hand - reserved

            ledger_entry = ItemLedger(
                company_id=user.company_id,
                item_id=item_id,
                transaction_number=transaction_number,
                transaction_date=datetime.utcnow(),
                transaction_type="CANCEL_WORK_ORDER",
                quantity=qty,  # Positive because we're returning to stock
                unit=data['unit'] or (item.unit if item else 'pcs'),
                unit_cost=data['unit_cost'],
                total_cost=data['unit_cost'] * qty,
                to_hhd_id=hhd_id,  # Items going back to HHD
                work_order_id=wo_id,
                balance_after=balance_after,
                notes=f"Cancelled WO {wo.wo_number}" + (f" - {request.reason}" if request and request.reason else ""),
                created_by=user.id
            )
            db.add(ledger_entry)
            items_reversed += 1

        # Update work order status
        wo.status = "cancelled"
        wo.cancelled_by = user.id
        wo.cancelled_at = datetime.utcnow()
        wo.cancellation_reason = request.reason if request else None
        wo.updated_by = user.id

        db.commit()
        db.refresh(wo)

        logger.info(f"Work order {wo.wo_number} cancelled by {user.email}. {items_reversed} items reversed.")

        return {
            "success": True,
            "message": f"Work order {wo.wo_number} has been cancelled",
            "work_order": work_order_to_response(wo, include_details=True),
            "items_reversed": items_reversed,
            "was_approved": was_approved,
            "stock_action": "restored to on_hand" if was_approved else "released from reserved"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling work order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cancelling work order: {str(e)}"
        )


# ============ Technician Assignment Endpoints ============

@router.post("/work-orders/{wo_id}/technicians/{technician_id}")
async def assign_technician(
    wo_id: int,
    technician_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign a technician to a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == user.company_id,
        Technician.is_active == True
    ).first()
    if not technician:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technician not found")

    # Check if already assigned
    existing = db.execute(
        work_order_technicians.select().where(
            and_(
                work_order_technicians.c.work_order_id == wo_id,
                work_order_technicians.c.technician_id == technician_id
            )
        )
    ).first()

    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Technician already assigned")

    # Calculate hourly rate
    hourly_rate = None
    if technician.hourly_rate:
        hourly_rate = technician.hourly_rate
    elif technician.base_salary and technician.working_hours_per_day and technician.working_days_per_month:
        hours_per_month = float(technician.working_hours_per_day) * float(technician.working_days_per_month)
        if hours_per_month > 0:
            hourly_rate = float(technician.base_salary) / hours_per_month

    db.execute(
        work_order_technicians.insert().values(
            work_order_id=wo_id,
            technician_id=technician_id,
            hourly_rate=hourly_rate
        )
    )
    db.commit()

    return {"success": True, "message": f"Technician {technician.name} assigned to work order"}


@router.delete("/work-orders/{wo_id}/technicians/{technician_id}")
async def unassign_technician(
    wo_id: int,
    technician_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a technician from a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    db.execute(
        work_order_technicians.delete().where(
            and_(
                work_order_technicians.c.work_order_id == wo_id,
                work_order_technicians.c.technician_id == technician_id
            )
        )
    )
    db.commit()

    return {"success": True, "message": "Technician removed from work order"}


# ============ Employee Assignment Endpoints (AddressBook-based) ============

@router.post("/work-orders/{wo_id}/employees/{address_book_id}")
async def assign_employee(
    wo_id: int,
    address_book_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Assign an employee (AddressBook entry with search_type='E') to a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Get employee from AddressBook
    employee = db.query(AddressBook).filter(
        AddressBook.id == address_book_id,
        AddressBook.company_id == user.company_id,
        AddressBook.search_type == 'E',  # Must be Employee type
        AddressBook.is_active == True
    ).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    # Check if already assigned
    existing = db.execute(
        work_order_technicians_ab.select().where(
            and_(
                work_order_technicians_ab.c.work_order_id == wo_id,
                work_order_technicians_ab.c.address_book_id == address_book_id
            )
        )
    ).first()

    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee already assigned")

    # Calculate hourly rate from AddressBook salary fields
    hourly_rate = None
    if employee.hourly_rate:
        hourly_rate = employee.hourly_rate
    elif employee.base_salary and employee.working_hours_per_day and employee.working_days_per_month:
        hours_per_month = float(employee.working_hours_per_day) * float(employee.working_days_per_month)
        if hours_per_month > 0:
            hourly_rate = float(employee.base_salary) / hours_per_month

    db.execute(
        work_order_technicians_ab.insert().values(
            work_order_id=wo_id,
            address_book_id=address_book_id,
            hourly_rate=hourly_rate
        )
    )
    db.commit()

    return {"success": True, "message": f"Employee {employee.alpha_name} assigned to work order"}


@router.delete("/work-orders/{wo_id}/employees/{address_book_id}")
async def unassign_employee(
    wo_id: int,
    address_book_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove an employee from a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    db.execute(
        work_order_technicians_ab.delete().where(
            and_(
                work_order_technicians_ab.c.work_order_id == wo_id,
                work_order_technicians_ab.c.address_book_id == address_book_id
            )
        )
    )
    db.commit()

    return {"success": True, "message": "Employee removed from work order"}


@router.get("/work-orders/{wo_id}/employees")
async def get_work_order_employees(
    wo_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all employees assigned to a work order (AddressBook-based)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Get employees from the junction table with their details
    employees = db.query(
        AddressBook,
        work_order_technicians_ab.c.assigned_at,
        work_order_technicians_ab.c.hours_worked,
        work_order_technicians_ab.c.hourly_rate,
        work_order_technicians_ab.c.notes
    ).join(
        work_order_technicians_ab,
        AddressBook.id == work_order_technicians_ab.c.address_book_id
    ).filter(
        work_order_technicians_ab.c.work_order_id == wo_id
    ).all()

    return [
        {
            "address_book_id": emp.AddressBook.id,
            "address_number": emp.AddressBook.address_number,
            "name": emp.AddressBook.alpha_name,
            "employee_id": emp.AddressBook.employee_id,
            "specialization": emp.AddressBook.specialization,
            "phone": emp.AddressBook.phone_primary,
            "email": emp.AddressBook.email,
            "assigned_at": emp.assigned_at.isoformat() if emp.assigned_at else None,
            "hours_worked": float(emp.hours_worked) if emp.hours_worked else None,
            "hourly_rate": float(emp.hourly_rate) if emp.hourly_rate else None,
            "notes": emp.notes
        }
        for emp in employees
    ]


@router.patch("/work-orders/{wo_id}/employees/{address_book_id}")
async def update_employee_assignment(
    wo_id: int,
    address_book_id: int,
    hours_worked: Optional[float] = None,
    hourly_rate: Optional[float] = None,
    notes: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update employee assignment details (hours, rate, notes)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Build update values
    update_values = {}
    if hours_worked is not None:
        update_values["hours_worked"] = hours_worked
    if hourly_rate is not None:
        update_values["hourly_rate"] = hourly_rate
    if notes is not None:
        update_values["notes"] = notes

    if update_values:
        db.execute(
            work_order_technicians_ab.update().where(
                and_(
                    work_order_technicians_ab.c.work_order_id == wo_id,
                    work_order_technicians_ab.c.address_book_id == address_book_id
                )
            ).values(**update_values)
        )
        db.commit()

    return {"success": True, "message": "Employee assignment updated"}


# ============ Work Order Item Issue (from HHD via Item Master) ============

def generate_ledger_transaction_number(db: Session, company_id: int, prefix: str) -> str:
    """Generate unique transaction number for item ledger"""
    year = datetime.now().year
    month = datetime.now().month
    full_prefix = f"{prefix}-{year}{month:02d}-"

    last_entry = db.query(ItemLedger).filter(
        ItemLedger.company_id == company_id,
        ItemLedger.transaction_number.like(f"{full_prefix}%")
    ).order_by(ItemLedger.id.desc()).first()

    if last_entry:
        try:
            last_num = int(last_entry.transaction_number.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1

    return f"{full_prefix}{new_num:05d}"


@router.post("/work-orders/{wo_id}/issue-item")
async def issue_item_to_work_order(
    wo_id: int,
    data: WorkOrderItemIssue,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Issue an item from HHD stock to a work order (creates ledger entry) - supports both admin and HHD authentication"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get work order
    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # For HHD authentication, verify the work order is assigned to this HHD
    if isinstance(auth_context, HHDContext):
        if wo.assigned_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work order not assigned to this device")
        # Also verify the HHD issuing items is the same as the authenticated HHD
        if data.hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only issue items from your own device")

    if wo.approved_by is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot issue items to an approved work order"
        )

    # Get item from item master
    item = db.query(ItemMaster).filter(
        ItemMaster.id == data.item_id,
        ItemMaster.company_id == auth_context.company_id
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Get HHD
    hhd = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == data.hhd_id,
        HandHeldDevice.company_id == auth_context.company_id
    ).first()
    if not hhd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HHD not found")

    # Check HHD stock - available = on_hand - reserved
    # First try direct HHD stock, then check linked warehouse stock
    hhd_stock = db.query(ItemStock).filter(
        ItemStock.item_id == data.item_id,
        ItemStock.handheld_device_id == data.hhd_id
    ).first()

    # If no direct HHD stock, check if HHD has a linked warehouse
    if not hhd_stock and hhd.warehouse_id:
        hhd_stock = db.query(ItemStock).filter(
            ItemStock.item_id == data.item_id,
            ItemStock.warehouse_id == hhd.warehouse_id
        ).first()

    on_hand = float(hhd_stock.quantity_on_hand or 0) if hhd_stock else 0
    reserved = float(hhd_stock.quantity_reserved or 0) if hhd_stock else 0
    available = on_hand - reserved

    if not hhd_stock or available < data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock on HHD. Available: {available} {item.unit}"
        )

    try:
        # Reserve items on HHD (don't deduct yet - will be deducted on WO approval)
        hhd_stock.quantity_reserved = reserved + data.quantity
        hhd_stock.last_movement_date = datetime.utcnow()

        # Use weighted average cost from HHD stock, fallback to item unit_cost
        unit_cost = float(hhd_stock.average_cost or 0) if hhd_stock.average_cost else float(item.unit_cost or 0)
        unit_price = float(item.unit_price or unit_cost)

        # Create ledger entry with status pending (not yet confirmed)
        transaction_number = generate_ledger_transaction_number(db, auth_context.company_id, "ISS")

        ledger_entry = ItemLedger(
            company_id=auth_context.company_id,
            item_id=data.item_id,
            transaction_number=transaction_number,
            transaction_date=datetime.utcnow(),
            transaction_type="ISSUE_WORK_ORDER",
            quantity=-data.quantity,  # Negative for issue
            unit=item.unit,
            unit_cost=unit_cost,
            total_cost=unit_cost * data.quantity,
            from_hhd_id=data.hhd_id,
            work_order_id=wo_id,
            balance_after=on_hand - reserved - data.quantity,  # Available after this reservation
            notes=data.notes or f"Issued to WO {wo.wo_number} (pending approval)",
            created_by=auth_context.id
        )
        db.add(ledger_entry)

        db.commit()

        return {
            "success": True,
            "message": f"Issued {data.quantity} {item.unit} of {item.description} (on hold until WO approved)",
            "transaction_number": transaction_number,
            "remaining_hhd_stock": on_hand - reserved - data.quantity
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error issuing item to work order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error issuing item: {str(e)}"
        )


@router.post("/work-orders/{wo_id}/return-item")
async def return_item_from_work_order(
    wo_id: int,
    data: WorkOrderItemIssue,  # Reuse same schema
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return an item from work order back to HHD stock"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    if wo.approved_by is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot return items from an approved work order"
        )

    item = db.query(ItemMaster).filter(
        ItemMaster.id == data.item_id,
        ItemMaster.company_id == user.company_id
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    hhd = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == data.hhd_id,
        HandHeldDevice.company_id == user.company_id
    ).first()
    if not hhd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HHD not found")

    try:
        # Get HHD stock record - check direct HHD stock first, then linked warehouse
        hhd_stock = db.query(ItemStock).filter(
            ItemStock.item_id == data.item_id,
            ItemStock.handheld_device_id == data.hhd_id
        ).first()

        # If no direct HHD stock, check linked warehouse
        if not hhd_stock and hhd.warehouse_id:
            hhd_stock = db.query(ItemStock).filter(
                ItemStock.item_id == data.item_id,
                ItemStock.warehouse_id == hhd.warehouse_id
            ).first()

        if not hhd_stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No stock record found for this item on HHD"
            )

        # Get the cost from the original issue ledger entry for this work order
        original_issue = db.query(ItemLedger).filter(
            ItemLedger.item_id == data.item_id,
            ItemLedger.work_order_id == wo_id,
            ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
        ).order_by(ItemLedger.created_at.desc()).first()

        # Use the issue cost if found, otherwise use HHD average or item cost
        if original_issue and original_issue.unit_cost:
            unit_cost = float(original_issue.unit_cost)
        elif hhd_stock.average_cost:
            unit_cost = float(hhd_stock.average_cost)
        else:
            unit_cost = float(item.unit_cost or 0)

        # Release reservation (since WO not yet approved, items were reserved not deducted)
        current_reserved = float(hhd_stock.quantity_reserved or 0)
        hhd_stock.quantity_reserved = max(0, current_reserved - data.quantity)
        hhd_stock.last_movement_date = datetime.utcnow()

        on_hand = float(hhd_stock.quantity_on_hand or 0)
        available_after = on_hand - hhd_stock.quantity_reserved

        # Create ledger entry
        transaction_number = generate_ledger_transaction_number(db, user.company_id, "RET")

        ledger_entry = ItemLedger(
            company_id=user.company_id,
            item_id=data.item_id,
            transaction_number=transaction_number,
            transaction_date=datetime.utcnow(),
            transaction_type="RETURN_WORK_ORDER",
            quantity=data.quantity,  # Positive for return
            unit=item.unit,
            unit_cost=unit_cost,
            total_cost=unit_cost * data.quantity,
            to_hhd_id=data.hhd_id,
            work_order_id=wo_id,
            balance_after=available_after,
            notes=data.notes or f"Returned from WO {wo.wo_number}",
            created_by=user.id
        )
        db.add(ledger_entry)

        db.commit()

        return {
            "success": True,
            "message": f"Returned {data.quantity} {item.unit} of {item.description}",
            "transaction_number": transaction_number,
            "new_hhd_stock": available_after
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error returning item from work order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error returning item: {str(e)}"
        )


@router.get("/work-orders/{wo_id}/issued-items")
async def get_work_order_issued_items(
    wo_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all items issued to a work order from Item Ledger"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    ledger_entries = db.query(ItemLedger).options(
        joinedload(ItemLedger.item),
        joinedload(ItemLedger.from_hhd),
        joinedload(ItemLedger.to_hhd)
    ).filter(
        ItemLedger.work_order_id == wo_id
    ).order_by(ItemLedger.transaction_date).all()

    return [
        {
            "id": e.id,
            "transaction_number": e.transaction_number,
            "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
            "transaction_type": e.transaction_type,
            "item_id": e.item_id,
            "item_number": e.item.item_number if e.item else None,
            "item_description": e.item.description if e.item else None,
            "quantity": decimal_to_float(e.quantity),
            "unit": e.unit,
            "unit_cost": decimal_to_float(e.unit_cost),
            "total_cost": decimal_to_float(e.total_cost),
            "hhd_code": e.from_hhd.device_code if e.from_hhd else (e.to_hhd.device_code if e.to_hhd else None),
            "from_hhd_id": e.from_hhd_id,
            "to_hhd_id": e.to_hhd_id,
            "notes": e.notes
        }
        for e in ledger_entries
    ]


# ============ Time Entry Endpoints ============

@router.post("/work-orders/{wo_id}/time-entries")
async def add_time_entry(
    wo_id: int,
    data: TimeEntryCreate,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Add a time entry to a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    technician = db.query(Technician).filter(
        Technician.id == data.technician_id,
        Technician.company_id == user.company_id
    ).first()
    if not technician:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Technician not found")

    # Validate start time is before end time
    if data.start_time and data.end_time:
        if data.start_time >= data.end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Start time must be before end time"
            )

    try:
        # Calculate hours worked
        hours_worked = None
        if data.end_time and data.start_time:
            duration = data.end_time - data.start_time
            minutes = duration.total_seconds() / 60 - (data.break_minutes or 0)
            hours_worked = round(minutes / 60, 2)

        # Get hourly rate
        hourly_rate = None
        overtime_rate = None
        if technician.hourly_rate:
            hourly_rate = float(technician.hourly_rate)
        elif technician.base_salary and technician.working_hours_per_day and technician.working_days_per_month:
            hours_per_month = float(technician.working_hours_per_day) * float(technician.working_days_per_month)
            if hours_per_month > 0:
                hourly_rate = float(technician.base_salary) / hours_per_month

        if hourly_rate and technician.overtime_rate_multiplier:
            overtime_rate = hourly_rate * float(technician.overtime_rate_multiplier)

        # Calculate cost
        total_cost = None
        if hours_worked and hourly_rate:
            if data.is_overtime and overtime_rate:
                total_cost = hours_worked * overtime_rate
            else:
                total_cost = hours_worked * hourly_rate

        te = WorkOrderTimeEntry(
            work_order_id=wo_id,
            technician_id=data.technician_id,
            start_time=data.start_time,
            end_time=data.end_time,
            break_minutes=data.break_minutes or 0,
            hours_worked=hours_worked,
            is_overtime=data.is_overtime or False,
            hourly_rate=hourly_rate,
            overtime_rate=overtime_rate,
            total_cost=total_cost,
            work_description=data.work_description,
            notes=data.notes
        )
        db.add(te)
        db.commit()
        db.refresh(te)

        return {
            "success": True,
            "message": "Time entry added",
            "time_entry": {
                "id": te.id,
                "hours_worked": decimal_to_float(te.hours_worked),
                "total_cost": decimal_to_float(te.total_cost)
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding time entry: {str(e)}"
        )


@router.put("/work-orders/{wo_id}/time-entries/{entry_id}")
async def update_time_entry(
    wo_id: int,
    entry_id: int,
    data: TimeEntryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a time entry"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    te = db.query(WorkOrderTimeEntry).filter(
        WorkOrderTimeEntry.id == entry_id,
        WorkOrderTimeEntry.work_order_id == wo_id
    ).first()
    if not te:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(te, field, value)

        # Recalculate hours and cost
        if te.end_time and te.start_time:
            duration = te.end_time - te.start_time
            minutes = duration.total_seconds() / 60 - (te.break_minutes or 0)
            te.hours_worked = round(minutes / 60, 2)

            if te.hours_worked and te.hourly_rate:
                if te.is_overtime and te.overtime_rate:
                    te.total_cost = float(te.hours_worked) * float(te.overtime_rate)
                else:
                    te.total_cost = float(te.hours_worked) * float(te.hourly_rate)

        db.commit()
        db.refresh(te)

        return {"success": True, "message": "Time entry updated"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating time entry: {str(e)}"
        )


@router.delete("/work-orders/{wo_id}/time-entries/{entry_id}")
async def delete_time_entry(
    wo_id: int,
    entry_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a time entry"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    te = db.query(WorkOrderTimeEntry).filter(
        WorkOrderTimeEntry.id == entry_id,
        WorkOrderTimeEntry.work_order_id == wo_id
    ).first()
    if not te:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")

    try:
        db.delete(te)
        db.commit()
        return {"success": True, "message": "Time entry deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting time entry: {str(e)}"
        )


# ============ Cost Calculation Endpoint ============

@router.get("/work-orders/{wo_id}/calculate-costs")
async def calculate_work_order_costs(
    wo_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Calculate and return work order costs"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.time_entries)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    labor = calculate_labor_cost(db, wo)
    parts = calculate_parts_cost(wo, db)

    total_cost = labor["total_cost"] + parts["total_cost"]

    # Calculate billable amount
    billable_labor = 0
    billable_parts = 0
    billable_total = 0

    if wo.is_billable:
        labor_markup = float(wo.labor_markup_percent or 0) / 100
        parts_markup = float(wo.parts_markup_percent or 0) / 100

        billable_labor = labor["total_cost"] * (1 + labor_markup)
        billable_parts = parts["total_price"] * (1 + parts_markup)
        billable_total = billable_labor + billable_parts

    return {
        "labor": {
            "total_hours": labor["total_hours"],
            "overtime_hours": labor["total_overtime_hours"],
            "cost": labor["total_cost"],
            "markup_percent": decimal_to_float(wo.labor_markup_percent),
            "billable": round(billable_labor, 2)
        },
        "parts": {
            "cost": parts["total_cost"],
            "price": parts["total_price"],
            "issued_items_cost": parts.get("issued_items_cost", 0),
            "markup_percent": decimal_to_float(wo.parts_markup_percent),
            "billable": round(billable_parts, 2)
        },
        "totals": {
            "cost": round(total_cost, 2),
            "billable": round(billable_total, 2),
            "profit": round(billable_total - total_cost, 2) if wo.is_billable else 0
        },
        "currency": wo.currency
    }


# ============ Checklist Item Endpoints ============

class ChecklistItemCreate(BaseModel):
    description: str
    item_number: Optional[int] = None


class ChecklistItemUpdate(BaseModel):
    is_completed: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/work-orders/{wo_id}/checklist")
async def get_checklist_items(
    wo_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all checklist items for a work order (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # For HHD authentication, verify the work order is assigned to this HHD
    if isinstance(auth_context, HHDContext):
        if wo.assigned_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work order not assigned to this device")

    items = db.query(WorkOrderChecklistItem).filter(
        WorkOrderChecklistItem.work_order_id == wo_id
    ).order_by(WorkOrderChecklistItem.item_number).all()

    return [
        {
            "id": item.id,
            "item_number": item.item_number,
            "description": item.description,
            "is_completed": item.is_completed,
            "completed_by": item.completed_by,
            "completed_by_name": item.completer.name if item.completer else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "notes": item.notes
        }
        for item in items
    ]


@router.post("/work-orders/{wo_id}/checklist")
async def add_checklist_item(
    wo_id: int,
    data: ChecklistItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a checklist item to a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Get next item number if not provided
    item_number = data.item_number
    if item_number is None:
        max_num = db.query(func.max(WorkOrderChecklistItem.item_number)).filter(
            WorkOrderChecklistItem.work_order_id == wo_id
        ).scalar() or 0
        item_number = max_num + 1

    try:
        item = WorkOrderChecklistItem(
            work_order_id=wo_id,
            item_number=item_number,
            description=data.description,
            is_completed=False
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        return {
            "id": item.id,
            "item_number": item.item_number,
            "description": item.description,
            "is_completed": item.is_completed,
            "completed_by": None,
            "completed_by_name": None,
            "completed_at": None,
            "notes": None
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding checklist item: {str(e)}"
        )


@router.patch("/work-orders/{wo_id}/checklist/{item_id}")
async def update_checklist_item(
    wo_id: int,
    item_id: int,
    data: ChecklistItemUpdate,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Update a checklist item (toggle completion, add notes) - supports both admin and HHD authentication"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == auth_context.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # For HHD authentication, verify the work order is assigned to this HHD
    if isinstance(auth_context, HHDContext):
        if wo.assigned_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work order not assigned to this device")

    item = db.query(WorkOrderChecklistItem).filter(
        WorkOrderChecklistItem.id == item_id,
        WorkOrderChecklistItem.work_order_id == wo_id
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")

    try:
        if data.is_completed is not None:
            item.is_completed = data.is_completed
            if data.is_completed:
                item.completed_by = auth_context.id
                item.completed_at = datetime.utcnow()
            else:
                item.completed_by = None
                item.completed_at = None

        if data.notes is not None:
            item.notes = data.notes

        db.commit()
        db.refresh(item)

        return {
            "id": item.id,
            "item_number": item.item_number,
            "description": item.description,
            "is_completed": item.is_completed,
            "completed_by": item.completed_by,
            "completed_by_name": item.completer.name if item.completer else None,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "notes": item.notes
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating checklist item: {str(e)}"
        )


@router.delete("/work-orders/{wo_id}/checklist/{item_id}")
async def delete_checklist_item(
    wo_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a checklist item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    item = db.query(WorkOrderChecklistItem).filter(
        WorkOrderChecklistItem.id == item_id,
        WorkOrderChecklistItem.work_order_id == wo_id
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found")

    try:
        db.delete(item)
        db.commit()
        return {"success": True, "message": "Checklist item deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting checklist item: {str(e)}"
        )


# ============ Export and Email Endpoints ============

def get_issued_items_for_report(db: Session, wo_id: int) -> list:
    """Fetch issued items from ledger for PDF report"""
    # Get all issues
    ledger_entries = db.query(ItemLedger).options(
        joinedload(ItemLedger.item)
    ).filter(
        ItemLedger.work_order_id == wo_id,
        ItemLedger.transaction_type == "ISSUE_WORK_ORDER"
    ).all()

    # Calculate net issued quantities
    issued_items_map = {}
    for entry in ledger_entries:
        item_id = entry.item_id
        if item_id not in issued_items_map:
            issued_items_map[item_id] = {
                "item_id": item_id,
                "item_number": entry.item.item_number if entry.item else "-",
                "description": entry.item.description if entry.item else "-",
                "quantity": 0,
                "unit": entry.unit or "pcs",
                "unit_cost": decimal_to_float(entry.unit_cost) or 0,
                "total_cost": 0
            }
        issued_items_map[item_id]["quantity"] += abs(decimal_to_float(entry.quantity) or 0)
        issued_items_map[item_id]["total_cost"] += abs(decimal_to_float(entry.total_cost) or 0)

    # Subtract returns
    return_entries = db.query(ItemLedger).filter(
        ItemLedger.work_order_id == wo_id,
        ItemLedger.transaction_type == "RETURN_WORK_ORDER"
    ).all()

    for entry in return_entries:
        item_id = entry.item_id
        if item_id in issued_items_map:
            issued_items_map[item_id]["quantity"] -= abs(decimal_to_float(entry.quantity) or 0)
            issued_items_map[item_id]["total_cost"] -= abs(decimal_to_float(entry.total_cost) or 0)

    # Return items with positive quantity
    return [item for item in issued_items_map.values() if item["quantity"] > 0]


class EmailWorkOrderRequest(BaseModel):
    recipient_email: str
    message: Optional[str] = None


@router.get("/work-orders/{wo_id}/export/pdf")
async def export_work_order_pdf(
    wo_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Export a work order as PDF"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Load work order with all related data
    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.equipment),
        joinedload(WorkOrder.sub_equipment),
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.branch),
        joinedload(WorkOrder.floor),
        joinedload(WorkOrder.room),
        joinedload(WorkOrder.project),
        joinedload(WorkOrder.assigned_hhd).joinedload(HandHeldDevice.assigned_technician),
        joinedload(WorkOrder.assigned_technicians),
        joinedload(WorkOrder.time_entries).joinedload(WorkOrderTimeEntry.technician),
        joinedload(WorkOrder.checklist_items)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Convert to response dict
    wo_data = work_order_to_response(wo, include_details=True)

    # Add issued items from ledger
    wo_data["issued_items"] = get_issued_items_for_report(db, wo_id)

    # Add completion data (rating, comments, signature)
    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == wo_id
    ).first()
    if completion:
        wo_data["completion"] = {
            "rating": completion.rating,
            "comments": completion.comments,
            "signature_path": completion.signature_path,
            "signed_by_name": completion.signed_by_name,
            "signed_at": completion.signed_at.isoformat() if completion.signed_at else None
        }

    # Generate PDF
    from app.services.work_order_report import WorkOrderReportService
    report_service = WorkOrderReportService()
    pdf_data = report_service.generate_pdf(wo_data)

    # Return PDF as downloadable file
    filename = f"WorkOrder_{wo.wo_number}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.post("/work-orders/{wo_id}/email")
async def email_work_order(
    wo_id: int,
    request: EmailWorkOrderRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Email a work order report to a recipient"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Load work order with all related data
    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.equipment),
        joinedload(WorkOrder.sub_equipment),
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.branch),
        joinedload(WorkOrder.floor),
        joinedload(WorkOrder.room),
        joinedload(WorkOrder.project),
        joinedload(WorkOrder.assigned_hhd).joinedload(HandHeldDevice.assigned_technician),
        joinedload(WorkOrder.assigned_technicians),
        joinedload(WorkOrder.time_entries).joinedload(WorkOrderTimeEntry.technician),
        joinedload(WorkOrder.checklist_items)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Convert to response dict
    wo_data = work_order_to_response(wo, include_details=True)

    # Add issued items from ledger
    wo_data["issued_items"] = get_issued_items_for_report(db, wo_id)

    # Add completion data (rating, comments, signature)
    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == wo_id
    ).first()
    if completion:
        wo_data["completion"] = {
            "rating": completion.rating,
            "comments": completion.comments,
            "signature_path": completion.signature_path,
            "signed_by_name": completion.signed_by_name,
            "signed_at": completion.signed_at.isoformat() if completion.signed_at else None
        }

    # Generate PDF
    from app.services.work_order_report import WorkOrderReportService
    report_service = WorkOrderReportService()
    pdf_data = report_service.generate_pdf(wo_data)

    # Send email
    success = report_service.send_work_order_email(
        recipient_email=request.recipient_email,
        work_order=wo_data,
        pdf_data=pdf_data,
        message=request.message,
        sender_name=user.name
    )

    if success:
        return {"success": True, "message": f"Work order report sent to {request.recipient_email}"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email. Please check email configuration."
        )


# ============================================================================
# Work Order Snapshots API
# ============================================================================

SNAPSHOTS_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "work_order_snapshots")

# Ensure upload directory exists
os.makedirs(SNAPSHOTS_UPLOAD_DIR, exist_ok=True)


def snapshot_to_response(snapshot: WorkOrderSnapshot) -> dict:
    """Convert WorkOrderSnapshot to response dict"""
    return {
        "id": snapshot.id,
        "work_order_id": snapshot.work_order_id,
        "filename": snapshot.filename,
        "original_filename": snapshot.original_filename,
        "file_path": snapshot.file_path,
        "file_size": snapshot.file_size,
        "mime_type": snapshot.mime_type,
        "caption": snapshot.caption,
        "taken_by": snapshot.taken_by,
        "taken_by_name": snapshot.photographer.name if snapshot.photographer else None,
        "taken_at": snapshot.taken_at.isoformat() if snapshot.taken_at else None,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None
    }


@router.get("/{wo_id}/snapshots")
async def get_work_order_snapshots(
    wo_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all snapshots for a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify work order exists and belongs to user's company
    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    snapshots = db.query(WorkOrderSnapshot).options(
        joinedload(WorkOrderSnapshot.photographer)
    ).filter(
        WorkOrderSnapshot.work_order_id == wo_id
    ).order_by(WorkOrderSnapshot.taken_at.desc()).all()

    return [snapshot_to_response(s) for s in snapshots]


@router.post("/{wo_id}/snapshots")
async def upload_work_order_snapshot(
    wo_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a snapshot to a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify work order exists and belongs to user's company
    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    # Generate unique filename
    file_ext = os.path.splitext(file.filename)[1] or ".jpg"
    unique_filename = f"{uuid.uuid4()}{file_ext}"

    # Create company-specific subdirectory
    company_dir = os.path.join(SNAPSHOTS_UPLOAD_DIR, str(user.company_id))
    os.makedirs(company_dir, exist_ok=True)

    file_path = os.path.join(company_dir, unique_filename)

    try:
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Get file size
        file_size = os.path.getsize(file_path)

        # Create snapshot record
        snapshot = WorkOrderSnapshot(
            work_order_id=wo_id,
            company_id=user.company_id,
            filename=unique_filename,
            original_filename=file.filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            caption=caption,
            taken_by=user.id
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        return snapshot_to_response(snapshot)

    except Exception as e:
        # Clean up file if database operation fails
        if os.path.exists(file_path):
            os.remove(file_path)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload snapshot: {str(e)}"
        )


@router.get("/{wo_id}/snapshots/{snapshot_id}/image")
async def get_snapshot_image(
    wo_id: int,
    snapshot_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Get snapshot image file (requires token in query param for img src)"""
    # Verify token
    payload = verify_token_payload(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    company_id = payload.get("company_id")
    if not company_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Get snapshot
    snapshot = db.query(WorkOrderSnapshot).filter(
        WorkOrderSnapshot.id == snapshot_id,
        WorkOrderSnapshot.work_order_id == wo_id,
        WorkOrderSnapshot.company_id == company_id
    ).first()

    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    if not os.path.exists(snapshot.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found")

    return FileResponse(
        snapshot.file_path,
        media_type=snapshot.mime_type or "image/jpeg",
        filename=snapshot.original_filename
    )


@router.patch("/{wo_id}/snapshots/{snapshot_id}")
async def update_snapshot_caption(
    wo_id: int,
    snapshot_id: int,
    caption: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update snapshot caption"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    snapshot = db.query(WorkOrderSnapshot).filter(
        WorkOrderSnapshot.id == snapshot_id,
        WorkOrderSnapshot.work_order_id == wo_id,
        WorkOrderSnapshot.company_id == user.company_id
    ).first()

    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    snapshot.caption = caption
    db.commit()
    db.refresh(snapshot)

    return snapshot_to_response(snapshot)


@router.delete("/{wo_id}/snapshots/{snapshot_id}")
async def delete_work_order_snapshot(
    wo_id: int,
    snapshot_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a snapshot from a work order"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    snapshot = db.query(WorkOrderSnapshot).filter(
        WorkOrderSnapshot.id == snapshot_id,
        WorkOrderSnapshot.work_order_id == wo_id,
        WorkOrderSnapshot.company_id == user.company_id
    ).first()

    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    # Delete file
    if os.path.exists(snapshot.file_path):
        try:
            os.remove(snapshot.file_path)
        except Exception as e:
            logger.warning(f"Failed to delete snapshot file: {e}")

    # Delete record
    db.delete(snapshot)
    db.commit()

    return {"success": True, "message": "Snapshot deleted"}


# ============================================================================
# Work Order Completion (Rating, Comments, Signature) API
# ============================================================================

SIGNATURES_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "work_order_signatures")

# Ensure upload directory exists
os.makedirs(SIGNATURES_UPLOAD_DIR, exist_ok=True)


class WorkOrderCompletionCreate(BaseModel):
    """Schema for creating work order completion data"""
    rating: Optional[int] = None  # 1-5 stars
    comments: Optional[str] = None
    signed_by_name: Optional[str] = None


class WorkOrderCompletionResponse(BaseModel):
    """Schema for work order completion response"""
    id: int
    work_order_id: int
    rating: Optional[int] = None
    comments: Optional[str] = None
    signature_filename: Optional[str] = None
    signed_by_name: Optional[str] = None
    signed_at: Optional[str] = None
    created_at: Optional[str] = None


def completion_to_response(completion: WorkOrderCompletion) -> dict:
    """Convert WorkOrderCompletion to response dict"""
    return {
        "id": completion.id,
        "work_order_id": completion.work_order_id,
        "rating": completion.rating,
        "comments": completion.comments,
        "signature_filename": completion.signature_filename,
        "signed_by_name": completion.signed_by_name,
        "signed_at": completion.signed_at.isoformat() if completion.signed_at else None,
        "created_at": completion.created_at.isoformat() if completion.created_at else None,
        "updated_at": completion.updated_at.isoformat() if completion.updated_at else None
    }


@router.get("/work-orders/{wo_id}/completion")
async def get_work_order_completion(
    wo_id: int,
    user = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get work order completion data (rating, comments, signature info)"""
    company_id = user.company_id

    # Verify work order exists and belongs to company
    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == wo_id
    ).first()

    if not completion:
        return None

    return completion_to_response(completion)


@router.post("/work-orders/{wo_id}/completion")
async def create_or_update_work_order_completion(
    wo_id: int,
    data: WorkOrderCompletionCreate,
    user = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Create or update work order completion (rating and comments)"""
    company_id = user.company_id

    # Verify work order exists and belongs to company
    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Validate rating if provided
    if data.rating is not None and (data.rating < 1 or data.rating > 5):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rating must be between 1 and 5"
        )

    # Get existing completion or create new one
    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == wo_id
    ).first()

    if completion:
        # Update existing
        if data.rating is not None:
            completion.rating = data.rating
        if data.comments is not None:
            completion.comments = data.comments
        if data.signed_by_name is not None:
            completion.signed_by_name = data.signed_by_name
    else:
        # Create new
        completion = WorkOrderCompletion(
            work_order_id=wo_id,
            company_id=company_id,
            rating=data.rating,
            comments=data.comments,
            signed_by_name=data.signed_by_name,
            created_by=user.id if hasattr(user, 'id') else None
        )
        db.add(completion)

    db.commit()
    db.refresh(completion)

    return completion_to_response(completion)


@router.post("/work-orders/{wo_id}/completion/signature")
async def upload_work_order_signature(
    wo_id: int,
    file: UploadFile = File(...),
    signed_by_name: Optional[str] = Form(None),
    user = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Upload signature image for work order completion"""
    company_id = user.company_id

    # Verify work order exists and belongs to company
    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == company_id
    ).first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    # Validate file type (PNG is typical for signature pads)
    allowed_types = ["image/png", "image/jpeg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    # Generate unique filename
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".png"
    unique_filename = f"{uuid.uuid4()}{file_ext}"

    # Create company-specific subdirectory
    company_dir = os.path.join(SIGNATURES_UPLOAD_DIR, str(company_id))
    os.makedirs(company_dir, exist_ok=True)

    file_path = os.path.join(company_dir, unique_filename)

    try:
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Get or create completion record
        completion = db.query(WorkOrderCompletion).filter(
            WorkOrderCompletion.work_order_id == wo_id
        ).first()

        # Delete old signature file if exists
        if completion and completion.signature_path and os.path.exists(completion.signature_path):
            try:
                os.remove(completion.signature_path)
            except Exception as e:
                logger.warning(f"Failed to delete old signature file: {e}")

        if completion:
            # Update existing
            completion.signature_filename = unique_filename
            completion.signature_path = file_path
            completion.signed_at = datetime.utcnow()
            if signed_by_name:
                completion.signed_by_name = signed_by_name
        else:
            # Create new
            completion = WorkOrderCompletion(
                work_order_id=wo_id,
                company_id=company_id,
                signature_filename=unique_filename,
                signature_path=file_path,
                signed_by_name=signed_by_name,
                signed_at=datetime.utcnow(),
                created_by=user.id if hasattr(user, 'id') else None
            )
            db.add(completion)

        db.commit()
        db.refresh(completion)

        return completion_to_response(completion)

    except Exception as e:
        # Clean up file if database operation fails
        if os.path.exists(file_path):
            os.remove(file_path)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload signature: {str(e)}"
        )


@router.get("/work-orders/{wo_id}/completion/signature/image")
async def get_signature_image(
    wo_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Get signature image file (requires token in query param for img src)"""
    # Verify token
    payload = verify_token_payload(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Get company_id from payload (works for both user and HHD tokens)
    company_id = payload.get("company_id")
    if not company_id:
        # For regular user tokens, we need to look up the user
        sub = payload.get("sub")
        if sub and not sub.startswith("hhd:"):
            user = db.query(User).filter(User.email == sub).first()
            if user:
                company_id = user.company_id

    if not company_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Get completion with signature
    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == wo_id,
        WorkOrderCompletion.company_id == company_id
    ).first()

    if not completion or not completion.signature_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signature not found")

    if not os.path.exists(completion.signature_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signature file not found")

    return FileResponse(
        completion.signature_path,
        media_type="image/png",
        filename=completion.signature_filename
    )


@router.delete("/work-orders/{wo_id}/completion")
async def delete_work_order_completion(
    wo_id: int,
    user = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Delete work order completion data"""
    company_id = user.company_id

    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == wo_id,
        WorkOrderCompletion.company_id == company_id
    ).first()

    if not completion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Completion data not found")

    # Delete signature file if exists
    if completion.signature_path and os.path.exists(completion.signature_path):
        try:
            os.remove(completion.signature_path)
        except Exception as e:
            logger.warning(f"Failed to delete signature file: {e}")

    # Delete record
    db.delete(completion)
    db.commit()

    return {"success": True, "message": "Completion data deleted"}
