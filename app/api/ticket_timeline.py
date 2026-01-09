"""
Ticket Timeline API endpoints
Provides activity timeline for service requests including manual notes
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from typing import Optional, List
from datetime import datetime
import json

from app.database import get_db
from app.models import (
    Ticket, TicketActivity, User, WorkOrder,
    WorkOrderTimeEntry, WorkOrderChecklistItem, WorkOrderSparePart,
    WorkOrderSnapshot, WorkOrderCompletion
)
from app.schemas import (
    TicketNoteCreate, TicketNoteUpdate,
    TimelineActivity, TicketTimeline
)
from app.api.auth import get_current_user

router = APIRouter(prefix="/tickets", tags=["Ticket Timeline"])


def format_activity(
    id: int,
    activity_type: str,
    subject: str,
    description: str,
    created_at: datetime,
    created_by_name: str,
    source: str,
    previous_status: str = None,
    new_status: str = None,
    extra_data: dict = None
) -> dict:
    """Helper to format timeline activity consistently"""
    return {
        "id": id,
        "activity_type": activity_type,
        "subject": subject,
        "description": description,
        "created_at": created_at,
        "created_by_name": created_by_name,
        "source": source,
        "previous_status": previous_status,
        "new_status": new_status,
        "extra_data": extra_data
    }


def get_work_order_activities(db: Session, work_order: WorkOrder) -> List[dict]:
    """
    Aggregate all activities from a work order and its related entities.
    Returns a list of formatted activity dictionaries.
    """
    activities = []

    # Work order created
    creator_name = None
    if work_order.created_by:
        creator = db.query(User).filter(User.id == work_order.created_by).first()
        creator_name = creator.name if creator else None

    activities.append(format_activity(
        id=work_order.id * 10000,  # Use offset to avoid ID conflicts
        activity_type="wo_created",
        subject=f"Work Order {work_order.wo_number} created",
        description=f"Type: {work_order.work_order_type}, Priority: {work_order.priority}",
        created_at=work_order.created_at,
        created_by_name=creator_name,
        source="work_order"
    ))

    # Time entries
    time_entries = db.query(WorkOrderTimeEntry).filter(
        WorkOrderTimeEntry.work_order_id == work_order.id
    ).all()

    for entry in time_entries:
        tech_name = None
        if entry.address_book_id:
            from app.models import AddressBook
            ab = db.query(AddressBook).filter(AddressBook.id == entry.address_book_id).first()
            tech_name = ab.alpha_name if ab else None
        elif entry.technician_id:
            from app.models import Technician
            tech = db.query(Technician).filter(Technician.id == entry.technician_id).first()
            tech_name = tech.name if tech else None

        hours = entry.hours_worked or 0
        activities.append(format_activity(
            id=entry.id * 10000 + 1,
            activity_type="wo_time_entry",
            subject=f"{hours:.1f} hours logged" + (f" by {tech_name}" if tech_name else ""),
            description=entry.work_description,
            created_at=entry.created_at,
            created_by_name=tech_name,
            source="work_order",
            extra_data={"hours": hours, "is_overtime": entry.is_overtime}
        ))

    # Checklist items completed
    checklist_items = db.query(WorkOrderChecklistItem).filter(
        WorkOrderChecklistItem.work_order_id == work_order.id,
        WorkOrderChecklistItem.is_completed == True
    ).all()

    for item in checklist_items:
        completed_by_name = None
        if item.completed_by:
            user = db.query(User).filter(User.id == item.completed_by).first()
            completed_by_name = user.name if user else None

        activities.append(format_activity(
            id=item.id * 10000 + 2,
            activity_type="wo_checklist_completed",
            subject=f"Checklist item completed: {item.description[:50]}..." if len(item.description or '') > 50 else f"Checklist item completed: {item.description}",
            description=item.notes,
            created_at=item.completed_at or item.created_at,
            created_by_name=completed_by_name,
            source="work_order"
        ))

    # Spare parts used
    spare_parts = db.query(WorkOrderSparePart).filter(
        WorkOrderSparePart.work_order_id == work_order.id
    ).all()

    for part in spare_parts:
        from app.models import SparePart
        sp = db.query(SparePart).filter(SparePart.id == part.spare_part_id).first()
        part_name = sp.name if sp else "Unknown part"

        activities.append(format_activity(
            id=part.id * 10000 + 3,
            activity_type="wo_spare_part",
            subject=f"Part issued: {part_name} x{part.quantity}",
            description=None,
            created_at=part.created_at,
            created_by_name=None,
            source="work_order",
            extra_data={"quantity": part.quantity, "part_name": part_name}
        ))

    # Snapshots/photos
    snapshots = db.query(WorkOrderSnapshot).filter(
        WorkOrderSnapshot.work_order_id == work_order.id
    ).all()

    for snap in snapshots:
        taken_by_name = None
        if snap.taken_by:
            user = db.query(User).filter(User.id == snap.taken_by).first()
            taken_by_name = user.name if user else None

        activities.append(format_activity(
            id=snap.id * 10000 + 4,
            activity_type="wo_photo_uploaded",
            subject=f"Photo uploaded" + (f": {snap.caption}" if snap.caption else ""),
            description=snap.original_filename,
            created_at=snap.taken_at or snap.created_at,
            created_by_name=taken_by_name,
            source="work_order"
        ))

    # Completion
    completion = db.query(WorkOrderCompletion).filter(
        WorkOrderCompletion.work_order_id == work_order.id
    ).first()

    if completion:
        activities.append(format_activity(
            id=completion.id * 10000 + 5,
            activity_type="wo_completed",
            subject=f"Work completed" + (f" - Signed by {completion.signed_by_name}" if completion.signed_by_name else ""),
            description=completion.comments,
            created_at=completion.signed_at or completion.created_at,
            created_by_name=completion.signed_by_name,
            source="work_order",
            extra_data={"rating": completion.rating} if completion.rating else None
        ))

    # Approval
    if work_order.approved_at:
        approver_name = None
        if work_order.approved_by:
            user = db.query(User).filter(User.id == work_order.approved_by).first()
            approver_name = user.name if user else None

        activities.append(format_activity(
            id=work_order.id * 10000 + 6,
            activity_type="wo_approved",
            subject="Work Order approved",
            description=None,
            created_at=work_order.approved_at,
            created_by_name=approver_name,
            source="work_order"
        ))

    # Cancellation
    if work_order.cancelled_at:
        canceller_name = None
        if work_order.cancelled_by:
            user = db.query(User).filter(User.id == work_order.cancelled_by).first()
            canceller_name = user.name if user else None

        activities.append(format_activity(
            id=work_order.id * 10000 + 7,
            activity_type="wo_cancelled",
            subject="Work Order cancelled",
            description=work_order.cancellation_reason,
            created_at=work_order.cancelled_at,
            created_by_name=canceller_name,
            source="work_order"
        ))

    return activities


@router.get("/{ticket_id}/timeline", response_model=TicketTimeline)
async def get_ticket_timeline(
    ticket_id: int,
    include_wo_activities: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get comprehensive timeline for a ticket.
    Aggregates ticket activities and optionally work order activities.
    """
    # Get ticket
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    activities = []

    # Get ticket activities
    ticket_activities = db.query(TicketActivity).options(
        joinedload(TicketActivity.creator)
    ).filter(
        TicketActivity.ticket_id == ticket_id,
        TicketActivity.is_deleted == False
    ).order_by(desc(TicketActivity.created_at)).all()

    for activity in ticket_activities:
        extra = None
        if activity.extra_data:
            try:
                extra = json.loads(activity.extra_data)
            except:
                pass

        activities.append(format_activity(
            id=activity.id,
            activity_type=activity.activity_type,
            subject=activity.subject,
            description=activity.description,
            created_at=activity.created_at,
            created_by_name=activity.creator.name if activity.creator else None,
            source="ticket",
            previous_status=activity.previous_status,
            new_status=activity.new_status,
            extra_data=extra
        ))

    # Get work order activities if ticket is converted
    work_order = None
    work_order_number = None

    if include_wo_activities and ticket.work_order_id:
        work_order = db.query(WorkOrder).filter(
            WorkOrder.id == ticket.work_order_id
        ).first()

        if work_order:
            work_order_number = work_order.wo_number
            wo_activities = get_work_order_activities(db, work_order)
            activities.extend(wo_activities)

    # Sort all activities by created_at descending
    activities.sort(key=lambda x: x["created_at"], reverse=True)

    return TicketTimeline(
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        work_order_id=ticket.work_order_id,
        work_order_number=work_order_number,
        activities=activities,
        total_count=len(activities)
    )


