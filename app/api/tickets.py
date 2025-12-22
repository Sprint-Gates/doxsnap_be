"""
Ticket/Service Request API endpoints
Allows users to submit requests that can be converted to work orders
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func
from typing import Optional, List
from datetime import datetime
import uuid
import os
import json

from app.database import get_db
from app.models import Ticket, User, Site, Equipment, WorkOrder, Company, AddressBook
from app.schemas import (
    TicketCreate, TicketUpdate, Ticket as TicketSchema,
    TicketList, TicketStatusUpdate, TicketConvertToWorkOrder
)
from app.schemas import CancelTicketRequest
from app.api.auth import get_current_user

router = APIRouter(prefix="/tickets", tags=["Tickets"])

def generate_ticket_number(db: Session, company_id: int) -> str:
    """Generate a unique ticket number in format TKT-YYYYMMDD-XXXX"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"TKT-{today}-"

    # Find the latest ticket number for today
    latest = db.query(Ticket).filter(
        Ticket.company_id == company_id,
        Ticket.ticket_number.like(f"{prefix}%")
    ).order_by(desc(Ticket.ticket_number)).first()

    if latest:
        try:
            last_num = int(latest.ticket_number.split("-")[-1])
            new_num = last_num + 1
        except ValueError:
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{new_num:04d}"


@router.get("/", response_model=TicketList)
async def list_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    site_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
):
    """List all tickets for the company"""
    query = db.query(Ticket).options(
        joinedload(Ticket.requester),
        joinedload(Ticket.site),
        joinedload(Ticket.equipment),
        joinedload(Ticket.work_order)
    ).filter(Ticket.company_id == current_user.company_id)

    # Apply filters
    if status:
        query = query.filter(Ticket.status == status)
    if category:
        query = query.filter(Ticket.category == category)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if site_id:
        query = query.filter(Ticket.site_id == site_id)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Ticket.ticket_number.ilike(search_term)) |
            (Ticket.title.ilike(search_term)) |
            (Ticket.description.ilike(search_term))
        )

    # Get total count
    total = query.count()

    # Apply pagination and ordering
    tickets = query.order_by(desc(Ticket.created_at))\
        .offset((page - 1) * size)\
        .limit(size)\
        .all()

    return TicketList(
        tickets=tickets,
        total=total,
        page=page,
        size=size
    )


@router.get("/my-tickets", response_model=TicketList)
async def list_my_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
):
    """List tickets submitted by the current user"""
    query = db.query(Ticket).options(
        joinedload(Ticket.site),
        joinedload(Ticket.equipment),
        joinedload(Ticket.work_order)
    ).filter(
        Ticket.company_id == current_user.company_id,
        Ticket.requested_by == current_user.id
    )

    if status:
        query = query.filter(Ticket.status == status)

    total = query.count()

    tickets = query.order_by(desc(Ticket.created_at))\
        .offset((page - 1) * size)\
        .limit(size)\
        .all()

    return TicketList(
        tickets=tickets,
        total=total,
        page=page,
        size=size
    )


@router.get("/stats")
async def get_ticket_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get ticket statistics for the company"""
    base_query = db.query(Ticket).filter(Ticket.company_id == current_user.company_id)

    total = base_query.count()
    open_count = base_query.filter(Ticket.status == "open").count()
    in_review = base_query.filter(Ticket.status == "in_review").count()
    approved = base_query.filter(Ticket.status == "approved").count()
    converted = base_query.filter(Ticket.status == "converted").count()
    rejected = base_query.filter(Ticket.status == "rejected").count()
    closed = base_query.filter(Ticket.status == "closed").count()

    # Priority breakdown
    urgent = base_query.filter(Ticket.priority == "urgent", Ticket.status.in_(["open", "in_review", "approved"])).count()
    high = base_query.filter(Ticket.priority == "high", Ticket.status.in_(["open", "in_review", "approved"])).count()

    return {
        "total": total,
        "open": open_count,
        "in_review": in_review,
        "approved": approved,
        "converted": converted,
        "rejected": rejected,
        "closed": closed,
        "urgent_pending": urgent,
        "high_priority_pending": high
    }


@router.get("/{ticket_id}", response_model=TicketSchema)
async def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific ticket by ID"""
    ticket = db.query(Ticket).options(
        joinedload(Ticket.requester),
        joinedload(Ticket.site),
        joinedload(Ticket.equipment),
        joinedload(Ticket.work_order)
    ).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return ticket


