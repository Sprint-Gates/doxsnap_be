from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, extract
from typing import Optional, List
from datetime import datetime, date
from app.database import get_db
from app.models import NPSSurvey, User, Client, Site, WorkOrder, AddressBook
from app.api.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Valid survey types
VALID_SURVEY_TYPES = ["general", "post_service", "quarterly", "annual"]
VALID_FOLLOW_UP_STATUSES = ["pending", "in_progress", "completed", "not_required"]


# ============================================================================
# Pydantic Schemas
# ============================================================================

class NPSSurveyCreate(BaseModel):
    client_id: Optional[int] = None  # Legacy client reference
    address_book_id: Optional[int] = None  # New Address Book customer reference
    survey_date: date
    survey_type: Optional[str] = "general"
    score: int  # 0-10
    feedback: Optional[str] = None
    would_recommend_reason: Optional[str] = None
    work_order_id: Optional[int] = None
    site_id: Optional[int] = None
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None
    respondent_phone: Optional[str] = None
    respondent_role: Optional[str] = None


class NPSSurveyUpdate(BaseModel):
    survey_date: Optional[date] = None
    survey_type: Optional[str] = None
    score: Optional[int] = None
    feedback: Optional[str] = None
    would_recommend_reason: Optional[str] = None
    work_order_id: Optional[int] = None
    site_id: Optional[int] = None
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None
    respondent_phone: Optional[str] = None
    respondent_role: Optional[str] = None
    requires_follow_up: Optional[bool] = None
    follow_up_status: Optional[str] = None
    follow_up_notes: Optional[str] = None


class NPSSurveyResponse(BaseModel):
    id: int
    company_id: int
    client_id: Optional[int]
    address_book_id: Optional[int]
    client_name: Optional[str]
    survey_date: str
    survey_type: str
    score: int
    category: str
    feedback: Optional[str]
    would_recommend_reason: Optional[str]
    work_order_id: Optional[int]
    work_order_number: Optional[str]
    site_id: Optional[int]
    site_name: Optional[str]
    respondent_name: Optional[str]
    respondent_email: Optional[str]
    respondent_phone: Optional[str]
    respondent_role: Optional[str]
    requires_follow_up: bool
    follow_up_status: Optional[str]
    follow_up_notes: Optional[str]
    followed_up_by: Optional[int]
    followed_up_by_name: Optional[str]
    followed_up_at: Optional[str]
    collected_by: Optional[int]
    collected_by_name: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class NPSStatsResponse(BaseModel):
    total_surveys: int
    nps_score: float  # The actual NPS score (-100 to 100)
    promoters_count: int
    promoters_percentage: float
    passives_count: int
    passives_percentage: float
    detractors_count: int
    detractors_percentage: float
    average_score: float
    by_survey_type: dict
    by_client: List[dict]
    trend: List[dict]  # Monthly trend
    follow_up_pending: int


class ClientNPSResponse(BaseModel):
    client_id: int
    client_name: str
    total_surveys: int
    nps_score: float
    average_score: float
    latest_score: Optional[int]
    latest_survey_date: Optional[str]


# ============================================================================
# Helper Functions
# ============================================================================

def get_category_from_score(score: int) -> str:
    """Determine NPS category from score"""
    if score >= 9:
        return "promoter"
    elif score >= 7:
        return "passive"
    else:
        return "detractor"


def calculate_nps(promoters: int, detractors: int, total: int) -> float:
    """Calculate NPS score"""
    if total == 0:
        return 0.0
    promoter_pct = (promoters / total) * 100
    detractor_pct = (detractors / total) * 100
    return round(promoter_pct - detractor_pct, 1)


