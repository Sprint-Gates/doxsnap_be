"""
CRM Leads API
Handles lead management, conversion to clients/opportunities
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from datetime import datetime
from app.database import get_db
from app.models import Lead, LeadSource, Client, Opportunity, PipelineStage, User, AddressBook
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


# =============================================================================
# SCHEMAS
# =============================================================================

class LeadSourceCreate(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = 0


class LeadSourceUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class LeadCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    employee_count: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    source_id: Optional[int] = None
    status: Optional[str] = "new"
    rating: Optional[str] = None
    estimated_value: Optional[float] = None
    currency: Optional[str] = "USD"
    assigned_to: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class LeadUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    employee_count: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    source_id: Optional[int] = None
    status: Optional[str] = None
    rating: Optional[str] = None
    estimated_value: Optional[float] = None
    currency: Optional[str] = None
    assigned_to: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class LeadConvertRequest(BaseModel):
    create_client: bool = True
    create_opportunity: bool = False
    opportunity_name: Optional[str] = None
    opportunity_amount: Optional[float] = None
    opportunity_stage_id: Optional[int] = None


# =============================================================================
# LEAD SOURCES ENDPOINTS
# =============================================================================

@router.get("/crm/lead-sources")
async def get_lead_sources(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all lead sources for the company"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    query = db.query(LeadSource).filter(LeadSource.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(LeadSource.is_active == True)

    sources = query.order_by(LeadSource.sort_order, LeadSource.name).all()

    return [{
        "id": s.id,
        "name": s.name,
        "code": s.code,
        "description": s.description,
        "is_active": s.is_active,
        "sort_order": s.sort_order
    } for s in sources]


@router.post("/crm/lead-sources")
async def create_lead_source(
    data: LeadSourceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new lead source"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    source = LeadSource(
        company_id=user.company_id,
        name=data.name,
        code=data.code,
        description=data.description,
        sort_order=data.sort_order or 0
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    return {"id": source.id, "name": source.name, "message": "Lead source created"}


@router.put("/crm/lead-sources/{source_id}")
async def update_lead_source(
    source_id: int,
    data: LeadSourceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a lead source"""
    source = db.query(LeadSource).filter(
        LeadSource.id == source_id,
        LeadSource.company_id == user.company_id
    ).first()

    if not source:
        raise HTTPException(status_code=404, detail="Lead source not found")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(source, field, value)

    db.commit()
    return {"message": "Lead source updated"}


