"""
Client Portal API endpoints

Client-facing endpoints for submitting tickets and viewing work orders.
These endpoints use separate authentication from the admin portal.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func, or_

from app.database import get_db
from app.models import (
    ClientUser, ClientRefreshToken, Ticket, WorkOrder, Site,
    AddressBook, TicketActivity, Equipment
)
from app.schemas import (
    ClientUserLogin, ClientToken, ClientUserAcceptInvitation,
    ClientRefreshTokenRequest, ClientPasswordResetRequest, ClientPasswordReset,
    ClientProfileUpdate, ClientPasswordChange, ClientUserResponse,
    ClientDashboard, ClientTicketCreate, ClientWorkOrderBrief, ClientWorkOrderList,
    TicketList, Ticket as TicketSchema
)
from app.api.client_auth import (
    get_current_client, authenticate_client, get_client_by_email,
    get_client_by_invitation_token, create_client_tokens,
    validate_client_refresh_token, revoke_client_refresh_token,
    get_client_accessible_site_ids, get_client_accessible_sites,
    generate_client_refresh_token, get_client_refresh_token_expiry
)
from app.utils.security import get_password_hash, verify_password
from app.utils.rate_limiter import limiter, RateLimits
from app.config import settings

router = APIRouter(prefix="/client", tags=["Client Portal"])


# =============================================================================
# AUTHENTICATION ENDPOINTS
# =============================================================================

@router.post("/login", response_model=ClientToken)
@limiter.limit(RateLimits.CLIENT_LOGIN)
async def client_login(
    request: Request,
    credentials: ClientUserLogin,
    db: Session = Depends(get_db)
):
    """Login as a client user"""
    client = authenticate_client(db, credentials.email, credentials.password)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return create_client_tokens(db, client)


@router.post("/accept-invitation", response_model=ClientToken)
async def accept_invitation(
    data: ClientUserAcceptInvitation,
    db: Session = Depends(get_db)
):
    """Accept an invitation and set password"""
    client = get_client_by_invitation_token(db, data.invitation_token)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token"
        )

    # Check if invitation is expired (7 days)
    if client.invitation_sent_at:
        from datetime import timedelta
        if datetime.utcnow() > client.invitation_sent_at + timedelta(days=7):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has expired. Please request a new invitation."
            )

    # Validate password length
    if len(data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )

    # Set password and mark invitation as accepted
    client.hashed_password = get_password_hash(data.password)
    client.invitation_token = None  # Clear token
    client.invitation_accepted_at = datetime.utcnow()
    db.commit()

    return create_client_tokens(db, client)


@router.post("/refresh", response_model=ClientToken)
async def refresh_token(
    request: ClientRefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """Refresh access token using refresh token"""
    client = validate_client_refresh_token(db, request.refresh_token)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Revoke old refresh token
    db_token = db.query(ClientRefreshToken).filter(
        ClientRefreshToken.token == request.refresh_token
    ).first()
    if db_token:
        db_token.is_revoked = True
        db_token.revoked_at = datetime.utcnow()

    # Create new tokens
    return create_client_tokens(db, client)


@router.post("/logout")
async def client_logout(
    request: ClientRefreshTokenRequest,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Logout and revoke refresh token"""
    revoke_client_refresh_token(db, request.refresh_token, current_client.id)
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=ClientUserResponse)
async def get_current_client_user(
    current_client: ClientUser = Depends(get_current_client)
):
    """Get current client user profile"""
    return current_client


