"""
CRM Campaigns API
Handles marketing campaign management
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from datetime import datetime, date
from app.database import get_db
from app.models import Campaign, CampaignLead, Lead, User
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

class CampaignCreate(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    campaign_type: Optional[str] = None
    status: Optional[str] = "planned"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    currency: Optional[str] = "USD"
    expected_revenue: Optional[float] = None
    expected_response_rate: Optional[float] = None
    target_audience: Optional[str] = None
    owner_id: Optional[int] = None
    notes: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    campaign_type: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    actual_cost: Optional[float] = None
    currency: Optional[str] = None
    expected_revenue: Optional[float] = None
    expected_response_rate: Optional[float] = None
    target_audience: Optional[str] = None
    sent_count: Optional[int] = None
    response_count: Optional[int] = None
    leads_generated: Optional[int] = None
    opportunities_created: Optional[int] = None
    revenue_generated: Optional[float] = None
    owner_id: Optional[int] = None
    notes: Optional[str] = None


class CampaignLeadAdd(BaseModel):
    lead_ids: List[int]


class CampaignLeadUpdate(BaseModel):
    status: str  # sent, responded, converted
    notes: Optional[str] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

def campaign_to_response(campaign: Campaign, db: Session) -> dict:
    """Convert Campaign model to response dict"""
    # Get lead counts
    total_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign.id).count()
    responded_leads = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign.id,
        CampaignLead.status.in_(["responded", "converted"])
    ).count()
    converted_leads = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign.id,
        CampaignLead.status == "converted"
    ).count()

    # Calculate response rate
    actual_response_rate = (responded_leads / total_leads * 100) if total_leads > 0 else 0
    conversion_rate = (converted_leads / total_leads * 100) if total_leads > 0 else 0

    # Calculate ROI
    roi = None
    if campaign.actual_cost and float(campaign.actual_cost) > 0 and campaign.revenue_generated:
        roi = ((float(campaign.revenue_generated) - float(campaign.actual_cost)) / float(campaign.actual_cost)) * 100

    return {
        "id": campaign.id,
        "name": campaign.name,
        "code": campaign.code,
        "description": campaign.description,
        "campaign_type": campaign.campaign_type,
        "status": campaign.status,
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "budget": float(campaign.budget) if campaign.budget else None,
        "actual_cost": float(campaign.actual_cost) if campaign.actual_cost else None,
        "currency": campaign.currency,
        "expected_revenue": float(campaign.expected_revenue) if campaign.expected_revenue else None,
        "expected_response_rate": float(campaign.expected_response_rate) if campaign.expected_response_rate else None,
        "target_audience": campaign.target_audience,
        "sent_count": campaign.sent_count,
        "response_count": campaign.response_count,
        "leads_generated": campaign.leads_generated,
        "opportunities_created": campaign.opportunities_created,
        "revenue_generated": float(campaign.revenue_generated) if campaign.revenue_generated else None,
        "owner_id": campaign.owner_id,
        "owner_name": campaign.owner.name if campaign.owner else None,
        "notes": campaign.notes,
        "total_leads": total_leads,
        "responded_leads": responded_leads,
        "converted_leads": converted_leads,
        "actual_response_rate": round(actual_response_rate, 1),
        "conversion_rate": round(conversion_rate, 1),
        "roi": round(roi, 1) if roi is not None else None,
        "created_by": campaign.created_by,
        "creator_name": campaign.creator.name if campaign.creator else None,
        "created_at": campaign.created_at.isoformat(),
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None
    }


@router.get("/crm/campaigns")
async def get_campaigns(
    status: Optional[str] = None,
    campaign_type: Optional[str] = None,
    owner_id: Optional[int] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all campaigns for the company"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    query = db.query(Campaign).filter(Campaign.company_id == user.company_id)

    if status:
        query = query.filter(Campaign.status == status)

    if campaign_type:
        query = query.filter(Campaign.campaign_type == campaign_type)

    if owner_id:
        query = query.filter(Campaign.owner_id == owner_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Campaign.name.ilike(search_term),
                Campaign.code.ilike(search_term),
                Campaign.description.ilike(search_term)
            )
        )

    campaigns = query.order_by(Campaign.created_at.desc()).all()

    return [campaign_to_response(c, db) for c in campaigns]


@router.get("/crm/campaigns/stats")
async def get_campaign_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get campaign statistics"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    # Count by status
    status_counts = db.query(
        Campaign.status,
        func.count(Campaign.id)
    ).filter(
        Campaign.company_id == user.company_id
    ).group_by(Campaign.status).all()

    # Total budget
    total_budget = db.query(func.sum(Campaign.budget)).filter(
        Campaign.company_id == user.company_id
    ).scalar() or 0

    # Total actual cost
    total_cost = db.query(func.sum(Campaign.actual_cost)).filter(
        Campaign.company_id == user.company_id
    ).scalar() or 0

    # Total revenue generated
    total_revenue = db.query(func.sum(Campaign.revenue_generated)).filter(
        Campaign.company_id == user.company_id
    ).scalar() or 0

    # Total leads generated
    total_leads = db.query(func.sum(Campaign.leads_generated)).filter(
        Campaign.company_id == user.company_id
    ).scalar() or 0

    # Active campaigns count
    active_count = db.query(Campaign).filter(
        Campaign.company_id == user.company_id,
        Campaign.status == "active"
    ).count()

    return {
        "by_status": {s: c for s, c in status_counts},
        "total_budget": float(total_budget),
        "total_cost": float(total_cost),
        "total_revenue": float(total_revenue),
        "total_leads_generated": int(total_leads or 0),
        "active_count": active_count,
        "overall_roi": round(((float(total_revenue) - float(total_cost)) / float(total_cost) * 100), 1) if float(total_cost) > 0 else None
    }


@router.get("/crm/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific campaign"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return campaign_to_response(campaign, db)


@router.post("/crm/campaigns")
async def create_campaign(
    data: CampaignCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new campaign"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    campaign = Campaign(
        company_id=user.company_id,
        name=data.name,
        code=data.code,
        description=data.description,
        campaign_type=data.campaign_type,
        status=data.status or "planned",
        start_date=data.start_date,
        end_date=data.end_date,
        budget=data.budget,
        currency=data.currency or "USD",
        expected_revenue=data.expected_revenue,
        expected_response_rate=data.expected_response_rate,
        target_audience=data.target_audience,
        owner_id=data.owner_id or user.id,
        notes=data.notes,
        created_by=user.id
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    return {"id": campaign.id, "message": "Campaign created successfully"}


@router.put("/crm/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    data: CampaignUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a campaign"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(campaign, field, value)

    db.commit()
    return {"message": "Campaign updated successfully"}


@router.delete("/crm/campaigns/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a campaign"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Delete associated campaign leads first
    db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id).delete()

    db.delete(campaign)
    db.commit()
    return {"message": "Campaign deleted successfully"}


# =============================================================================
# CAMPAIGN LEADS ENDPOINTS
# =============================================================================

@router.get("/crm/campaigns/{campaign_id}/leads")
async def get_campaign_leads(
    campaign_id: int,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all leads associated with a campaign"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign_id)

    if status:
        query = query.filter(CampaignLead.status == status)

    campaign_leads = query.all()

    return [{
        "id": cl.id,
        "campaign_id": cl.campaign_id,
        "lead_id": cl.lead_id,
        "lead_name": f"{cl.lead.first_name} {cl.lead.last_name or ''}".strip() if cl.lead else None,
        "lead_email": cl.lead.email if cl.lead else None,
        "lead_company": cl.lead.company_name if cl.lead else None,
        "status": cl.status,
        "responded_at": cl.responded_at.isoformat() if cl.responded_at else None,
        "converted_at": cl.converted_at.isoformat() if cl.converted_at else None,
        "notes": cl.notes,
        "created_at": cl.created_at.isoformat()
    } for cl in campaign_leads]


@router.post("/crm/campaigns/{campaign_id}/leads")
async def add_leads_to_campaign(
    campaign_id: int,
    data: CampaignLeadAdd,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add leads to a campaign"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    added = 0
    skipped = 0

    for lead_id in data.lead_ids:
        # Check if lead exists and belongs to same company
        lead = db.query(Lead).filter(
            Lead.id == lead_id,
            Lead.company_id == user.company_id
        ).first()

        if not lead:
            skipped += 1
            continue

        # Check if already in campaign
        existing = db.query(CampaignLead).filter(
            CampaignLead.campaign_id == campaign_id,
            CampaignLead.lead_id == lead_id
        ).first()

        if existing:
            skipped += 1
            continue

        campaign_lead = CampaignLead(
            campaign_id=campaign_id,
            lead_id=lead_id,
            status="sent"
        )
        db.add(campaign_lead)
        added += 1

    # Update campaign sent count
    campaign.sent_count = (campaign.sent_count or 0) + added

    db.commit()

    return {"message": f"Added {added} leads to campaign", "added": added, "skipped": skipped}


@router.put("/crm/campaigns/{campaign_id}/leads/{lead_id}")
async def update_campaign_lead(
    campaign_id: int,
    lead_id: int,
    data: CampaignLeadUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a campaign lead status"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign_lead = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.lead_id == lead_id
    ).first()

    if not campaign_lead:
        raise HTTPException(status_code=404, detail="Lead not found in campaign")

    old_status = campaign_lead.status
    campaign_lead.status = data.status

    if data.notes:
        campaign_lead.notes = data.notes

    # Update timestamps
    if data.status == "responded" and old_status == "sent":
        campaign_lead.responded_at = datetime.utcnow()
        campaign.response_count = (campaign.response_count or 0) + 1

    if data.status == "converted" and old_status != "converted":
        campaign_lead.converted_at = datetime.utcnow()
        if old_status == "sent":
            campaign.response_count = (campaign.response_count or 0) + 1

    db.commit()
    return {"message": "Campaign lead updated"}


@router.delete("/crm/campaigns/{campaign_id}/leads/{lead_id}")
async def remove_lead_from_campaign(
    campaign_id: int,
    lead_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a lead from a campaign"""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.company_id == user.company_id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign_lead = db.query(CampaignLead).filter(
        CampaignLead.campaign_id == campaign_id,
        CampaignLead.lead_id == lead_id
    ).first()

    if not campaign_lead:
        raise HTTPException(status_code=404, detail="Lead not found in campaign")

    db.delete(campaign_lead)

    # Update campaign sent count
    if campaign.sent_count and campaign.sent_count > 0:
        campaign.sent_count -= 1

    db.commit()
    return {"message": "Lead removed from campaign"}