@router.delete("/crm/lead-sources/{source_id}")
async def delete_lead_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a lead source (soft delete)"""
    source = db.query(LeadSource).filter(
        LeadSource.id == source_id,
        LeadSource.company_id == user.company_id
    ).first()

    if not source:
        raise HTTPException(status_code=404, detail="Lead source not found")

    source.is_active = False
    db.commit()
    return {"message": "Lead source deleted"}


# =============================================================================
# LEADS ENDPOINTS
# =============================================================================

def lead_to_response(lead: Lead, db: Session) -> dict:
    """Convert Lead model to response dict"""
    return {
        "id": lead.id,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "full_name": f"{lead.first_name} {lead.last_name or ''}".strip(),
        "email": lead.email,
        "phone": lead.phone,
        "mobile": lead.mobile,
        "job_title": lead.job_title,
        "company_name": lead.company_name,
        "industry": lead.industry,
        "website": lead.website,
        "employee_count": lead.employee_count,
        "address": lead.address,
        "city": lead.city,
        "state": lead.state,
        "country": lead.country,
        "postal_code": lead.postal_code,
        "source_id": lead.source_id,
        "source_name": lead.source.name if lead.source else None,
        "status": lead.status,
        "rating": lead.rating,
        "estimated_value": float(lead.estimated_value) if lead.estimated_value else None,
        "currency": lead.currency,
        "assigned_to": lead.assigned_to,
        "assignee_name": lead.assignee.name if lead.assignee else None,
        "description": lead.description,
        "notes": lead.notes,
        "converted_to_client_id": lead.converted_to_client_id,
        "converted_to_opportunity_id": lead.converted_to_opportunity_id,
        "converted_at": lead.converted_at.isoformat() if lead.converted_at else None,
        "created_by": lead.created_by,
        "creator_name": lead.creator.name if lead.creator else None,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None
    }


@router.get("/crm/leads")
async def get_leads(
    status: Optional[str] = None,
    rating: Optional[str] = None,
    source_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
    search: Optional[str] = None,
    include_converted: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all leads for the company"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    query = db.query(Lead).filter(Lead.company_id == user.company_id)

    if not include_converted:
        query = query.filter(Lead.status != "converted")

    if status:
        query = query.filter(Lead.status == status)

    if rating:
        query = query.filter(Lead.rating == rating)

    if source_id:
        query = query.filter(Lead.source_id == source_id)

    if assigned_to:
        query = query.filter(Lead.assigned_to == assigned_to)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Lead.first_name.ilike(search_term),
                Lead.last_name.ilike(search_term),
                Lead.email.ilike(search_term),
                Lead.company_name.ilike(search_term),
                Lead.phone.ilike(search_term)
            )
        )

    leads = query.order_by(Lead.created_at.desc()).all()

    return [lead_to_response(lead, db) for lead in leads]


@router.get("/crm/leads/stats")
async def get_lead_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get lead statistics"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    # Count by status
    status_counts = db.query(
        Lead.status,
        func.count(Lead.id)
    ).filter(
        Lead.company_id == user.company_id
    ).group_by(Lead.status).all()

    # Count by rating
    rating_counts = db.query(
        Lead.rating,
        func.count(Lead.id)
    ).filter(
        Lead.company_id == user.company_id,
        Lead.status != "converted"
    ).group_by(Lead.rating).all()

    # Total estimated value
    total_value = db.query(func.sum(Lead.estimated_value)).filter(
        Lead.company_id == user.company_id,
        Lead.status != "converted"
    ).scalar() or 0

    # Leads this month
    from datetime import datetime
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    leads_this_month = db.query(Lead).filter(
        Lead.company_id == user.company_id,
        Lead.created_at >= start_of_month
    ).count()

    total_leads = sum(c for s, c in status_counts)
    total_active = sum(c for s, c in status_counts if s != "converted")
    converted_count = sum(c for s, c in status_counts if s == "converted")
    conversion_rate = (converted_count / total_leads * 100) if total_leads > 0 else 0

    return {
        "total": total_leads,
        "by_status": {s: c for s, c in status_counts},
        "by_rating": {r or "unrated": c for r, c in rating_counts},
        "total_estimated_value": float(total_value),
        "leads_this_month": leads_this_month,
        "total_active": total_active,
        "conversion_rate": round(conversion_rate, 1)
    }


@router.get("/crm/leads/{lead_id}")
async def get_lead(
    lead_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific lead"""
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == user.company_id
    ).first()

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return lead_to_response(lead, db)


@router.post("/crm/leads")
async def create_lead(
    data: LeadCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new lead"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    lead = Lead(
        company_id=user.company_id,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        mobile=data.mobile,
        job_title=data.job_title,
        company_name=data.company_name,
        industry=data.industry,
        website=data.website,
        employee_count=data.employee_count,
        address=data.address,
        city=data.city,
        state=data.state,
        country=data.country,
        postal_code=data.postal_code,
        source_id=data.source_id,
        status=data.status or "new",
        rating=data.rating,
        estimated_value=data.estimated_value,
        currency=data.currency or "USD",
        assigned_to=data.assigned_to,
        description=data.description,
        notes=data.notes,
        created_by=user.id
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    return {"id": lead.id, "message": "Lead created successfully"}


@router.put("/crm/leads/{lead_id}")
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a lead"""
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == user.company_id
    ).first()

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.status == "converted":
        raise HTTPException(status_code=400, detail="Cannot update converted lead")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(lead, field, value)

    db.commit()
    return {"message": "Lead updated successfully"}


@router.delete("/crm/leads/{lead_id}")
async def delete_lead(
    lead_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a lead"""
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == user.company_id
    ).first()

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.status == "converted":
        raise HTTPException(status_code=400, detail="Cannot delete converted lead")

    db.delete(lead)
    db.commit()
    return {"message": "Lead deleted successfully"}