@router.put("/profile", response_model=ClientUserResponse)
async def update_client_profile(
    profile_data: ClientProfileUpdate,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Update client profile (name, phone)"""
    if profile_data.name is not None:
        current_client.name = profile_data.name
    if profile_data.phone is not None:
        current_client.phone = profile_data.phone

    current_client.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_client)

    return current_client


@router.post("/change-password")
async def change_client_password(
    password_data: ClientPasswordChange,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Change password (requires current password)"""
    # Verify current password
    if not verify_password(password_data.current_password, current_client.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Validate new password length
    if len(password_data.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters"
        )

    # Update password
    current_client.hashed_password = get_password_hash(password_data.new_password)
    current_client.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Password changed successfully"}


# =============================================================================
# DASHBOARD ENDPOINT
# =============================================================================

@router.get("/dashboard", response_model=ClientDashboard)
async def get_client_dashboard(
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Get dashboard summary for client"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    # Count sites
    total_sites = len(accessible_site_ids)

    if not accessible_site_ids:
        return ClientDashboard(
            total_sites=0,
            total_tickets=0,
            open_tickets=0,
            pending_work_orders=0,
            completed_work_orders=0,
            recent_tickets=[],
            upcoming_work_orders=[]
        )

    # Count tickets
    ticket_base = db.query(Ticket).filter(
        Ticket.site_id.in_(accessible_site_ids),
        Ticket.company_id == current_client.company_id
    )
    total_tickets = ticket_base.count()
    open_tickets = ticket_base.filter(Ticket.status.in_(["open", "in_review", "approved"])).count()

    # Count work orders (from tickets)
    ticket_ids = [t.id for t in ticket_base.all()]
    wo_base = db.query(WorkOrder).filter(
        WorkOrder.site_id.in_(accessible_site_ids),
        WorkOrder.company_id == current_client.company_id
    )
    pending_work_orders = wo_base.filter(
        WorkOrder.status.in_(["draft", "pending", "in_progress", "on_hold"])
    ).count()
    completed_work_orders = wo_base.filter(WorkOrder.status == "completed").count()

    # Recent tickets (last 5)
    recent_tickets = db.query(Ticket).options(
        joinedload(Ticket.site)
    ).filter(
        Ticket.site_id.in_(accessible_site_ids),
        Ticket.company_id == current_client.company_id
    ).order_by(desc(Ticket.created_at)).limit(5).all()

    recent_tickets_data = [
        {
            "id": t.id,
            "ticket_number": t.ticket_number,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "site_name": t.site.name if t.site else None,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        for t in recent_tickets
    ]

    # Upcoming work orders (next 5 scheduled)
    upcoming_wos = db.query(WorkOrder).options(
        joinedload(WorkOrder.site)
    ).filter(
        WorkOrder.site_id.in_(accessible_site_ids),
        WorkOrder.company_id == current_client.company_id,
        WorkOrder.status.in_(["pending", "in_progress"]),
        WorkOrder.scheduled_start != None
    ).order_by(WorkOrder.scheduled_start).limit(5).all()

    upcoming_wos_data = [
        {
            "id": wo.id,
            "wo_number": wo.wo_number,
            "title": wo.title,
            "status": wo.status,
            "site_name": wo.site.name if wo.site else None,
            "scheduled_date": wo.scheduled_start.isoformat() if wo.scheduled_start else None
        }
        for wo in upcoming_wos
    ]

    return ClientDashboard(
        total_sites=total_sites,
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        pending_work_orders=pending_work_orders,
        completed_work_orders=completed_work_orders,
        recent_tickets=recent_tickets_data,
        upcoming_work_orders=upcoming_wos_data
    )


# =============================================================================
# SITE ENDPOINTS
# =============================================================================

@router.get("/sites")
async def list_client_sites(
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """List sites accessible to the client"""
    sites = get_client_accessible_sites(db, current_client)

    return {
        "sites": [
            {
                "id": s.id,
                "name": s.name,
                "code": s.code,
                "address": s.address,
                "city": s.city,
                "is_active": s.is_active
            }
            for s in sites
        ],
        "total": len(sites)
    }


# =============================================================================
# TICKET ENDPOINTS
# =============================================================================

@router.get("/tickets", response_model=TicketList)
async def list_client_tickets(
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client),
    status: Optional[str] = None,
    site_id: Optional[int] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
):
    """List tickets for client's accessible sites"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    if not accessible_site_ids:
        return TicketList(tickets=[], total=0, page=page, size=size)

    query = db.query(Ticket).options(
        joinedload(Ticket.site),
        joinedload(Ticket.work_order)
    ).filter(
        Ticket.site_id.in_(accessible_site_ids),
        Ticket.company_id == current_client.company_id
    )

    # Apply filters
    if status:
        query = query.filter(Ticket.status == status)
    if site_id:
        # Validate site_id is accessible
        if site_id in accessible_site_ids:
            query = query.filter(Ticket.site_id == site_id)
        else:
            return TicketList(tickets=[], total=0, page=page, size=size)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Ticket.ticket_number.ilike(search_term),
                Ticket.title.ilike(search_term),
                Ticket.description.ilike(search_term)
            )
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


@router.get("/tickets/{ticket_id}")
async def get_client_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Get a specific ticket (must be for an accessible site)"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    ticket = db.query(Ticket).options(
        joinedload(Ticket.site),
        joinedload(Ticket.work_order)
    ).filter(
        Ticket.id == ticket_id,
        Ticket.site_id.in_(accessible_site_ids),
        Ticket.company_id == current_client.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return ticket


@router.post("/tickets")
async def create_client_ticket(
    ticket_data: ClientTicketCreate,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Create a new ticket for an accessible site"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    # Validate site is accessible
    if ticket_data.site_id not in accessible_site_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this site"
        )

    # Get site for validation
    site = db.query(Site).filter(Site.id == ticket_data.site_id).first()
    if not site:
        raise HTTPException(status_code=400, detail="Invalid site")

    # Validate priority
    valid_priorities = ["Low", "Medium", "High", "Urgent"]
    priority = ticket_data.priority or "Medium"
    if priority not in valid_priorities:
        priority = "Medium"

    # Generate ticket number
    from app.api.tickets import generate_ticket_number
    ticket_number = generate_ticket_number(db, current_client.company_id)

    # Create ticket
    ticket = Ticket(
        company_id=current_client.company_id,
        ticket_number=ticket_number,
        title=ticket_data.description[:100] if ticket_data.description else "Service Request",
        description=ticket_data.description,
        category="other",  # Default for client-submitted tickets
        priority=priority.lower(),
        status="open",
        site_id=ticket_data.site_id,
        service_id=ticket_data.service_id,
        requester_name=ticket_data.contact_name or current_client.name,
        requester_email=ticket_data.contact_email or current_client.email,
        requester_phone=ticket_data.contact_phone or current_client.phone,
        source="client_portal",  # Mark as submitted from client portal
        client_user_id=current_client.id  # Link to client user
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Log activity
    activity = TicketActivity(
        company_id=current_client.company_id,
        ticket_id=ticket.id,
        activity_type="created",
        subject="Ticket Created",
        description=f"Ticket submitted via Client Portal by {current_client.name}",
        created_at=datetime.utcnow()
    )
    db.add(activity)
    db.commit()

    # Reload with relationships
    ticket = db.query(Ticket).options(
        joinedload(Ticket.site)
    ).filter(Ticket.id == ticket.id).first()

    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "site_id": ticket.site_id,
        "site_name": ticket.site.name if ticket.site else None,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None
    }


@router.get("/tickets/{ticket_id}/timeline")
async def get_client_ticket_timeline(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Get timeline/activity history for a ticket"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    # Verify ticket access
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.site_id.in_(accessible_site_ids),
        Ticket.company_id == current_client.company_id
    ).first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Get timeline activities
    activities = db.query(TicketActivity).filter(
        TicketActivity.ticket_id == ticket_id
    ).order_by(desc(TicketActivity.created_at)).all()

    return {
        "ticket_id": ticket_id,
        "ticket_number": ticket.ticket_number,
        "activities": [
            {
                "id": a.id,
                "type": a.activity_type,
                "subject": a.subject,
                "description": a.description,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in activities
        ]
    }


# =============================================================================
# WORK ORDER ENDPOINTS
# =============================================================================

@router.get("/work-orders", response_model=ClientWorkOrderList)
async def list_client_work_orders(
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client),
    status: Optional[str] = None,
    site_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
):
    """List work orders for client's accessible sites (limited info)"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    if not accessible_site_ids:
        return ClientWorkOrderList(work_orders=[], total=0, page=page, size=size)

    query = db.query(WorkOrder).options(
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.equipment)
    ).filter(
        WorkOrder.site_id.in_(accessible_site_ids),
        WorkOrder.company_id == current_client.company_id
    )

    # Apply filters
    if status:
        query = query.filter(WorkOrder.status == status)
    if site_id:
        if site_id in accessible_site_ids:
            query = query.filter(WorkOrder.site_id == site_id)
        else:
            return ClientWorkOrderList(work_orders=[], total=0, page=page, size=size)

    # Get total count
    total = query.count()

    # Apply pagination and ordering
    work_orders = query.order_by(desc(WorkOrder.created_at))\
        .offset((page - 1) * size)\
        .limit(size)\
        .all()

    # Convert to limited view
    wo_list = []
    for wo in work_orders:
        # Get technician name from slot assignments if available
        technician_name = None
        if wo.slot_assignments:
            for slot_assign in wo.slot_assignments:
                if slot_assign.address_book:
                    technician_name = slot_assign.address_book.alpha_name
                    break

        wo_list.append(ClientWorkOrderBrief(
            id=wo.id,
            wo_number=wo.wo_number,
            title=wo.title,
            description=wo.description,
            work_order_type=wo.work_order_type,
            priority=wo.priority,
            status=wo.status,
            site_id=wo.site_id,
            site_name=wo.site.name if wo.site else None,
            equipment_name=wo.equipment.name if wo.equipment else None,
            scheduled_date=wo.scheduled_start,
            scheduled_end=wo.scheduled_end,
            actual_start=wo.actual_start,
            actual_end=wo.actual_end,
            completed_date=wo.actual_end,
            technician_name=technician_name,
            completion_notes=wo.completion_notes if wo.status == "completed" else None,
            created_at=wo.created_at
        ))

    return ClientWorkOrderList(
        work_orders=wo_list,
        total=total,
        page=page,
        size=size
    )


@router.get("/work-orders/{wo_id}", response_model=ClientWorkOrderBrief)
async def get_client_work_order(
    wo_id: int,
    db: Session = Depends(get_db),
    current_client: ClientUser = Depends(get_current_client)
):
    """Get a specific work order (limited info)"""
    accessible_site_ids = get_client_accessible_site_ids(db, current_client)

    wo = db.query(WorkOrder).options(
        joinedload(WorkOrder.site),
        joinedload(WorkOrder.equipment)
    ).filter(
        WorkOrder.id == wo_id,
        WorkOrder.site_id.in_(accessible_site_ids),
        WorkOrder.company_id == current_client.company_id
    ).first()

    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    # Get technician name
    technician_name = None
    if wo.slot_assignments:
        for slot_assign in wo.slot_assignments:
            if slot_assign.address_book:
                technician_name = slot_assign.address_book.alpha_name
                break

    return ClientWorkOrderBrief(
        id=wo.id,
        wo_number=wo.wo_number,
        title=wo.title,
        description=wo.description,
        work_order_type=wo.work_order_type,
        priority=wo.priority,
        status=wo.status,
        site_id=wo.site_id,
        site_name=wo.site.name if wo.site else None,
        equipment_name=wo.equipment.name if wo.equipment else None,
        scheduled_date=wo.scheduled_start,
        scheduled_end=wo.scheduled_end,
        actual_start=wo.actual_start,
        actual_end=wo.actual_end,
        completed_date=wo.actual_end,
        technician_name=technician_name,
        completion_notes=wo.completion_notes if wo.status == "completed" else None,
        created_at=wo.created_at
    )
