"""
CRM Opportunities API
Handles opportunity/deal management and pipeline tracking
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_
from typing import Optional, List
from datetime import datetime, date
from app.database import get_db
from app.models import Opportunity, PipelineStage, Client, Lead, Contract, User
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

class PipelineStageCreate(BaseModel):
    name: str
    code: Optional[str] = None
    color: Optional[str] = "#6366f1"
    probability: Optional[int] = 0
    is_won: Optional[bool] = False
    is_lost: Optional[bool] = False
    sort_order: Optional[int] = 0


class PipelineStageUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    color: Optional[str] = None
    probability: Optional[int] = None
    is_won: Optional[bool] = None
    is_lost: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class OpportunityCreate(BaseModel):
    name: str
    description: Optional[str] = None
    client_id: Optional[int] = None
    lead_id: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    stage_id: Optional[int] = None
    probability: Optional[int] = None
    amount: Optional[float] = None
    currency: Optional[str] = "USD"
    expected_close_date: Optional[date] = None
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    next_step: Optional[str] = None


class OpportunityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    client_id: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    stage_id: Optional[int] = None
    probability: Optional[int] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    expected_close_date: Optional[date] = None
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    next_step: Optional[str] = None
    status: Optional[str] = None
    lost_reason: Optional[str] = None
    competitor: Optional[str] = None


class OpportunityMoveStage(BaseModel):
    stage_id: int


class OpportunityWinLose(BaseModel):
    status: str  # "won" or "lost"
    lost_reason: Optional[str] = None
    competitor: Optional[str] = None


# =============================================================================
# PIPELINE STAGES ENDPOINTS
# =============================================================================

@router.get("/crm/pipeline-stages")
async def get_pipeline_stages(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all pipeline stages for the company"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    query = db.query(PipelineStage).filter(PipelineStage.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(PipelineStage.is_active == True)

    stages = query.order_by(PipelineStage.sort_order, PipelineStage.name).all()

    # Get opportunity counts per stage
    stage_counts = db.query(
        Opportunity.stage_id,
        func.count(Opportunity.id),
        func.sum(Opportunity.amount)
    ).filter(
        Opportunity.company_id == user.company_id,
        Opportunity.status == "open"
    ).group_by(Opportunity.stage_id).all()

    count_map = {s: {"count": c, "value": float(v or 0)} for s, c, v in stage_counts}

    return [{
        "id": s.id,
        "name": s.name,
        "code": s.code,
        "color": s.color,
        "probability": s.probability,
        "is_won": s.is_won,
        "is_lost": s.is_lost,
        "is_active": s.is_active,
        "sort_order": s.sort_order,
        "opportunity_count": count_map.get(s.id, {}).get("count", 0),
        "opportunity_value": count_map.get(s.id, {}).get("value", 0)
    } for s in stages]


@router.post("/crm/pipeline-stages")
async def create_pipeline_stage(
    data: PipelineStageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new pipeline stage"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    stage = PipelineStage(
        company_id=user.company_id,
        name=data.name,
        code=data.code,
        color=data.color or "#6366f1",
        probability=data.probability or 0,
        is_won=data.is_won or False,
        is_lost=data.is_lost or False,
        sort_order=data.sort_order or 0
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)

    return {"id": stage.id, "name": stage.name, "message": "Pipeline stage created"}


@router.put("/crm/pipeline-stages/{stage_id}")
async def update_pipeline_stage(
    stage_id: int,
    data: PipelineStageUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a pipeline stage"""
    stage = db.query(PipelineStage).filter(
        PipelineStage.id == stage_id,
        PipelineStage.company_id == user.company_id
    ).first()

    if not stage:
        raise HTTPException(status_code=404, detail="Pipeline stage not found")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(stage, field, value)

    db.commit()
    return {"message": "Pipeline stage updated"}