@router.post("/crm/leads/{lead_id}/convert")
async def convert_lead(
    lead_id: int,
    data: LeadConvertRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Convert a lead to client and/or opportunity"""
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == user.company_id
    ).first()

    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.status == "converted":
        raise HTTPException(status_code=400, detail="Lead already converted")

    result = {"lead_id": lead_id}

    # Create client if requested
    client_id = None
    address_book_id = None
    if data.create_client:
        # Generate next address number for Address Book
        entries = db.query(AddressBook.address_number).filter(
            AddressBook.company_id == user.company_id
        ).all()

        max_num = 0
        for (addr_num,) in entries:
            try:
                num = int(addr_num)
                if num > max_num:
                    max_num = num
            except (ValueError, TypeError):
                pass

        address_number = str(max_num + 1).zfill(8)

        # Create Address Book entry with search_type='C' (Customer)
        # This will automatically create a Client record through the address_book.py logic
        address_book_entry = AddressBook(
            company_id=user.company_id,
            address_number=address_number,
            search_type='C',  # Customer type - this makes it appear in client lists
            alpha_name=lead.company_name or f"{lead.first_name} {lead.last_name or ''}".strip(),
            mailing_name=f"{lead.first_name} {lead.last_name or ''}".strip() if lead.first_name else None,
            email=lead.email,
            phone_primary=lead.phone,
            address_line_1=lead.address,
            city=lead.city,
            state=lead.state,
            country=lead.country,
            postal_code=lead.postal_code,
            website=lead.website,
            notes=f"Converted from lead on {datetime.utcnow().strftime('%Y-%m-%d')}\n{lead.notes or ''}",
            is_active=True,
            created_by=user.id
        )
        db.add(address_book_entry)
        db.flush()
        address_book_id = address_book_entry.id

        # Create Client record linked to Address Book
        client = Client(
            company_id=user.company_id,
            name=lead.company_name or f"{lead.first_name} {lead.last_name or ''}".strip(),
            code=address_number,
            email=lead.email,
            phone=lead.phone,
            address=lead.address,
            city=lead.city,
            country=lead.country,
            contact_person=f"{lead.first_name} {lead.last_name or ''}".strip(),
            notes=f"Converted from lead on {datetime.utcnow().strftime('%Y-%m-%d')}\n{lead.notes or ''}",
            address_book_id=address_book_id,  # Link to Address Book
            is_active=True
        )
        db.add(client)
        db.flush()
        client_id = client.id

        # Update lead with both conversion IDs
        lead.converted_to_client_id = client_id
        lead.converted_to_address_book_id = address_book_id
        result["client_id"] = client_id
        result["address_book_id"] = address_book_id

    # Create opportunity if requested
    if data.create_opportunity:
        # Get first pipeline stage if not specified
        stage_id = data.opportunity_stage_id
        if not stage_id:
            first_stage = db.query(PipelineStage).filter(
                PipelineStage.company_id == user.company_id,
                PipelineStage.is_active == True
            ).order_by(PipelineStage.sort_order).first()
            stage_id = first_stage.id if first_stage else None

        opportunity = Opportunity(
            company_id=user.company_id,
            name=data.opportunity_name or lead.company_name or f"{lead.first_name} {lead.last_name or ''} Opportunity",
            client_id=client_id,
            lead_id=lead_id,
            contact_name=f"{lead.first_name} {lead.last_name or ''}".strip(),
            contact_email=lead.email,
            contact_phone=lead.phone,
            stage_id=stage_id,
            amount=data.opportunity_amount or lead.estimated_value,
            currency=lead.currency,
            assigned_to=lead.assigned_to,
            created_by=user.id
        )
        db.add(opportunity)
        db.flush()
        lead.converted_to_opportunity_id = opportunity.id
        result["opportunity_id"] = opportunity.id

    # Update lead status
    lead.status = "converted"
    lead.converted_at = datetime.utcnow()
    lead.converted_by = user.id

    db.commit()

    result["message"] = "Lead converted successfully"
    return result