def survey_to_response(survey: NPSSurvey) -> NPSSurveyResponse:
    """Convert NPSSurvey to response"""
    # Get client name from address_book (preferred) or legacy client
    client_name = None
    if survey.address_book and survey.address_book.alpha_name:
        client_name = survey.address_book.alpha_name
    elif survey.client:
        client_name = survey.client.name

    return NPSSurveyResponse(
        id=survey.id,
        company_id=survey.company_id,
        client_id=survey.client_id,
        address_book_id=survey.address_book_id,
        client_name=client_name,
        survey_date=survey.survey_date.isoformat() if survey.survey_date else "",
        survey_type=survey.survey_type or "general",
        score=survey.score,
        category=survey.category,
        feedback=survey.feedback,
        would_recommend_reason=survey.would_recommend_reason,
        work_order_id=survey.work_order_id,
        work_order_number=survey.work_order.work_order_number if survey.work_order else None,
        site_id=survey.site_id,
        site_name=survey.site.name if survey.site else None,
        respondent_name=survey.respondent_name,
        respondent_email=survey.respondent_email,
        respondent_phone=survey.respondent_phone,
        respondent_role=survey.respondent_role,
        requires_follow_up=survey.requires_follow_up or False,
        follow_up_status=survey.follow_up_status,
        follow_up_notes=survey.follow_up_notes,
        followed_up_by=survey.followed_up_by,
        followed_up_by_name=survey.follow_up_user.name if survey.follow_up_user else None,
        followed_up_at=survey.followed_up_at.isoformat() if survey.followed_up_at else None,
        collected_by=survey.collected_by,
        collected_by_name=survey.collector.name if survey.collector else None,
        created_at=survey.created_at.isoformat() if survey.created_at else "",
        updated_at=survey.updated_at.isoformat() if survey.updated_at else ""
    )


# ============================================================================
# NPS Survey CRUD Endpoints
# ============================================================================

@router.get("/", response_model=List[NPSSurveyResponse])
async def get_nps_surveys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_id: Optional[int] = Query(None, description="Filter by client"),
    site_id: Optional[int] = Query(None, description="Filter by site"),
    survey_type: Optional[str] = Query(None, description="Filter by survey type"),
    category: Optional[str] = Query(None, description="Filter by category (promoter, passive, detractor)"),
    requires_follow_up: Optional[bool] = Query(None, description="Filter by follow-up required"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date")
):
    """Get all NPS surveys with optional filtering"""
    query = db.query(NPSSurvey).options(
        joinedload(NPSSurvey.client),
        joinedload(NPSSurvey.address_book),
        joinedload(NPSSurvey.site),
        joinedload(NPSSurvey.work_order),
        joinedload(NPSSurvey.collector),
        joinedload(NPSSurvey.follow_up_user)
    ).filter(NPSSurvey.company_id == current_user.company_id)

    if client_id:
        query = query.filter(NPSSurvey.client_id == client_id)

    if site_id:
        query = query.filter(NPSSurvey.site_id == site_id)

    if survey_type and survey_type in VALID_SURVEY_TYPES:
        query = query.filter(NPSSurvey.survey_type == survey_type)

    if category in ["promoter", "passive", "detractor"]:
        query = query.filter(NPSSurvey.category == category)

    if requires_follow_up is not None:
        query = query.filter(NPSSurvey.requires_follow_up == requires_follow_up)

    if date_from:
        query = query.filter(NPSSurvey.survey_date >= date_from)

    if date_to:
        query = query.filter(NPSSurvey.survey_date <= date_to)

    surveys = query.order_by(NPSSurvey.survey_date.desc()).all()
    return [survey_to_response(s) for s in surveys]


