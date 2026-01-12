from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from app.database import get_db
from app.models import UpgradeRequest, User, Company, Plan
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


# Request/Response models
class UpgradeRequestCreate(BaseModel):
    requested_plan_id: Optional[int] = None
    request_type: str  # upgrade, downgrade, renewal, custom
    message: Optional[str] = None


class UpgradeRequestResponse(BaseModel):
    id: int
    company_id: int
    company_name: str
    requested_by_id: int
    requested_by_name: str
    current_plan_id: Optional[int]
    current_plan_name: Optional[str]
    requested_plan_id: Optional[int]
    requested_plan_name: Optional[str]
    request_type: str
    status: str
    message: Optional[str]
    admin_notes: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


class PlanResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    price_monthly: float
    documents_min: int
    documents_max: int
    max_users: int
    max_clients: int
    max_projects: int
    is_popular: bool

    class Config:
        from_attributes = True


class SubscriptionInfoResponse(BaseModel):
    company_name: str
    current_plan: Optional[PlanResponse]
    subscription_status: str
    subscription_end: Optional[datetime]
    is_trial: bool
    days_remaining: Optional[int]
    available_plans: List[PlanResponse]
    pending_request: Optional[UpgradeRequestResponse]


@router.get("/upgrade/info", response_model=SubscriptionInfoResponse)
async def get_upgrade_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get subscription info and available upgrade options"""
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Get current plan
    current_plan = None
    if company.plan_id:
        plan = db.query(Plan).filter(Plan.id == company.plan_id).first()
        if plan:
            current_plan = PlanResponse(
                id=plan.id,
                name=plan.name,
                slug=plan.slug,
                description=plan.description,
                price_monthly=float(plan.price_monthly),
                documents_min=plan.documents_min,
                documents_max=plan.documents_max,
                max_users=plan.max_users,
                max_clients=plan.max_clients,
                max_projects=plan.max_projects,
                is_popular=plan.is_popular
            )

    # Calculate days remaining
    days_remaining = None
    if company.subscription_end:
        delta = company.subscription_end - datetime.utcnow()
        days_remaining = max(0, delta.days)

    # Get available plans
    plans = db.query(Plan).filter(Plan.is_active == True).order_by(Plan.sort_order).all()
    available_plans = [
        PlanResponse(
            id=p.id,
            name=p.name,
            slug=p.slug,
            description=p.description,
            price_monthly=float(p.price_monthly),
            documents_min=p.documents_min,
            documents_max=p.documents_max,
            max_users=p.max_users,
            max_clients=p.max_clients,
            max_projects=p.max_projects,
            is_popular=p.is_popular
        )
        for p in plans
    ]

    # Check for pending upgrade request
    pending_request = db.query(UpgradeRequest).filter(
        UpgradeRequest.company_id == company.id,
        UpgradeRequest.status == "pending"
    ).first()

    pending_response = None
    if pending_request:
        req_plan = db.query(Plan).filter(Plan.id == pending_request.requested_plan_id).first() if pending_request.requested_plan_id else None
        cur_plan = db.query(Plan).filter(Plan.id == pending_request.current_plan_id).first() if pending_request.current_plan_id else None
        pending_response = UpgradeRequestResponse(
            id=pending_request.id,
            company_id=pending_request.company_id,
            company_name=company.name,
            requested_by_id=pending_request.requested_by_id,
            requested_by_name=current_user.name,
            current_plan_id=pending_request.current_plan_id,
            current_plan_name=cur_plan.name if cur_plan else None,
            requested_plan_id=pending_request.requested_plan_id,
            requested_plan_name=req_plan.name if req_plan else None,
            request_type=pending_request.request_type,
            status=pending_request.status,
            message=pending_request.message,
            admin_notes=pending_request.admin_notes,
            created_at=pending_request.created_at,
            processed_at=pending_request.processed_at
        )

    return SubscriptionInfoResponse(
        company_name=company.name,
        current_plan=current_plan,
        subscription_status=company.subscription_status or "trial",
        subscription_end=company.subscription_end,
        is_trial=company.subscription_status == "trial",
        days_remaining=days_remaining,
        available_plans=available_plans,
        pending_request=pending_response
    )


@router.post("/upgrade/request", response_model=UpgradeRequestResponse)
async def create_upgrade_request(
    data: UpgradeRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Submit an upgrade/renewal request"""
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Check for existing pending request
    existing = db.query(UpgradeRequest).filter(
        UpgradeRequest.company_id == company.id,
        UpgradeRequest.status == "pending"
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="You already have a pending upgrade request. Please wait for it to be processed."
        )

    # Validate request type
    valid_types = ["upgrade", "downgrade", "renewal", "custom"]
    if data.request_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid request type. Must be one of: {valid_types}")

    # Validate requested plan if provided
    requested_plan = None
    if data.requested_plan_id:
        requested_plan = db.query(Plan).filter(Plan.id == data.requested_plan_id, Plan.is_active == True).first()
        if not requested_plan:
            raise HTTPException(status_code=404, detail="Requested plan not found")

    # Create the upgrade request
    upgrade_request = UpgradeRequest(
        company_id=company.id,
        requested_by_id=current_user.id,
        current_plan_id=company.plan_id,
        requested_plan_id=data.requested_plan_id,
        request_type=data.request_type,
        status="pending",
        message=data.message
    )

    db.add(upgrade_request)
    db.commit()
    db.refresh(upgrade_request)

    logger.info(f"Upgrade request created: company={company.name}, type={data.request_type}, user={current_user.email}")

    # Build response
    current_plan = db.query(Plan).filter(Plan.id == company.plan_id).first() if company.plan_id else None

    return UpgradeRequestResponse(
        id=upgrade_request.id,
        company_id=upgrade_request.company_id,
        company_name=company.name,
        requested_by_id=upgrade_request.requested_by_id,
        requested_by_name=current_user.name,
        current_plan_id=upgrade_request.current_plan_id,
        current_plan_name=current_plan.name if current_plan else None,
        requested_plan_id=upgrade_request.requested_plan_id,
        requested_plan_name=requested_plan.name if requested_plan else None,
        request_type=upgrade_request.request_type,
        status=upgrade_request.status,
        message=upgrade_request.message,
        admin_notes=upgrade_request.admin_notes,
        created_at=upgrade_request.created_at,
        processed_at=upgrade_request.processed_at
    )