@router.put("/crm/pipeline-stages/reorder")
async def reorder_pipeline_stages(
    stage_orders: List[dict],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reorder pipeline stages"""
    for item in stage_orders:
        stage = db.query(PipelineStage).filter(
            PipelineStage.id == item["id"],
            PipelineStage.company_id == user.company_id
        ).first()
        if stage:
            stage.sort_order = item["sort_order"]

    db.commit()
    return {"message": "Stages reordered"}


@router.delete("/crm/pipeline-stages/{stage_id}")
async def delete_pipeline_stage(
    stage_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a pipeline stage (soft delete)"""
    stage = db.query(PipelineStage).filter(
        PipelineStage.id == stage_id,
        PipelineStage.company_id == user.company_id
    ).first()

    if not stage:
        raise HTTPException(status_code=404, detail="Pipeline stage not found")

    # Check if any opportunities use this stage
    opp_count = db.query(Opportunity).filter(
        Opportunity.stage_id == stage_id,
        Opportunity.status == "open"
    ).count()

    if opp_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete stage with {opp_count} active opportunities")

    stage.is_active = False
    db.commit()
    return {"message": "Pipeline stage deleted"}


# =============================================================================
# OPPORTUNITIES ENDPOINTS
# =============================================================================

def opportunity_to_response(opp: Opportunity, db: Session) -> dict:
    """Convert Opportunity model to response dict"""
    return {
        "id": opp.id,
        "name": opp.name,
        "description": opp.description,
        "client_id": opp.client_id,
        "client_name": opp.client.name if opp.client else None,
        "lead_id": opp.lead_id,
        "contact_name": opp.contact_name,
        "contact_email": opp.contact_email,
        "contact_phone": opp.contact_phone,
        "stage_id": opp.stage_id,
        "stage_name": opp.stage.name if opp.stage else None,
        "stage_color": opp.stage.color if opp.stage else None,
        "probability": opp.probability,
        "amount": float(opp.amount) if opp.amount else None,
        "currency": opp.currency,
        "weighted_amount": float(opp.amount * opp.probability / 100) if opp.amount and opp.probability else None,
        "expected_close_date": opp.expected_close_date.isoformat() if opp.expected_close_date else None,
        "actual_close_date": opp.actual_close_date.isoformat() if opp.actual_close_date else None,
        "status": opp.status,
        "lost_reason": opp.lost_reason,
        "competitor": opp.competitor,
        "assigned_to": opp.assigned_to,
        "assignee_name": opp.assignee.name if opp.assignee else None,
        "notes": opp.notes,
        "next_step": opp.next_step,
        "converted_to_contract_id": opp.converted_to_contract_id,
        "created_by": opp.created_by,
        "creator_name": opp.creator.name if opp.creator else None,
        "created_at": opp.created_at.isoformat(),
        "updated_at": opp.updated_at.isoformat() if opp.updated_at else None
    }


@router.get("/crm/opportunities")
async def get_opportunities(
    status: Optional[str] = None,
    stage_id: Optional[int] = None,
    client_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all opportunities for the company"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    query = db.query(Opportunity).filter(Opportunity.company_id == user.company_id)

    if status:
        query = query.filter(Opportunity.status == status)
    else:
        # Default to open opportunities
        query = query.filter(Opportunity.status == "open")

    if stage_id:
        query = query.filter(Opportunity.stage_id == stage_id)

    if client_id:
        query = query.filter(Opportunity.client_id == client_id)

    if assigned_to:
        query = query.filter(Opportunity.assigned_to == assigned_to)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Opportunity.name.ilike(search_term),
                Opportunity.contact_name.ilike(search_term),
                Opportunity.contact_email.ilike(search_term)
            )
        )

    opportunities = query.order_by(Opportunity.created_at.desc()).all()

    return [opportunity_to_response(opp, db) for opp in opportunities]