@router.get("/stats", response_model=NPSStatsResponse)
async def get_nps_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_id: Optional[int] = Query(None, description="Filter by client"),
    months: Optional[int] = Query(12, description="Number of months for trend")
):
    """Get NPS statistics and analytics"""
    base_query = db.query(NPSSurvey).filter(
        NPSSurvey.company_id == current_user.company_id
    )

    if client_id:
        base_query = base_query.filter(NPSSurvey.client_id == client_id)

    # Get all surveys
    surveys = base_query.all()
    total = len(surveys)

    if total == 0:
        return NPSStatsResponse(
            total_surveys=0,
            nps_score=0.0,
            promoters_count=0,
            promoters_percentage=0.0,
            passives_count=0,
            passives_percentage=0.0,
            detractors_count=0,
            detractors_percentage=0.0,
            average_score=0.0,
            by_survey_type={},
            by_client=[],
            trend=[],
            follow_up_pending=0
        )

    # Count by category
    promoters = sum(1 for s in surveys if s.category == "promoter")
    passives = sum(1 for s in surveys if s.category == "passive")
    detractors = sum(1 for s in surveys if s.category == "detractor")

    # Calculate NPS
    nps_score = calculate_nps(promoters, detractors, total)

    # Average score
    avg_score = sum(s.score for s in surveys) / total

    # By survey type
    by_type = {}
    for survey_type in VALID_SURVEY_TYPES:
        type_surveys = [s for s in surveys if s.survey_type == survey_type]
        if type_surveys:
            type_promoters = sum(1 for s in type_surveys if s.category == "promoter")
            type_detractors = sum(1 for s in type_surveys if s.category == "detractor")
            by_type[survey_type] = {
                "count": len(type_surveys),
                "nps": calculate_nps(type_promoters, type_detractors, len(type_surveys)),
                "avg_score": sum(s.score for s in type_surveys) / len(type_surveys)
            }

    # By client (top 10)
    client_stats = {}
    for survey in surveys:
        if survey.client_id not in client_stats:
            client_stats[survey.client_id] = {
                "client_id": survey.client_id,
                "client_name": survey.client.name if survey.client else "Unknown",
                "surveys": [],
                "promoters": 0,
                "detractors": 0
            }
        client_stats[survey.client_id]["surveys"].append(survey)
        if survey.category == "promoter":
            client_stats[survey.client_id]["promoters"] += 1
        elif survey.category == "detractor":
            client_stats[survey.client_id]["detractors"] += 1

    by_client = []
    for client_id, data in client_stats.items():
        client_total = len(data["surveys"])
        by_client.append({
            "client_id": data["client_id"],
            "client_name": data["client_name"],
            "total_surveys": client_total,
            "nps_score": calculate_nps(data["promoters"], data["detractors"], client_total),
            "avg_score": sum(s.score for s in data["surveys"]) / client_total
        })

    by_client.sort(key=lambda x: x["nps_score"], reverse=True)
    by_client = by_client[:10]

    # Monthly trend
    trend = []
    now = datetime.now()
    for i in range(months - 1, -1, -1):
        month = now.month - i
        year = now.year
        while month <= 0:
            month += 12
            year -= 1

        month_surveys = [
            s for s in surveys
            if s.survey_date.month == month and s.survey_date.year == year
        ]

        if month_surveys:
            month_promoters = sum(1 for s in month_surveys if s.category == "promoter")
            month_detractors = sum(1 for s in month_surveys if s.category == "detractor")
            trend.append({
                "month": month,
                "year": year,
                "month_name": date(year, month, 1).strftime("%b %Y"),
                "count": len(month_surveys),
                "nps_score": calculate_nps(month_promoters, month_detractors, len(month_surveys)),
                "avg_score": sum(s.score for s in month_surveys) / len(month_surveys)
            })
        else:
            trend.append({
                "month": month,
                "year": year,
                "month_name": date(year, month, 1).strftime("%b %Y"),
                "count": 0,
                "nps_score": 0,
                "avg_score": 0
            })

    # Follow-up pending count
    follow_up_pending = base_query.filter(
        NPSSurvey.requires_follow_up == True,
        NPSSurvey.follow_up_status.in_(["pending", "in_progress", None])
    ).count()

    return NPSStatsResponse(
        total_surveys=total,
        nps_score=nps_score,
        promoters_count=promoters,
        promoters_percentage=round((promoters / total) * 100, 1),
        passives_count=passives,
        passives_percentage=round((passives / total) * 100, 1),
        detractors_count=detractors,
        detractors_percentage=round((detractors / total) * 100, 1),
        average_score=round(avg_score, 2),
        by_survey_type=by_type,
        by_client=by_client,
        trend=trend,
        follow_up_pending=follow_up_pending
    )


