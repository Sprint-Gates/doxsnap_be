"""
PM Work Order Generation API
Generates preventive maintenance work orders based on equipment PM schedules
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from decimal import Decimal
import logging

from app.database import get_db
from app.models import (
    User, WorkOrder, Equipment, Branch, Floor, Room, Project,
    PMEquipmentClass, PMSystemCode, PMAssetType, PMChecklist, PMActivity,
    PMSchedule, Technician, work_order_technicians, HandHeldDevice,
    WorkOrderChecklistItem
)
from app.api.auth import verify_token

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)


# ============ Pydantic Schemas ============

class PMWorkOrderGenerateRequest(BaseModel):
    """Request to generate PM work orders for a branch"""
    branch_id: int
    frequency_code: str  # "1M", "3M", "6M", "1Y", etc.
    project_id: int  # Required - project to assign work orders to
    scheduled_date: Optional[datetime] = None  # When to schedule the work orders
    technician_ids: Optional[List[int]] = []  # Technicians to assign
    assigned_hhd_id: Optional[int] = None  # HHD to assign
    is_billable: Optional[bool] = False
    labor_markup_percent: Optional[float] = 0  # Default markup for labor costs
    parts_markup_percent: Optional[float] = 0  # Default markup for spare parts


class PMWorkOrderPreviewItem(BaseModel):
    """Preview of a PM work order to be generated"""
    equipment_id: int
    equipment_name: str
    equipment_code: Optional[str]
    room_name: Optional[str]
    floor_name: Optional[str]
    pm_asset_type: str
    checklist_id: int
    frequency_code: str
    frequency_name: str
    activities_count: int
    last_completed: Optional[str]
    next_due: Optional[str]
    is_overdue: bool


class PMWorkOrderGenerateResponse(BaseModel):
    """Response after generating PM work orders"""
    success: bool
    message: str
    work_orders_created: int
    work_order_numbers: List[str]


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


# ============ Helper Functions ============

def generate_wo_number(db: Session, company_id: int) -> str:
    """Generate unique work order number"""
    year = datetime.now().year
    prefix = f"WO-{year}-"

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


def get_or_create_pm_schedule(db: Session, company_id: int, equipment_id: int, checklist_id: int) -> PMSchedule:
    """Get existing PM schedule or create a new one"""
    schedule = db.query(PMSchedule).filter(
        PMSchedule.company_id == company_id,
        PMSchedule.equipment_id == equipment_id,
        PMSchedule.checklist_id == checklist_id
    ).first()

    if not schedule:
        schedule = PMSchedule(
            company_id=company_id,
            equipment_id=equipment_id,
            checklist_id=checklist_id,
            is_active=True
        )
        db.add(schedule)
        db.flush()

    return schedule


# ============ API Endpoints ============

@router.get("/pm-work-orders/frequencies")
async def get_pm_frequencies(
    branch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get available PM frequencies for a branch based on equipment with PM asset types
    Returns frequencies that have at least one equipment with checklists
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get all equipment in this branch that has pm_asset_type_id set
    equipment_with_pm = db.query(Equipment).join(Room).join(Floor).filter(
        Floor.branch_id == branch_id,
        Equipment.pm_asset_type_id.isnot(None),
        Equipment.is_active == True
    ).all()

    if not equipment_with_pm:
        return {
            "frequencies": [],
            "equipment_count": 0,
            "message": "No equipment with PM asset types found in this branch"
        }

    # Collect all unique frequencies from the checklists
    pm_asset_type_ids = [e.pm_asset_type_id for e in equipment_with_pm]

    checklists = db.query(PMChecklist).filter(
        PMChecklist.asset_type_id.in_(pm_asset_type_ids),
        PMChecklist.is_active == True
    ).distinct(PMChecklist.frequency_code).all()

    frequencies = []
    for checklist in checklists:
        # Count equipment with this frequency
        equipment_count = 0
        for equip in equipment_with_pm:
            has_checklist = db.query(PMChecklist).filter(
                PMChecklist.asset_type_id == equip.pm_asset_type_id,
                PMChecklist.frequency_code == checklist.frequency_code,
                PMChecklist.is_active == True
            ).first()
            if has_checklist:
                equipment_count += 1

        frequencies.append({
            "code": checklist.frequency_code,
            "name": checklist.frequency_name,
            "days": checklist.frequency_days,
            "equipment_count": equipment_count
        })

    # Sort by days
    frequencies.sort(key=lambda x: x["days"])

    return {
        "frequencies": frequencies,
        "equipment_count": len(equipment_with_pm),
        "branch_id": branch_id
    }


@router.get("/pm-work-orders/preview")
async def preview_pm_work_orders(
    branch_id: int,
    frequency_code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Preview PM work orders that would be generated for a branch and frequency
    Shows equipment, their PM status, and whether they are overdue
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get branch
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    # Get equipment with PM asset types in this branch
    equipment_list = db.query(Equipment).options(
        joinedload(Equipment.room).joinedload(Room.floor),
        joinedload(Equipment.pm_asset_type)
    ).join(Room).join(Floor).filter(
        Floor.branch_id == branch_id,
        Equipment.pm_asset_type_id.isnot(None),
        Equipment.is_active == True
    ).all()

    preview_items = []
    now = datetime.now()

    for equip in equipment_list:
        # Find checklist for this equipment's asset type and frequency
        checklist = db.query(PMChecklist).options(
            joinedload(PMChecklist.activities)
        ).filter(
            PMChecklist.asset_type_id == equip.pm_asset_type_id,
            PMChecklist.frequency_code == frequency_code,
            PMChecklist.is_active == True
        ).first()

        if not checklist:
            continue

        # Get or check PM schedule
        schedule = db.query(PMSchedule).filter(
            PMSchedule.equipment_id == equip.id,
            PMSchedule.checklist_id == checklist.id
        ).first()

        last_completed = None
        next_due = None
        is_overdue = False

        if schedule:
            if schedule.last_completed_date:
                last_completed = schedule.last_completed_date.isoformat()
            if schedule.next_due_date:
                next_due = schedule.next_due_date.isoformat()
                is_overdue = schedule.next_due_date < now
        else:
            # Never done - consider it overdue
            is_overdue = True

        preview_items.append({
            "equipment_id": equip.id,
            "equipment_name": equip.name,
            "equipment_code": equip.code,
            "room_name": equip.room.name if equip.room else None,
            "floor_name": equip.room.floor.name if equip.room and equip.room.floor else None,
            "pm_asset_type": equip.pm_asset_type.name if equip.pm_asset_type else None,
            "checklist_id": checklist.id,
            "frequency_code": checklist.frequency_code,
            "frequency_name": checklist.frequency_name,
            "activities_count": len(checklist.activities),
            "last_completed": last_completed,
            "next_due": next_due,
            "is_overdue": is_overdue
        })

    # Sort: overdue first, then by next_due date
    preview_items.sort(key=lambda x: (not x["is_overdue"], x["next_due"] or ""))

    return {
        "branch": {
            "id": branch.id,
            "name": branch.name
        },
        "frequency": {
            "code": frequency_code
        },
        "preview_items": preview_items,
        "total_count": len(preview_items),
        "overdue_count": sum(1 for item in preview_items if item["is_overdue"])
    }


@router.post("/pm-work-orders/generate")
async def generate_pm_work_orders(
    data: PMWorkOrderGenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate PM work orders for a branch and frequency
    Creates work orders for all equipment that has the specified frequency checklist
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Validate branch
    branch = db.query(Branch).filter(Branch.id == data.branch_id).first()
    if not branch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Branch not found")

    # Validate project
    project = db.query(Project).filter(
        Project.id == data.project_id,
        Project.branch_id == data.branch_id,
        Project.status == 'active'
    ).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or not active for this branch")

    # Get markup values from request (which should come from project defaults)
    labor_markup = Decimal(str(data.labor_markup_percent or 0))
    parts_markup = Decimal(str(data.parts_markup_percent or 0))

    # Get equipment with PM asset types
    equipment_list = db.query(Equipment).options(
        joinedload(Equipment.room).joinedload(Room.floor),
        joinedload(Equipment.pm_asset_type)
    ).join(Room).join(Floor).filter(
        Floor.branch_id == data.branch_id,
        Equipment.pm_asset_type_id.isnot(None),
        Equipment.is_active == True
    ).all()

    # Validate technicians if provided
    technicians = []
    if data.technician_ids:
        technicians = db.query(Technician).filter(
            Technician.id.in_(data.technician_ids),
            Technician.company_id == user.company_id,
            Technician.is_active == True
        ).all()

    # Validate HHD if provided
    assigned_hhd = None
    if data.assigned_hhd_id:
        assigned_hhd = db.query(HandHeldDevice).filter(
            HandHeldDevice.id == data.assigned_hhd_id,
            HandHeldDevice.company_id == user.company_id,
            HandHeldDevice.is_active == True
        ).first()
        if not assigned_hhd:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handheld device not found")

    scheduled_date = data.scheduled_date or datetime.now()
    work_orders_created = []

    try:
        for equip in equipment_list:
            # Find checklist for this frequency
            checklist = db.query(PMChecklist).options(
                joinedload(PMChecklist.activities),
                joinedload(PMChecklist.asset_type)
            ).filter(
                PMChecklist.asset_type_id == equip.pm_asset_type_id,
                PMChecklist.frequency_code == data.frequency_code,
                PMChecklist.is_active == True
            ).first()

            if not checklist:
                continue

            # Build work order title and description
            asset_type_name = checklist.asset_type.name if checklist.asset_type else "Equipment"
            wo_title = f"PM - {checklist.frequency_name} - {equip.name}"

            # Build description with clear checklist format
            location = f"{equip.room.floor.name if equip.room and equip.room.floor else 'N/A'} > {equip.room.name if equip.room else 'N/A'}"

            # Format activities as a clean checklist
            sorted_activities = sorted(checklist.activities, key=lambda a: a.sequence_order)
            activity_lines = []
            for i, act in enumerate(sorted_activities, 1):
                # Add checkbox placeholder and clean formatting
                activity_lines.append(f"☐ {i}. {act.description}")
                if act.safety_notes:
                    activity_lines.append(f"   ⚠️ Safety: {act.safety_notes}")

            wo_description = f"""PREVENTIVE MAINTENANCE CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Equipment: {equip.name}