@router.get("/upgrade/requests", response_model=List[UpgradeRequestResponse])
async def get_my_upgrade_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all upgrade requests for the current user's company"""
    requests = db.query(UpgradeRequest).filter(
        UpgradeRequest.company_id == current_user.company_id
    ).order_by(UpgradeRequest.created_at.desc()).all()

    result = []
    for req in requests:
        company = db.query(Company).filter(Company.id == req.company_id).first()
        user = db.query(User).filter(User.id == req.requested_by_id).first()
        current_plan = db.query(Plan).filter(Plan.id == req.current_plan_id).first() if req.current_plan_id else None
        requested_plan = db.query(Plan).filter(Plan.id == req.requested_plan_id).first() if req.requested_plan_id else None

        result.append(UpgradeRequestResponse(
            id=req.id,
            company_id=req.company_id,
            company_name=company.name if company else "Unknown",
            requested_by_id=req.requested_by_id,
            requested_by_name=user.name if user else "Unknown",
            current_plan_id=req.current_plan_id,
            current_plan_name=current_plan.name if current_plan else None,
            requested_plan_id=req.requested_plan_id,
            requested_plan_name=requested_plan.name if requested_plan else None,
            request_type=req.request_type,
            status=req.status,
            message=req.message,
            admin_notes=req.admin_notes,
            created_at=req.created_at,
            processed_at=req.processed_at
        ))

    return result


@router.delete("/upgrade/request/{request_id}")
async def cancel_upgrade_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a pending upgrade request"""
    upgrade_request = db.query(UpgradeRequest).filter(
        UpgradeRequest.id == request_id,
        UpgradeRequest.company_id == current_user.company_id
    ).first()

    if not upgrade_request:
        raise HTTPException(status_code=404, detail="Upgrade request not found")

    if upgrade_request.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending requests can be cancelled")

    db.delete(upgrade_request)
    db.commit()

    logger.info(f"Upgrade request cancelled: id={request_id}, user={current_user.email}")

    return {"message": "Upgrade request cancelled successfully"}
