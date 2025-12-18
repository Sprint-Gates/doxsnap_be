from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import Optional, List
from decimal import Decimal
from datetime import datetime, date
from app.database import get_db
from app.models import TechnicianEvaluation, User, Technician
from app.api.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Valid evaluation periods
VALID_PERIODS = ["monthly", "quarterly", "semi-annual", "annual"]
VALID_STATUSES = ["draft", "submitted", "acknowledged", "finalized"]
VALID_RATINGS = ["excellent", "good", "satisfactory", "needs_improvement", "poor"]


# ============================================================================
# Pydantic Schemas
# ============================================================================

class TechnicianEvaluationCreate(BaseModel):
    technician_id: int
    evaluation_period: str
    period_start: date
    period_end: date
    attendance_score: Optional[int] = None
    quality_score: Optional[int] = None
    productivity_score: Optional[int] = None
    teamwork_score: Optional[int] = None
    safety_score: Optional[int] = None
    communication_score: Optional[int] = None
    initiative_score: Optional[int] = None
    technical_skills_score: Optional[int] = None
    strengths: Optional[str] = None
    areas_for_improvement: Optional[str] = None
    goals_for_next_period: Optional[str] = None
    evaluator_comments: Optional[str] = None


class TechnicianEvaluationUpdate(BaseModel):
    evaluation_period: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    attendance_score: Optional[int] = None
    quality_score: Optional[int] = None
    productivity_score: Optional[int] = None
    teamwork_score: Optional[int] = None
    safety_score: Optional[int] = None
    communication_score: Optional[int] = None
    initiative_score: Optional[int] = None
    technical_skills_score: Optional[int] = None
    strengths: Optional[str] = None
    areas_for_improvement: Optional[str] = None
    goals_for_next_period: Optional[str] = None
    evaluator_comments: Optional[str] = None
    technician_comments: Optional[str] = None
    status: Optional[str] = None


class TechnicianEvaluationResponse(BaseModel):
    id: int
    company_id: int
    technician_id: int
    technician_name: Optional[str]
    technician_employee_id: Optional[str]
    technician_specialization: Optional[str]
    evaluation_period: str
    period_start: str
    period_end: str
    attendance_score: Optional[int]
    quality_score: Optional[int]
    productivity_score: Optional[int]
    teamwork_score: Optional[int]
    safety_score: Optional[int]
    communication_score: Optional[int]
    initiative_score: Optional[int]
    technical_skills_score: Optional[int]
    overall_score: Optional[float]
    overall_rating: Optional[str]
    strengths: Optional[str]
    areas_for_improvement: Optional[str]
    goals_for_next_period: Optional[str]
    evaluator_comments: Optional[str]
    technician_comments: Optional[str]
    status: str
    evaluated_by: int
    evaluated_by_name: Optional[str]
    evaluated_at: Optional[str]
    acknowledged_by_technician: bool
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class EvaluationStatsResponse(BaseModel):
    total_evaluations: int
    draft_count: int
    submitted_count: int
    acknowledged_count: int
    finalized_count: int
    avg_overall_score: Optional[float]
    technicians_evaluated: int
    by_period: dict
    by_rating: dict


# ============================================================================
# Helper Functions
# ============================================================================

def calculate_overall_score(evaluation: TechnicianEvaluation) -> tuple:
    """Calculate overall score and rating from individual scores"""
    scores = [
        evaluation.attendance_score,
        evaluation.quality_score,
        evaluation.productivity_score,
        evaluation.teamwork_score,
        evaluation.safety_score,
        evaluation.communication_score,
        evaluation.initiative_score,
        evaluation.technical_skills_score
    ]

    valid_scores = [s for s in scores if s is not None]

    if not valid_scores:
        return None, None

    avg_score = sum(valid_scores) / len(valid_scores)

    # Determine rating based on average score
    if avg_score >= 4.5:
        rating = "excellent"
    elif avg_score >= 3.5:
        rating = "good"
    elif avg_score >= 2.5:
        rating = "satisfactory"
    elif avg_score >= 1.5:
        rating = "needs_improvement"
    else:
        rating = "poor"

    return round(avg_score, 2), rating