@router.post("/{ticket_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_ticket_note(
    ticket_id: int,
    note_data: TicketNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a manual note to the ticket timeline"""
    # Verify ticket exists and belongs to company
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Create note activity
    activity = TicketActivity(
        company_id=current_user.company_id,
        ticket_id=ticket_id,
        activity_type="note",
        subject=note_data.subject,
        description=note_data.description,
        created_by=current_user.id
    )

    db.add(activity)
    db.commit()
    db.refresh(activity)

    return {
        "id": activity.id,
        "message": "Note added successfully"
    }


@router.put("/{ticket_id}/notes/{note_id}")
async def update_ticket_note(
    ticket_id: int,
    note_id: int,
    note_data: TicketNoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a manual note (only notes can be updated, and only by creator or admin)"""
    # Get the note
    activity = db.query(TicketActivity).filter(
        TicketActivity.id == note_id,
        TicketActivity.ticket_id == ticket_id,
        TicketActivity.company_id == current_user.company_id,
        TicketActivity.activity_type == "note",
        TicketActivity.is_deleted == False
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Note not found")

    # Only creator or admin can update
    if activity.created_by != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="You can only edit your own notes")

    # Update fields
    if note_data.subject is not None:
        activity.subject = note_data.subject
    if note_data.description is not None:
        activity.description = note_data.description

    db.commit()

    return {"message": "Note updated successfully"}


@router.delete("/{ticket_id}/notes/{note_id}")
async def delete_ticket_note(
    ticket_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Soft delete a note (only notes can be deleted, and only by creator or admin)"""
    # Get the note
    activity = db.query(TicketActivity).filter(
        TicketActivity.id == note_id,
        TicketActivity.ticket_id == ticket_id,
        TicketActivity.company_id == current_user.company_id,
        TicketActivity.activity_type == "note",
        TicketActivity.is_deleted == False
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Note not found")

    # Only creator or admin can delete
    if activity.created_by != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="You can only delete your own notes")

    # Soft delete
    activity.is_deleted = True
    activity.deleted_at = datetime.utcnow()
    activity.deleted_by = current_user.id

    db.commit()

    return {"message": "Note deleted successfully"}


# ============================================================================
# Activity Logging Helper Functions
# ============================================================================

def log_ticket_created(db: Session, ticket: Ticket, user: User):
    """Log when a ticket is created"""
    activity = TicketActivity(
        company_id=ticket.company_id,
        ticket_id=ticket.id,
        activity_type="ticket_created",
        subject=f"Service request {ticket.ticket_number} submitted",
        description=f"Category: {ticket.category}, Priority: {ticket.priority}",
        new_status="open",
        created_by=user.id
    )
    db.add(activity)


def log_status_change(
    db: Session,
    ticket: Ticket,
    old_status: str,
    new_status: str,
    user: User,
    notes: str = None
):
    """Log status transitions"""
    # Determine activity type based on new status
    if new_status == "approved":
        activity_type = "approved"
        subject = f"Ticket approved"
    elif new_status == "rejected":
        activity_type = "rejected"
        subject = f"Ticket rejected"
    else:
        activity_type = "status_changed"
        subject = f"Status changed from {old_status} to {new_status}"

    activity = TicketActivity(
        company_id=ticket.company_id,
        ticket_id=ticket.id,
        activity_type=activity_type,
        subject=subject,
        description=notes,
        previous_status=old_status,
        new_status=new_status,
        created_by=user.id
    )
    db.add(activity)


def log_conversion(db: Session, ticket: Ticket, work_order, user: User):
    """Log when ticket is converted to work order"""
    activity = TicketActivity(
        company_id=ticket.company_id,
        ticket_id=ticket.id,
        activity_type="converted",
        subject=f"Converted to Work Order {work_order.wo_number}",
        description=f"Work order type: {work_order.work_order_type}",
        previous_status=ticket.status,
        new_status="converted",
        extra_data=json.dumps({"work_order_id": work_order.id, "wo_number": work_order.wo_number}),
        created_by=user.id
    )
    db.add(activity)
