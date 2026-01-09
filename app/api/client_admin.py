"""
Client Admin API endpoints

Admin endpoints for managing client portal users (invitations, user management).
These endpoints require admin authentication.
"""

from datetime import datetime
from typing import Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.database import get_db
from app.models import ClientUser, AddressBook, User, Company
from app.schemas import (
    ClientUserInvite, ClientUserResponse, ClientUserWithAddressBook, ClientUserList
)
from app.api.auth import get_current_user
from app.api.client_auth import generate_invitation_token
from app.services.email import EmailService
from app.config import settings

router = APIRouter(prefix="/admin/client-users", tags=["Client Admin"])
logger = logging.getLogger(__name__)


def send_client_invitation_email(client: ClientUser, invitation_url: str, company_name: str = "DoxSnap") -> bool:
    """
    Send invitation email to client user.
    Returns True if sent successfully, False otherwise.
    """
    try:
        email_service = EmailService()

        # Build full invitation URL
        base_url = settings.frontend_url if hasattr(settings, 'frontend_url') else "http://localhost:4200"
        full_url = f"{base_url}{invitation_url}"

        subject = f"You've been invited to the {company_name} Client Portal"

        message = f"""
        <h2>Welcome to the Client Portal!</h2>

        <p>Hi <strong>{client.name}</strong>,</p>

        <p>You've been invited to access the <strong>{company_name}</strong> client portal where you can:</p>

        <ul>
            <li>Submit service requests and tickets</li>
            <li>Track the status of your requests</li>
            <li>View work orders for your sites</li>
        </ul>

        <p style="margin: 30px 0;">
            <a href="{full_url}" style="background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 500; display: inline-block;">
                Accept Invitation & Set Password
            </a>
        </p>

        <p style="color: #666; font-size: 14px;">
            This invitation link will expire in 7 days. If you didn't expect this invitation, you can safely ignore this email.
        </p>

        <p style="color: #666; font-size: 14px;">
            If the button doesn't work, copy and paste this link into your browser:<br>
            <a href="{full_url}" style="color: #3b82f6;">{full_url}</a>
        </p>
        """

        success = email_service.send_email(client.email, subject, message)

        if success:
            logger.info(f"Client invitation email sent to {client.email}")
        else:
            logger.warning(f"Failed to send client invitation email to {client.email}")

        return success

    except Exception as e:
        logger.error(f"Error sending client invitation email: {str(e)}")
        # Log the invitation URL so admin can manually share if email fails
        logger.info(f"Manual invitation URL for {client.email}: {invitation_url}")
        return False


@router.get("", response_model=ClientUserList)
async def list_client_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100)
):
    """List all client users for the company (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    query = db.query(ClientUser).options(
        joinedload(ClientUser.address_book)
    ).filter(ClientUser.company_id == current_user.company_id)

    # Apply filters
    if status_filter:
        if status_filter == "pending":
            query = query.filter(ClientUser.invitation_accepted_at == None)
        elif status_filter == "active":
            query = query.filter(
                ClientUser.invitation_accepted_at != None,
                ClientUser.is_active == True
            )
        elif status_filter == "inactive":
            query = query.filter(ClientUser.is_active == False)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (ClientUser.email.ilike(search_term)) |
            (ClientUser.name.ilike(search_term))
        )

    # Get total count
    total = query.count()

    # Apply pagination and ordering
    clients = query.order_by(desc(ClientUser.created_at))\
        .offset((page - 1) * size)\
        .limit(size)\
        .all()

    # Convert to response with address book details
    users_data = []
    for client in clients:
        users_data.append(ClientUserWithAddressBook(
            id=client.id,
            email=client.email,
            name=client.name,
            phone=client.phone,
            company_id=client.company_id,
            address_book_id=client.address_book_id,
            is_active=client.is_active,
            invitation_sent_at=client.invitation_sent_at,
            invitation_accepted_at=client.invitation_accepted_at,
            created_at=client.created_at,
            last_login_at=client.last_login_at,
            address_book_name=client.address_book.alpha_name if client.address_book else None,
            address_book_number=client.address_book.address_number if client.address_book else None
        ))

    return ClientUserList(
        users=users_data,
        total=total,
        page=page,
        size=size
    )


@router.post("/invite", response_model=ClientUserWithAddressBook)
async def invite_client_user(
    invite_data: ClientUserInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Invite a new client user (admin only).
    Creates a client user record and sends an invitation email.
    """
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Check if email already exists
    existing = db.query(ClientUser).filter(
        ClientUser.email == invite_data.email,
        ClientUser.company_id == current_user.company_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A client user with this email already exists"
        )

    # Validate address book entry exists and belongs to company
    address_book = db.query(AddressBook).filter(
        AddressBook.id == invite_data.address_book_id,
        AddressBook.company_id == current_user.company_id
    ).first()
    if not address_book:
        raise HTTPException(status_code=400, detail="Invalid address book entry")

    # Validate address book type (should be Customer or Client Branch)
    if address_book.search_type not in ['C', 'CB']:
        raise HTTPException(
            status_code=400,
            detail="Address book entry must be a Customer (C) or Client Branch (CB)"
        )

    # Generate invitation token
    invitation_token = generate_invitation_token()

    # Create client user
    client = ClientUser(
        company_id=current_user.company_id,
        address_book_id=invite_data.address_book_id,
        email=invite_data.email,
        name=invite_data.name,
        phone=invite_data.phone,
        invitation_token=invitation_token,
        invitation_sent_at=datetime.utcnow(),
        invited_by=current_user.id
    )

    db.add(client)
    db.commit()
    db.refresh(client)

    # Get company name for the email
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    company_name = company.name if company else "DoxSnap"

    # Build invitation URL (frontend will handle this)
    # The actual URL will be something like: https://app.doxsnap.com/client/accept-invite?token=xxx
    invitation_url = f"/client/accept-invite?token={invitation_token}"

    # Send invitation email
    email_sent = send_client_invitation_email(client, invitation_url, company_name)

    if not email_sent:
        logger.warning(f"Invitation created but email failed for {client.email}. Token: {invitation_token}")

    return ClientUserWithAddressBook(
        id=client.id,
        email=client.email,
        name=client.name,
        phone=client.phone,
        company_id=client.company_id,
        address_book_id=client.address_book_id,
        is_active=client.is_active,
        invitation_sent_at=client.invitation_sent_at,
        invitation_accepted_at=client.invitation_accepted_at,
        created_at=client.created_at,
        last_login_at=client.last_login_at,
        address_book_name=address_book.alpha_name,
        address_book_number=address_book.address_number
    )