Asset Type: {asset_type_name}
Location: {location}
Frequency: {checklist.frequency_name}

TASKS TO COMPLETE:
━━━━━━━━━━━━━━━━━━

""" + "\n\n".join(activity_lines)

            # Get location context
            room_id = equip.room_id
            floor_id = equip.room.floor_id if equip.room else None

            # Create work order
            wo = WorkOrder(
                company_id=user.company_id,
                wo_number=generate_wo_number(db, user.company_id),
                title=wo_title,
                description=wo_description,
                work_order_type="preventive",
                priority="medium",
                status="pending",
                equipment_id=equip.id,
                branch_id=data.branch_id,
                floor_id=floor_id,
                room_id=room_id,
                project_id=data.project_id,
                scheduled_start=scheduled_date,
                scheduled_end=scheduled_date + timedelta(days=1),  # Default 1-day window
                is_billable=data.is_billable or False,
                labor_markup_percent=labor_markup,
                parts_markup_percent=parts_markup,
                assigned_hhd_id=data.assigned_hhd_id,
                created_by=user.id
            )
            db.add(wo)
            db.flush()

            # Create checklist items from activities
            sorted_activities = sorted(checklist.activities, key=lambda a: a.sequence_order)
            for i, act in enumerate(sorted_activities, 1):
                checklist_item = WorkOrderChecklistItem(
                    work_order_id=wo.id,
                    item_number=i,
                    description=act.description,
                    is_completed=False,
                    notes=f"Safety: {act.safety_notes}" if act.safety_notes else None
                )
                db.add(checklist_item)

            # Assign technicians
            for tech in technicians:
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

            # Update or create PM schedule
            schedule = get_or_create_pm_schedule(db, user.company_id, equip.id, checklist.id)
            schedule.next_due_date = scheduled_date + timedelta(days=checklist.frequency_days)

            work_orders_created.append(wo.wo_number)

        db.commit()

        logger.info(f"Generated {len(work_orders_created)} PM work orders for branch {data.branch_id} by {user.email}")

        return {
            "success": True,
            "message": f"Successfully generated {len(work_orders_created)} PM work orders",
            "work_orders_created": len(work_orders_created),
            "work_order_numbers": work_orders_created,
            "frequency": data.frequency_code,
            "branch_id": data.branch_id
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error generating PM work orders: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating PM work orders: {str(e)}"
        )


@router.post("/pm-work-orders/{wo_id}/complete")
async def complete_pm_work_order(
    wo_id: int,
    completion_notes: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark a PM work order as completed and update the PM schedule
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    wo = db.query(WorkOrder).filter(
        WorkOrder.id == wo_id,
        WorkOrder.company_id == user.company_id,
        WorkOrder.work_order_type == "preventive"
    ).first()

    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PM Work order not found")

    if wo.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Work order already completed")

    try:
        # Update work order status
        wo.status = "completed"
        wo.actual_end = datetime.now()
        wo.completion_notes = completion_notes
        wo.updated_by = user.id

        # Find and update PM schedule
        if wo.equipment_id:
            equipment = db.query(Equipment).filter(Equipment.id == wo.equipment_id).first()
            if equipment and equipment.pm_asset_type_id:
                # Find matching checklist based on work order description or title
                checklists = db.query(PMChecklist).filter(
                    PMChecklist.asset_type_id == equipment.pm_asset_type_id,
                    PMChecklist.is_active == True
                ).all()

                for checklist in checklists:
                    schedule = db.query(PMSchedule).filter(
                        PMSchedule.equipment_id == wo.equipment_id,
                        PMSchedule.checklist_id == checklist.id
                    ).first()

                    if schedule:
                        schedule.last_completed_date = datetime.now()
                        schedule.last_work_order_id = wo.id
                        schedule.next_due_date = datetime.now() + timedelta(days=checklist.frequency_days)

        db.commit()

        logger.info(f"PM work order {wo.wo_number} completed by {user.email}")

        return {
            "success": True,
            "message": f"Work order {wo.wo_number} marked as completed",
            "wo_number": wo.wo_number
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error completing PM work order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error completing PM work order: {str(e)}"
        )


@router.get("/pm-work-orders/dashboard")
async def get_pm_dashboard(
    branch_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get PM dashboard statistics for the company or a specific branch
    Shows overdue, upcoming, and completed PM work orders
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    now = datetime.now()
    week_ahead = now + timedelta(days=7)
    month_ahead = now + timedelta(days=30)

    # Base query for PM work orders
    query = db.query(WorkOrder).filter(
        WorkOrder.company_id == user.company_id,
        WorkOrder.work_order_type == "preventive"
    )

    if branch_id:
        query = query.filter(WorkOrder.branch_id == branch_id)

    # Get counts by status
    pending_count = query.filter(WorkOrder.status == "pending").count()
    in_progress_count = query.filter(WorkOrder.status == "in_progress").count()
    completed_count = query.filter(WorkOrder.status == "completed").count()

    # Overdue work orders (pending or in_progress, past scheduled_end)
    overdue_count = query.filter(
        WorkOrder.status.in_(["pending", "in_progress"]),
        WorkOrder.scheduled_end < now
    ).count()

    # Due this week
    due_this_week = query.filter(
        WorkOrder.status == "pending",
        WorkOrder.scheduled_start >= now,
        WorkOrder.scheduled_start <= week_ahead
    ).count()

    # Get PM schedules that are overdue but no work order created
    schedule_query = db.query(PMSchedule).filter(
        PMSchedule.company_id == user.company_id,
        PMSchedule.is_active == True,
        PMSchedule.next_due_date < now
    )

    if branch_id:
        schedule_query = schedule_query.join(Equipment).join(Room).join(Floor).filter(
            Floor.branch_id == branch_id
        )

    schedules_overdue = schedule_query.count()

    # Get recent PM work orders
    recent_work_orders = query.filter(
        WorkOrder.status == "completed"
    ).order_by(WorkOrder.actual_end.desc()).limit(5).all()

    return {
        "summary": {
            "pending": pending_count,
            "in_progress": in_progress_count,
            "completed": completed_count,
            "overdue": overdue_count,
            "due_this_week": due_this_week,
            "schedules_overdue": schedules_overdue
        },
        "recent_completed": [
            {
                "wo_number": wo.wo_number,
                "title": wo.title,
                "completed_at": wo.actual_end.isoformat() if wo.actual_end else None,
                "equipment_name": wo.equipment.name if wo.equipment else None
            }
            for wo in recent_work_orders
        ],
        "branch_id": branch_id
    }