@router.get("/crm/opportunities/pipeline")
async def get_pipeline_view(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get opportunities organized by pipeline stage (for Kanban view)"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    # Get all active stages
    stages = db.query(PipelineStage).filter(
        PipelineStage.company_id == user.company_id,
        PipelineStage.is_active == True
    ).order_by(PipelineStage.sort_order).all()

    # Get all open opportunities
    opportunities = db.query(Opportunity).filter(
        Opportunity.company_id == user.company_id,
        Opportunity.status == "open"
    ).all()

    # Organize by stage
    pipeline = []
    for stage in stages:
        stage_opps = [opp for opp in opportunities if opp.stage_id == stage.id]
        pipeline.append({
            "stage": {
                "id": stage.id,
                "name": stage.name,
                "color": stage.color,
                "probability": stage.probability,
                "is_won": stage.is_won,
                "is_lost": stage.is_lost
            },
            "opportunities": [opportunity_to_response(opp, db) for opp in stage_opps],
            "total_value": sum(float(opp.amount or 0) for opp in stage_opps),
            "count": len(stage_opps)
        })

    return pipeline


@router.get("/crm/opportunities/stats")
async def get_opportunity_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get opportunity statistics"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    # Total pipeline value (open opportunities)
    total_value = db.query(func.sum(Opportunity.amount)).filter(
        Opportunity.company_id == user.company_id,
        Opportunity.status == "open"
    ).scalar() or 0

    # Weighted pipeline value
    weighted_value = db.query(
        func.sum(Opportunity.amount * Opportunity.probability / 100)
    ).filter(
        Opportunity.company_id == user.company_id,
        Opportunity.status == "open"
    ).scalar() or 0

    # Won this month
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    won_this_month = db.query(func.sum(Opportunity.amount)).filter(
        Opportunity.company_id == user.company_id,
        Opportunity.status == "won",
        Opportunity.actual_close_date >= start_of_month.date()
    ).scalar() or 0

    # Count by status
    status_counts = db.query(
        Opportunity.status,
        func.count(Opportunity.id)
    ).filter(
        Opportunity.company_id == user.company_id
    ).group_by(Opportunity.status).all()

    # Win rate
    total_closed = sum(c for s, c in status_counts if s in ["won", "lost"])
    won_count = next((c for s, c in status_counts if s == "won"), 0)
    win_rate = (won_count / total_closed * 100) if total_closed > 0 else 0

    # Closing this month
    end_of_month = (start_of_month.replace(month=start_of_month.month % 12 + 1, day=1)
                   if start_of_month.month < 12
                   else start_of_month.replace(year=start_of_month.year + 1, month=1, day=1))
    closing_this_month = db.query(func.sum(Opportunity.amount)).filter(
        Opportunity.company_id == user.company_id,
        Opportunity.status == "open",
        Opportunity.expected_close_date >= start_of_month.date(),
        Opportunity.expected_close_date < end_of_month.date()
    ).scalar() or 0

    return {
        "total_pipeline_value": float(total_value),
        "weighted_pipeline_value": float(weighted_value),
        "won_this_month": float(won_this_month),
        "closing_this_month": float(closing_this_month),
        "by_status": {s: c for s, c in status_counts},
        "win_rate": round(win_rate, 1),
        "open_count": next((c for s, c in status_counts if s == "open"), 0)
    }


@router.get("/crm/opportunities/{opp_id}")
async def get_opportunity(
    opp_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific opportunity"""
    opp = db.query(Opportunity).filter(
        Opportunity.id == opp_id,
        Opportunity.company_id == user.company_id
    ).first()

    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    return opportunity_to_response(opp, db)


@router.post("/crm/opportunities")
async def create_opportunity(
    data: OpportunityCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new opportunity"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    # Get first stage if not specified
    stage_id = data.stage_id
    if not stage_id:
        first_stage = db.query(PipelineStage).filter(
            PipelineStage.company_id == user.company_id,
            PipelineStage.is_active == True
        ).order_by(PipelineStage.sort_order).first()
        stage_id = first_stage.id if first_stage else None

    # Get probability from stage if not specified
    probability = data.probability
    if probability is None and stage_id:
        stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
        probability = stage.probability if stage else 0

    opp = Opportunity(
        company_id=user.company_id,
        name=data.name,
        description=data.description,
        client_id=data.client_id,
        lead_id=data.lead_id,
        contact_name=data.contact_name,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        stage_id=stage_id,
        probability=probability or 0,
        amount=data.amount,
        currency=data.currency or "USD",
        expected_close_date=data.expected_close_date,
        assigned_to=data.assigned_to,
        notes=data.notes,
        next_step=data.next_step,
        created_by=user.id
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    return {"id": opp.id, "message": "Opportunity created successfully"}


@router.put("/crm/opportunities/{opp_id}")
async def update_opportunity(
    opp_id: int,
    data: OpportunityUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an opportunity"""
    opp = db.query(Opportunity).filter(
        Opportunity.id == opp_id,
        Opportunity.company_id == user.company_id
    ).first()

    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    for field, value in data.dict(exclude_unset=True).items():
        setattr(opp, field, value)

    # Update probability from stage if stage changed
    if data.stage_id and data.probability is None:
        stage = db.query(PipelineStage).filter(PipelineStage.id == data.stage_id).first()
        if stage:
            opp.probability = stage.probability

    db.commit()
    return {"message": "Opportunity updated successfully"}


@router.put("/crm/opportunities/{opp_id}/stage")
async def move_opportunity_stage(
    opp_id: int,
    data: OpportunityMoveStage,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Move opportunity to a different pipeline stage"""
    opp = db.query(Opportunity).filter(
        Opportunity.id == opp_id,
        Opportunity.company_id == user.company_id
    ).first()

    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if opp.status != "open":
        raise HTTPException(status_code=400, detail="Cannot move closed opportunity")

    stage = db.query(PipelineStage).filter(
        PipelineStage.id == data.stage_id,
        PipelineStage.company_id == user.company_id
    ).first()

    if not stage:
        raise HTTPException(status_code=404, detail="Pipeline stage not found")

    opp.stage_id = stage.id
    opp.probability = stage.probability

    # Auto-close if moved to won/lost stage
    if stage.is_won:
        opp.status = "won"
        opp.actual_close_date = date.today()
    elif stage.is_lost:
        opp.status = "lost"
        opp.actual_close_date = date.today()

    db.commit()
    return {"message": "Opportunity moved to stage", "status": opp.status}


@router.post("/crm/opportunities/{opp_id}/close")
async def close_opportunity(
    opp_id: int,
    data: OpportunityWinLose,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Close an opportunity as won or lost"""
    opp = db.query(Opportunity).filter(
        Opportunity.id == opp_id,
        Opportunity.company_id == user.company_id
    ).first()

    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    if data.status not in ["won", "lost"]:
        raise HTTPException(status_code=400, detail="Status must be 'won' or 'lost'")

    opp.status = data.status
    opp.actual_close_date = date.today()

    if data.status == "lost":
        opp.lost_reason = data.lost_reason
        opp.competitor = data.competitor

    # Move to appropriate stage
    if data.status == "won":
        won_stage = db.query(PipelineStage).filter(
            PipelineStage.company_id == user.company_id,
            PipelineStage.is_won == True
        ).first()
        if won_stage:
            opp.stage_id = won_stage.id
            opp.probability = 100
    else:
        lost_stage = db.query(PipelineStage).filter(
            PipelineStage.company_id == user.company_id,
            PipelineStage.is_lost == True
        ).first()
        if lost_stage:
            opp.stage_id = lost_stage.id
            opp.probability = 0

    db.commit()
    return {"message": f"Opportunity marked as {data.status}"}


@router.delete("/crm/opportunities/{opp_id}")
async def delete_opportunity(
    opp_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an opportunity"""
    opp = db.query(Opportunity).filter(
        Opportunity.id == opp_id,
        Opportunity.company_id == user.company_id
    ).first()

    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    db.delete(opp)
    db.commit()
    return {"message": "Opportunity deleted successfully"}