@router.get("/clients", response_model=List[ClientNPSResponse])
async def get_client_nps_scores(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get NPS scores for all clients"""
    surveys = db.query(NPSSurvey).options(
        joinedload(NPSSurvey.client),
        joinedload(NPSSurvey.address_book)
    ).filter(
        NPSSurvey.company_id == current_user.company_id
    ).all()

    # Group by client (use address_book_id as primary key, fall back to client_id)
    client_data = {}
    for survey in surveys:
        # Use address_book_id as the key if available, otherwise client_id
        key = survey.address_book_id or survey.client_id
        if key not in client_data:
            # Get client name from address_book or legacy client
            client_name = "Unknown"
            if survey.address_book and survey.address_book.alpha_name:
                client_name = survey.address_book.alpha_name
            elif survey.client:
                client_name = survey.client.name

            client_data[key] = {
                "client_id": key,
                "client_name": client_name,
                "surveys": [],
                "promoters": 0,
                "detractors": 0
            }
        client_data[key]["surveys"].append(survey)
        if survey.category == "promoter":
            client_data[key]["promoters"] += 1
        elif survey.category == "detractor":
            client_data[key]["detractors"] += 1

    results = []
    for client_id, data in client_data.items():
        total = len(data["surveys"])
        latest = max(data["surveys"], key=lambda s: s.survey_date)
        results.append(ClientNPSResponse(
            client_id=data["client_id"],
            client_name=data["client_name"],
            total_surveys=total,
            nps_score=calculate_nps(data["promoters"], data["detractors"], total),
            average_score=round(sum(s.score for s in data["surveys"]) / total, 2),
            latest_score=latest.score,
            latest_survey_date=latest.survey_date.isoformat()
        ))

    results.sort(key=lambda x: x.nps_score, reverse=True)
    return results


@router.get("/{survey_id}", response_model=NPSSurveyResponse)
async def get_nps_survey(
    survey_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a single NPS survey by ID"""
    survey = db.query(NPSSurvey).options(
        joinedload(NPSSurvey.client),
        joinedload(NPSSurvey.address_book),
        joinedload(NPSSurvey.site),
        joinedload(NPSSurvey.work_order),
        joinedload(NPSSurvey.collector),
        joinedload(NPSSurvey.follow_up_user)
    ).filter(
        NPSSurvey.id == survey_id,
        NPSSurvey.company_id == current_user.company_id
    ).first()

    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")

    return survey_to_response(survey)


@router.post("/", response_model=NPSSurveyResponse, status_code=status.HTTP_201_CREATED)
async def create_nps_survey(
    data: NPSSurveyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new NPS survey"""
    # Validate score
    if data.score < 0 or data.score > 10:
        raise HTTPException(status_code=400, detail="Score must be between 0 and 10")

    # Validate survey type
    if data.survey_type and data.survey_type not in VALID_SURVEY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid survey type. Must be one of: {', '.join(VALID_SURVEY_TYPES)}"
        )

    # Verify client exists (via address_book_id - preferred, or legacy client_id)
    if not data.client_id and not data.address_book_id:
        raise HTTPException(status_code=400, detail="Either client_id or address_book_id is required")

    client_id = None
    address_book_id = None

    # Prioritize address_book_id lookup (new system)
    if data.address_book_id:
        ab_entry = db.query(AddressBook).filter(
            AddressBook.id == data.address_book_id,
            AddressBook.company_id == current_user.company_id,
            AddressBook.search_type == 'C'  # Must be a Customer
        ).first()
        if not ab_entry:
            raise HTTPException(status_code=404, detail="Address Book customer not found")
        address_book_id = data.address_book_id
    elif data.client_id:
        # Legacy client_id lookup - only if address_book_id not provided
        client = db.query(Client).filter(
            Client.id == data.client_id,
            Client.company_id == current_user.company_id
        ).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        client_id = data.client_id

    # Determine category from score
    category = get_category_from_score(data.score)

    # Determine if follow-up is required (detractors always need follow-up)
    requires_follow_up = category == "detractor"

    survey = NPSSurvey(
        company_id=current_user.company_id,
        client_id=client_id,
        address_book_id=address_book_id,
        survey_date=data.survey_date,
        survey_type=data.survey_type or "general",
        score=data.score,
        category=category,
        feedback=data.feedback,
        would_recommend_reason=data.would_recommend_reason,
        work_order_id=data.work_order_id,
        site_id=data.site_id,
        respondent_name=data.respondent_name,
        respondent_email=data.respondent_email,
        respondent_phone=data.respondent_phone,
        respondent_role=data.respondent_role,
        requires_follow_up=requires_follow_up,
        follow_up_status="pending" if requires_follow_up else None,
        collected_by=current_user.id
    )

    db.add(survey)
    db.commit()
    db.refresh(survey)

    # Reload with relationships
    survey = db.query(NPSSurvey).options(
        joinedload(NPSSurvey.client),
        joinedload(NPSSurvey.address_book),
        joinedload(NPSSurvey.site),
        joinedload(NPSSurvey.work_order),
        joinedload(NPSSurvey.collector),
        joinedload(NPSSurvey.follow_up_user)
    ).filter(NPSSurvey.id == survey.id).first()

    logger.info(f"Created NPS survey {survey.id} for address_book_id {data.address_book_id} with score {data.score}")
    return survey_to_response(survey)


@router.put("/{survey_id}", response_model=NPSSurveyResponse)
async def update_nps_survey(
    survey_id: int,
    data: NPSSurveyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing NPS survey"""
    survey = db.query(NPSSurvey).filter(
        NPSSurvey.id == survey_id,
        NPSSurvey.company_id == current_user.company_id
    ).first()

    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")

    # Validate score if provided
    if data.score is not None:
        if data.score < 0 or data.score > 10:
            raise HTTPException(status_code=400, detail="Score must be between 0 and 10")
        # Update category when score changes
        survey.category = get_category_from_score(data.score)

    # Validate survey type if provided
    if data.survey_type and data.survey_type not in VALID_SURVEY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid survey type. Must be one of: {', '.join(VALID_SURVEY_TYPES)}"
        )

    # Validate follow-up status if provided
    if data.follow_up_status and data.follow_up_status not in VALID_FOLLOW_UP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid follow-up status. Must be one of: {', '.join(VALID_FOLLOW_UP_STATUSES)}"
        )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(survey, field, value)

    db.commit()
    db.refresh(survey)

    # Reload with relationships
    survey = db.query(NPSSurvey).options(
        joinedload(NPSSurvey.client),
        joinedload(NPSSurvey.address_book),
        joinedload(NPSSurvey.site),
        joinedload(NPSSurvey.work_order),
        joinedload(NPSSurvey.collector),
        joinedload(NPSSurvey.follow_up_user)
    ).filter(NPSSurvey.id == survey.id).first()

    logger.info(f"Updated NPS survey {survey_id}")
    return survey_to_response(survey)