@router.get("/{client_id}", response_model=ClientUserWithAddressBook)
async def get_client_user(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific client user (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    client = db.query(ClientUser).options(
        joinedload(ClientUser.address_book)
    ).filter(
        ClientUser.id == client_id,
        ClientUser.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client user not found")

    return ClientUserWithAddressBook(
        id=client.id,
        email=client.email,
        name=client.name,
        phone=client.phone,
        company_id=client.company_id,
        address_book_id=client.address_book_id,
        is_active=client.is_active,
        invitation_sent_at=client.invitation_sent_at,
        invitation_accepted_at=client.invitation_accepted_at,
        created_at=client.created_at,
        last_login_at=client.last_login_at,
        address_book_name=client.address_book.alpha_name if client.address_book else None,
        address_book_number=client.address_book.address_number if client.address_book else None
    )


@router.put("/{client_id}", response_model=ClientUserWithAddressBook)
async def update_client_user(
    client_id: int,
    update_data: ClientUserInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a client user (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    client = db.query(ClientUser).filter(
        ClientUser.id == client_id,
        ClientUser.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client user not found")

    # Check for email conflict
    if update_data.email != client.email:
        existing = db.query(ClientUser).filter(
            ClientUser.email == update_data.email,
            ClientUser.company_id == current_user.company_id,
            ClientUser.id != client_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="A client user with this email already exists"
            )

    # Validate address book entry if changed
    if update_data.address_book_id != client.address_book_id:
        address_book = db.query(AddressBook).filter(
            AddressBook.id == update_data.address_book_id,
            AddressBook.company_id == current_user.company_id
        ).first()
        if not address_book:
            raise HTTPException(status_code=400, detail="Invalid address book entry")
        if address_book.search_type not in ['C', 'CB']:
            raise HTTPException(
                status_code=400,
                detail="Address book entry must be a Customer (C) or Client Branch (CB)"
            )

    # Update fields
    client.email = update_data.email
    client.name = update_data.name
    client.phone = update_data.phone
    client.address_book_id = update_data.address_book_id
    client.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(client)

    # Reload with address book
    client = db.query(ClientUser).options(
        joinedload(ClientUser.address_book)
    ).filter(ClientUser.id == client_id).first()

    return ClientUserWithAddressBook(
        id=client.id,
        email=client.email,
        name=client.name,
        phone=client.phone,
        company_id=client.company_id,
        address_book_id=client.address_book_id,
        is_active=client.is_active,
        invitation_sent_at=client.invitation_sent_at,
        invitation_accepted_at=client.invitation_accepted_at,
        created_at=client.created_at,
        last_login_at=client.last_login_at,
        address_book_name=client.address_book.alpha_name if client.address_book else None,
        address_book_number=client.address_book.address_number if client.address_book else None
    )


@router.delete("/{client_id}")
async def deactivate_client_user(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Deactivate a client user (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    client = db.query(ClientUser).filter(
        ClientUser.id == client_id,
        ClientUser.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client user not found")

    client.is_active = False
    client.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Client user deactivated successfully"}


@router.post("/{client_id}/reactivate")
async def reactivate_client_user(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reactivate a client user (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    client = db.query(ClientUser).filter(
        ClientUser.id == client_id,
        ClientUser.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client user not found")

    client.is_active = True
    client.updated_at = datetime.utcnow()
    db.commit()

    return {"message": "Client user reactivated successfully"}


@router.post("/{client_id}/resend-invitation")
async def resend_invitation(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resend invitation email to a client user (admin only)"""
    # Check admin role
    if current_user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=403, detail="Admin access required")

    client = db.query(ClientUser).filter(
        ClientUser.id == client_id,
        ClientUser.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client user not found")

    # Check if invitation was already accepted
    if client.invitation_accepted_at:
        raise HTTPException(
            status_code=400,
            detail="Invitation was already accepted"
        )

    # Generate new invitation token
    new_token = generate_invitation_token()
    client.invitation_token = new_token
    client.invitation_sent_at = datetime.utcnow()
    db.commit()

    # Get company name for the email
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    company_name = company.name if company else "DoxSnap"

    # Build invitation URL
    invitation_url = f"/client/accept-invite?token={new_token}"

    # Send invitation email
    email_sent = send_client_invitation_email(client, invitation_url, company_name)

    if email_sent:
        return {"message": "Invitation resent successfully"}
    else:
        return {"message": "Invitation token regenerated but email sending failed. Check server logs for the invitation URL."}