def evaluation_to_response(evaluation: TechnicianEvaluation) -> TechnicianEvaluationResponse:
    """Convert TechnicianEvaluation to response"""
    return TechnicianEvaluationResponse(
        id=evaluation.id,
        company_id=evaluation.company_id,
        technician_id=evaluation.technician_id,
        technician_name=evaluation.technician.name if evaluation.technician else None,
        technician_employee_id=evaluation.technician.employee_id if evaluation.technician else None,
        technician_specialization=evaluation.technician.specialization if evaluation.technician else None,
        evaluation_period=evaluation.evaluation_period,
        period_start=evaluation.period_start.isoformat() if evaluation.period_start else "",
        period_end=evaluation.period_end.isoformat() if evaluation.period_end else "",
        attendance_score=evaluation.attendance_score,
        quality_score=evaluation.quality_score,
        productivity_score=evaluation.productivity_score,
        teamwork_score=evaluation.teamwork_score,
        safety_score=evaluation.safety_score,
        communication_score=evaluation.communication_score,
        initiative_score=evaluation.initiative_score,
        technical_skills_score=evaluation.technical_skills_score,
        overall_score=float(evaluation.overall_score) if evaluation.overall_score else None,
        overall_rating=evaluation.overall_rating,
        strengths=evaluation.strengths,
        areas_for_improvement=evaluation.areas_for_improvement,
        goals_for_next_period=evaluation.goals_for_next_period,
        evaluator_comments=evaluation.evaluator_comments,
        technician_comments=evaluation.technician_comments,
        status=evaluation.status,
        evaluated_by=evaluation.evaluated_by,
        evaluated_by_name=evaluation.evaluator.name if evaluation.evaluator else None,
        evaluated_at=evaluation.evaluated_at.isoformat() if evaluation.evaluated_at else None,
        acknowledged_by_technician=evaluation.acknowledged_by_technician or False,
        acknowledged_at=evaluation.acknowledged_at.isoformat() if evaluation.acknowledged_at else None,
        created_at=evaluation.created_at.isoformat() if evaluation.created_at else "",
        updated_at=evaluation.updated_at.isoformat() if evaluation.updated_at else ""
    )


# ============================================================================
# Technician Evaluation CRUD Endpoints
# ============================================================================

@router.get("/", response_model=List[TechnicianEvaluationResponse])
async def get_technician_evaluations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    technician_id: Optional[int] = Query(None, description="Filter by technician"),
    evaluation_period: Optional[str] = Query(None, description="Filter by evaluation period"),
    status: Optional[str] = Query(None, description="Filter by status"),
    overall_rating: Optional[str] = Query(None, description="Filter by overall rating"),
    search: Optional[str] = Query(None, description="Search by technician name")
):
    """Get all technician evaluations with optional filtering"""
    query = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(TechnicianEvaluation.company_id == current_user.company_id)

    if technician_id:
        query = query.filter(TechnicianEvaluation.technician_id == technician_id)

    if evaluation_period and evaluation_period in VALID_PERIODS:
        query = query.filter(TechnicianEvaluation.evaluation_period == evaluation_period)

    if status and status in VALID_STATUSES:
        query = query.filter(TechnicianEvaluation.status == status)

    if overall_rating and overall_rating in VALID_RATINGS:
        query = query.filter(TechnicianEvaluation.overall_rating == overall_rating)

    if search:
        query = query.join(Technician).filter(
            Technician.name.ilike(f"%{search}%")
        )

    evaluations = query.order_by(TechnicianEvaluation.created_at.desc()).all()
    return [evaluation_to_response(e) for e in evaluations]


@router.get("/stats", response_model=EvaluationStatsResponse)
async def get_evaluation_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get evaluation statistics for the company"""
    base_query = db.query(TechnicianEvaluation).filter(
        TechnicianEvaluation.company_id == current_user.company_id
    )

    total = base_query.count()
    draft = base_query.filter(TechnicianEvaluation.status == "draft").count()
    submitted = base_query.filter(TechnicianEvaluation.status == "submitted").count()
    acknowledged = base_query.filter(TechnicianEvaluation.status == "acknowledged").count()
    finalized = base_query.filter(TechnicianEvaluation.status == "finalized").count()

    # Average overall score
    avg_score = db.query(func.avg(TechnicianEvaluation.overall_score)).filter(
        TechnicianEvaluation.company_id == current_user.company_id,
        TechnicianEvaluation.overall_score.isnot(None)
    ).scalar()

    # Count distinct technicians evaluated
    technicians_evaluated = db.query(func.count(func.distinct(TechnicianEvaluation.technician_id))).filter(
        TechnicianEvaluation.company_id == current_user.company_id
    ).scalar()

    # Count by period
    by_period = {}
    for period in VALID_PERIODS:
        count = base_query.filter(TechnicianEvaluation.evaluation_period == period).count()
        by_period[period] = count

    # Count by rating
    by_rating = {}
    for rating in VALID_RATINGS:
        count = base_query.filter(TechnicianEvaluation.overall_rating == rating).count()
        by_rating[rating] = count

    return EvaluationStatsResponse(
        total_evaluations=total,
        draft_count=draft,
        submitted_count=submitted,
        acknowledged_count=acknowledged,
        finalized_count=finalized,
        avg_overall_score=round(float(avg_score), 2) if avg_score else None,
        technicians_evaluated=technicians_evaluated or 0,
        by_period=by_period,
        by_rating=by_rating
    )


@router.get("/{evaluation_id}", response_model=TechnicianEvaluationResponse)
async def get_technician_evaluation(
    evaluation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a single technician evaluation by ID"""
    evaluation = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(
        TechnicianEvaluation.id == evaluation_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).first()

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    return evaluation_to_response(evaluation)