@router.post("/", response_model=TicketSchema)
async def create_ticket(
    ticket_data: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new ticket/service request"""
    # Validate category
    valid_categories = ["maintenance", "repair", "installation", "inspection", "other"]
    if ticket_data.category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}")

    # Validate priority
    valid_priorities = ["low", "medium", "high", "urgent"]
    if ticket_data.priority not in valid_priorities:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}")

    # Validate site if provided - must be linked via address_book
    if ticket_data.site_id:
        site = db.query(Site).filter(Site.id == ticket_data.site_id).first()
        if not site:
            raise HTTPException(status_code=400, detail="Invalid site")

        # Site must be linked to an address book entry
        if not site.address_book_id:
            raise HTTPException(status_code=400, detail="Invalid site - not linked to Address Book")

        # Verify ownership via address_book
        ab_entry = db.query(AddressBook).filter(
            AddressBook.id == site.address_book_id,
            AddressBook.company_id == current_user.company_id
        ).first()
        if not ab_entry:
            raise HTTPException(status_code=400, detail="Invalid site")

    # Validate equipment if provided
    if ticket_data.equipment_id:
        equipment = db.query(Equipment).filter(Equipment.id == ticket_data.equipment_id).first()
        if not equipment:
            raise HTTPException(status_code=400, detail="Invalid equipment")

    # Generate ticket number
    ticket_number = generate_ticket_number(db, current_user.company_id)

    # Create ticket
    ticket = Ticket(
        company_id=current_user.company_id,
        ticket_number=ticket_number,
        title=ticket_data.title,
        description=ticket_data.description,
        category=ticket_data.category,
        priority=ticket_data.priority,
        status="open",
        site_id=ticket_data.site_id,
        building_id=ticket_data.building_id,
        floor_id=ticket_data.floor_id,
        room_id=ticket_data.room_id,
        location_description=ticket_data.location_description,
        equipment_id=ticket_data.equipment_id,
        requested_by=current_user.id,
        requester_name=ticket_data.requester_name or current_user.name,
        requester_email=ticket_data.requester_email or current_user.email,
        requester_phone=ticket_data.requester_phone,
        preferred_date=ticket_data.preferred_date,
        preferred_time_slot=ticket_data.preferred_time_slot
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Log activity
    from app.api.ticket_timeline import log_ticket_created
    log_ticket_created(db, ticket, current_user)
    db.commit()

    # Load relationships
    ticket = db.query(Ticket).options(
        joinedload(Ticket.requester),
        joinedload(Ticket.site),
        joinedload(Ticket.equipment)
    ).filter(Ticket.id == ticket.id).first()

    return ticket


@router.put("/{ticket_id}", response_model=TicketSchema)
async def update_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a ticket"""
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Only allow updates if ticket is not converted
    if ticket.status == "converted":
        raise HTTPException(status_code=400, detail="Cannot update a converted ticket")

    # Update fields
    update_data = ticket_data.model_dump(exclude_unset=True)

    # Validate category if provided
    if "category" in update_data:
        valid_categories = ["maintenance", "repair", "installation", "inspection", "other"]
        if update_data["category"] not in valid_categories:
            raise HTTPException(status_code=400, detail=f"Invalid category")

    # Validate priority if provided
    if "priority" in update_data:
        valid_priorities = ["low", "medium", "high", "urgent"]
        if update_data["priority"] not in valid_priorities:
            raise HTTPException(status_code=400, detail=f"Invalid priority")

    for field, value in update_data.items():
        setattr(ticket, field, value)

    db.commit()
    db.refresh(ticket)

    # Load relationships
    ticket = db.query(Ticket).options(
        joinedload(Ticket.requester),
        joinedload(Ticket.site),
        joinedload(Ticket.equipment),
        joinedload(Ticket.work_order)
    ).filter(Ticket.id == ticket.id).first()

    return ticket


@router.put("/{ticket_id}/status", response_model=TicketSchema)
async def update_ticket_status(
    ticket_id: int,
    status_data: TicketStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update ticket status (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Validate status
    valid_statuses = ["open", "in_review", "approved", "rejected", "closed"]
    if status_data.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Cannot set to 'converted' directly - use the convert endpoint")

    # Track old status for activity log
    old_status = ticket.status

    # Update status
    ticket.status = status_data.status
    ticket.reviewed_by = current_user.id
    ticket.reviewed_at = datetime.utcnow()

    if status_data.review_notes:
        ticket.review_notes = status_data.review_notes

    if status_data.status == "rejected" and status_data.rejection_reason:
        ticket.rejection_reason = status_data.rejection_reason

    db.commit()
    db.refresh(ticket)

    # Log activity
    from app.api.ticket_timeline import log_status_change
    notes = status_data.review_notes or status_data.rejection_reason
    log_status_change(db, ticket, old_status, status_data.status, current_user, notes)
    db.commit()

    # Load relationships
    ticket = db.query(Ticket).options(
        joinedload(Ticket.requester),
        joinedload(Ticket.site),
        joinedload(Ticket.equipment),
        joinedload(Ticket.work_order)
    ).filter(Ticket.id == ticket.id).first()

    return ticket


@router.post("/{ticket_id}/convert", response_model=TicketSchema)
async def convert_ticket_to_work_order(
    ticket_id: int,
    convert_data: TicketConvertToWorkOrder,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Convert an approved ticket to a work order (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Check if already converted
    if ticket.status == "converted":
        raise HTTPException(status_code=400, detail="Ticket has already been converted")

    # Check if ticket is approved or open (allow direct conversion)
    if ticket.status not in ["open", "in_review", "approved"]:
        raise HTTPException(status_code=400, detail=f"Cannot convert ticket with status '{ticket.status}'")

    # Generate work order number
    today = datetime.now().strftime("%Y%m%d")
    wo_prefix = f"WO-{today}-"
    latest_wo = db.query(WorkOrder).filter(
        WorkOrder.company_id == current_user.company_id,
        WorkOrder.wo_number.like(f"{wo_prefix}%")
    ).order_by(desc(WorkOrder.wo_number)).first()

    if latest_wo:
        try:
            last_num = int(latest_wo.wo_number.split("-")[-1])
            wo_num = last_num + 1
        except ValueError:
            wo_num = 1
    else:
        wo_num = 1

    wo_number = f"{wo_prefix}{wo_num:04d}"

    # Create work order
    work_order = WorkOrder(
        company_id=current_user.company_id,
        wo_number=wo_number,
        title=ticket.title,
        description=f"[From Ticket {ticket.ticket_number}]\n\n{ticket.description}",
        work_order_type=convert_data.work_order_type,
        priority=ticket.priority,
        status="pending",
        site_id=ticket.site_id,
        floor_id=ticket.floor_id,
        room_id=ticket.room_id,
        equipment_id=ticket.equipment_id,
        scheduled_start=convert_data.scheduled_start,
        scheduled_end=convert_data.scheduled_end,
        assigned_hhd_id=convert_data.assigned_hhd_id,
        is_billable=convert_data.is_billable,
        contract_id=convert_data.contract_id,
        notes=convert_data.notes or f"Created from ticket {ticket.ticket_number}",
        created_by=current_user.id
    )

    db.add(work_order)
    db.flush()  # Get work order ID

    # Assign technicians if provided
    if convert_data.technician_ids:
        from app.models import Technician
        technicians = db.query(Technician).filter(
            Technician.id.in_(convert_data.technician_ids),
            Technician.company_id == current_user.company_id
        ).all()
        work_order.assigned_technicians = technicians

    # Update ticket
    old_status = ticket.status
    ticket.status = "converted"
    ticket.work_order_id = work_order.id
    ticket.converted_at = datetime.utcnow()
    ticket.converted_by = current_user.id

    db.commit()
    db.refresh(ticket)

    # Log activity
    from app.api.ticket_timeline import log_conversion
    log_conversion(db, ticket, work_order, current_user)
    db.commit()

    # Load relationships
    ticket = db.query(Ticket).options(
        joinedload(Ticket.requester),
        joinedload(Ticket.site),
        joinedload(Ticket.equipment),
        joinedload(Ticket.work_order)
    ).filter(Ticket.id == ticket.id).first()

    return ticket


@router.delete("/{ticket_id}")
async def delete_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a ticket (admin only, only if not converted)"""
    # Check admin role
    if current_user.role not in ["admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.status == "converted":
        raise HTTPException(status_code=400, detail="Cannot delete a converted ticket")

    db.delete(ticket)
    db.commit()

    return {"message": "Ticket deleted successfully"}

@router.post("/{ticket_id}/cancel")
async def cancel_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cancel a ticket by setting its status to 'cancelled'.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.company_id == current_user.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.status == "cancelled":
        raise HTTPException(status_code=400, detail="Ticket is already cancelled")

    try:
        ticket.status = "cancelled"
        ticket.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(ticket)

        return {
            "success": True,
            "message": f"Ticket {ticket.ticket_number} has been cancelled",
            "ticket": ticket
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error cancelling ticket: {str(e)}"
        )