@router.post("/{survey_id}/follow-up", response_model=NPSSurveyResponse)
async def update_follow_up(
    survey_id: int,
    follow_up_status: str = Query(..., description="Follow-up status"),
    follow_up_notes: Optional[str] = Query(None, description="Follow-up notes"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update follow-up status for a survey"""
    survey = db.query(NPSSurvey).filter(
        NPSSurvey.id == survey_id,
        NPSSurvey.company_id == current_user.company_id
    ).first()

    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")

    if follow_up_status not in VALID_FOLLOW_UP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(VALID_FOLLOW_UP_STATUSES)}"
        )

    survey.follow_up_status = follow_up_status
    if follow_up_notes:
        survey.follow_up_notes = follow_up_notes
    survey.followed_up_by = current_user.id
    survey.followed_up_at = datetime.utcnow()

    db.commit()
    db.refresh(survey)

    # Reload with relationships
    survey = db.query(NPSSurvey).options(
        joinedload(NPSSurvey.client),
        joinedload(NPSSurvey.address_book),
        joinedload(NPSSurvey.site),
        joinedload(NPSSurvey.work_order),
        joinedload(NPSSurvey.collector),
        joinedload(NPSSurvey.follow_up_user)
    ).filter(NPSSurvey.id == survey.id).first()

    logger.info(f"Updated follow-up for NPS survey {survey_id} to {follow_up_status}")
    return survey_to_response(survey)


@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nps_survey(
    survey_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an NPS survey"""
    survey = db.query(NPSSurvey).filter(
        NPSSurvey.id == survey_id,
        NPSSurvey.company_id == current_user.company_id
    ).first()

    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")

    db.delete(survey)
    db.commit()

    logger.info(f"Deleted NPS survey {survey_id}")
    return None