@router.post("/", response_model=TechnicianEvaluationResponse, status_code=status.HTTP_201_CREATED)
async def create_technician_evaluation(
    data: TechnicianEvaluationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new technician evaluation"""
    # Validate evaluation period
    if data.evaluation_period not in VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid evaluation period. Must be one of: {', '.join(VALID_PERIODS)}"
        )

    # Validate scores are between 1-5
    score_fields = [
        'attendance_score', 'quality_score', 'productivity_score',
        'teamwork_score', 'safety_score', 'communication_score',
        'initiative_score', 'technical_skills_score'
    ]
    for field in score_fields:
        value = getattr(data, field)
        if value is not None and (value < 1 or value > 5):
            raise HTTPException(
                status_code=400,
                detail=f"{field} must be between 1 and 5"
            )

    # Verify technician exists and belongs to company
    technician = db.query(Technician).filter(
        Technician.id == data.technician_id,
        Technician.company_id == current_user.company_id
    ).first()
    if not technician:
        raise HTTPException(status_code=404, detail="Technician not found")

    # Validate period dates
    if data.period_end < data.period_start:
        raise HTTPException(status_code=400, detail="Period end date must be after start date")

    # Create evaluation
    evaluation = TechnicianEvaluation(
        company_id=current_user.company_id,
        technician_id=data.technician_id,
        evaluation_period=data.evaluation_period,
        period_start=data.period_start,
        period_end=data.period_end,
        attendance_score=data.attendance_score,
        quality_score=data.quality_score,
        productivity_score=data.productivity_score,
        teamwork_score=data.teamwork_score,
        safety_score=data.safety_score,
        communication_score=data.communication_score,
        initiative_score=data.initiative_score,
        technical_skills_score=data.technical_skills_score,
        strengths=data.strengths,
        areas_for_improvement=data.areas_for_improvement,
        goals_for_next_period=data.goals_for_next_period,
        evaluator_comments=data.evaluator_comments,
        evaluated_by=current_user.id,
        status="draft"
    )

    # Calculate overall score
    overall_score, overall_rating = calculate_overall_score(evaluation)
    evaluation.overall_score = overall_score
    evaluation.overall_rating = overall_rating

    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    # Reload with relationships
    evaluation = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(TechnicianEvaluation.id == evaluation.id).first()

    logger.info(f"Created technician evaluation {evaluation.id} for technician {data.technician_id}")
    return evaluation_to_response(evaluation)


@router.put("/{evaluation_id}", response_model=TechnicianEvaluationResponse)
async def update_technician_evaluation(
    evaluation_id: int,
    data: TechnicianEvaluationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing technician evaluation"""
    evaluation = db.query(TechnicianEvaluation).filter(
        TechnicianEvaluation.id == evaluation_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).first()

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    # Don't allow updates to finalized evaluations (except technician_comments)
    if evaluation.status == "finalized":
        if data.technician_comments is not None:
            evaluation.technician_comments = data.technician_comments
            db.commit()
            db.refresh(evaluation)
            evaluation = db.query(TechnicianEvaluation).options(
                joinedload(TechnicianEvaluation.technician),
                joinedload(TechnicianEvaluation.evaluator)
            ).filter(TechnicianEvaluation.id == evaluation.id).first()
            return evaluation_to_response(evaluation)
        raise HTTPException(status_code=400, detail="Cannot update finalized evaluation")

    # Validate status if provided
    if data.status is not None and data.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    # Validate scores
    score_fields = [
        'attendance_score', 'quality_score', 'productivity_score',
        'teamwork_score', 'safety_score', 'communication_score',
        'initiative_score', 'technical_skills_score'
    ]
    for field in score_fields:
        value = getattr(data, field, None)
        if value is not None and (value < 1 or value > 5):
            raise HTTPException(
                status_code=400,
                detail=f"{field} must be between 1 and 5"
            )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(evaluation, field, value)

    # If status changed to submitted, set evaluated_at
    if data.status == "submitted" and evaluation.evaluated_at is None:
        evaluation.evaluated_at = datetime.utcnow()

    # Recalculate overall score
    overall_score, overall_rating = calculate_overall_score(evaluation)
    evaluation.overall_score = overall_score
    evaluation.overall_rating = overall_rating

    db.commit()
    db.refresh(evaluation)

    # Reload with relationships
    evaluation = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(TechnicianEvaluation.id == evaluation.id).first()

    logger.info(f"Updated technician evaluation {evaluation_id}")
    return evaluation_to_response(evaluation)


@router.post("/{evaluation_id}/submit", response_model=TechnicianEvaluationResponse)
async def submit_evaluation(
    evaluation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit a draft evaluation for review"""
    evaluation = db.query(TechnicianEvaluation).filter(
        TechnicianEvaluation.id == evaluation_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).first()

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    if evaluation.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft evaluations can be submitted")

    evaluation.status = "submitted"
    evaluation.evaluated_at = datetime.utcnow()

    db.commit()
    db.refresh(evaluation)

    evaluation = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(TechnicianEvaluation.id == evaluation.id).first()

    logger.info(f"Submitted evaluation {evaluation_id}")
    return evaluation_to_response(evaluation)


@router.post("/{evaluation_id}/acknowledge", response_model=TechnicianEvaluationResponse)
async def acknowledge_evaluation(
    evaluation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Acknowledge an evaluation (by technician or HR)"""
    evaluation = db.query(TechnicianEvaluation).filter(
        TechnicianEvaluation.id == evaluation_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).first()

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    if evaluation.status not in ["submitted", "acknowledged"]:
        raise HTTPException(status_code=400, detail="Only submitted evaluations can be acknowledged")

    evaluation.status = "acknowledged"
    evaluation.acknowledged_by_technician = True
    evaluation.acknowledged_at = datetime.utcnow()

    db.commit()
    db.refresh(evaluation)

    evaluation = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(TechnicianEvaluation.id == evaluation.id).first()

    logger.info(f"Acknowledged evaluation {evaluation_id}")
    return evaluation_to_response(evaluation)


@router.post("/{evaluation_id}/finalize", response_model=TechnicianEvaluationResponse)
async def finalize_evaluation(
    evaluation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Finalize an evaluation (no further edits allowed)"""
    evaluation = db.query(TechnicianEvaluation).filter(
        TechnicianEvaluation.id == evaluation_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).first()

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    if evaluation.status == "finalized":
        raise HTTPException(status_code=400, detail="Evaluation is already finalized")

    evaluation.status = "finalized"

    db.commit()
    db.refresh(evaluation)

    evaluation = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(TechnicianEvaluation.id == evaluation.id).first()

    logger.info(f"Finalized evaluation {evaluation_id}")
    return evaluation_to_response(evaluation)


@router.delete("/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_technician_evaluation(
    evaluation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a technician evaluation (only draft evaluations)"""
    evaluation = db.query(TechnicianEvaluation).filter(
        TechnicianEvaluation.id == evaluation_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).first()

    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    if evaluation.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft evaluations can be deleted")

    db.delete(evaluation)
    db.commit()

    logger.info(f"Deleted technician evaluation {evaluation_id}")
    return None


@router.get("/technician/{technician_id}/history", response_model=List[TechnicianEvaluationResponse])
async def get_technician_evaluation_history(
    technician_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all evaluations for a specific technician"""
    # Verify technician exists and belongs to company
    technician = db.query(Technician).filter(
        Technician.id == technician_id,
        Technician.company_id == current_user.company_id
    ).first()
    if not technician:
        raise HTTPException(status_code=404, detail="Technician not found")

    evaluations = db.query(TechnicianEvaluation).options(
        joinedload(TechnicianEvaluation.technician),
        joinedload(TechnicianEvaluation.evaluator)
    ).filter(
        TechnicianEvaluation.technician_id == technician_id,
        TechnicianEvaluation.company_id == current_user.company_id
    ).order_by(TechnicianEvaluation.period_start.desc()).all()

    return [evaluation_to_response(e) for e in evaluations]
