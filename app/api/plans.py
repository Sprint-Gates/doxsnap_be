from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models import Plan
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


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
    max_branches: int
    max_projects: int
    features: Optional[List[str]]
    is_popular: bool

    class Config:
        from_attributes = True


def plan_to_response(plan: Plan) -> dict:
    """Convert Plan model to response dict"""
    features = []
    if plan.features:
        try:
            features = json.loads(plan.features)
        except (json.JSONDecodeError, TypeError):
            features = []

    return {
        "id": plan.id,
        "name": plan.name,
        "slug": plan.slug,
        "description": plan.description,
        "price_monthly": float(plan.price_monthly),
        "documents_min": plan.documents_min,
        "documents_max": plan.documents_max,
        "max_users": plan.max_users,
        "max_clients": plan.max_clients,
        "max_branches": plan.max_branches,
        "max_projects": plan.max_projects,
        "features": features,
        "is_popular": plan.is_popular
    }


@router.get("/plans/")
async def get_plans(db: Session = Depends(get_db)):
    """Get all active plans (public endpoint for pricing page)"""
    plans = db.query(Plan).filter(Plan.is_active == True).order_by(Plan.sort_order).all()

    # If no plans exist, create default plans
    if not plans:
        plans = create_default_plans(db)

    return [plan_to_response(plan) for plan in plans]


@router.get("/plans/{slug}")
async def get_plan_by_slug(slug: str, db: Session = Depends(get_db)):
    """Get a specific plan by slug"""
    plan = db.query(Plan).filter(Plan.slug == slug, Plan.is_active == True).first()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan not found"
        )

    return plan_to_response(plan)


def create_default_plans(db: Session) -> List[Plan]:
    """Create default subscription plans"""
    default_plans = [
        Plan(
            name="Starter",
            slug="starter",
            description="Perfect for small businesses just getting started with document management",
            price_monthly=100.00,
            documents_min=0,
            documents_max=200,
            max_users=3,
            max_clients=5,
            max_branches=3,
            max_projects=10,
            features=json.dumps([
                "Up to 200 documents/month",
                "3 team members",
                "5 clients",
                "Basic OCR processing",
                "Email support",
                "Data export (CSV, Excel)"
            ]),
            is_active=True,
            is_popular=False,
            sort_order=1
        ),
        Plan(
            name="Professional",
            slug="professional",
            description="Ideal for growing businesses with more document processing needs",
            price_monthly=250.00,
            documents_min=200,
            documents_max=500,
            max_users=10,
            max_clients=20,
            max_branches=10,
            max_projects=50,
            features=json.dumps([
                "Up to 500 documents/month",
                "10 team members",
                "20 clients",
                "Advanced AI extraction",
                "Priority support",
                "API access",
                "Custom document types",
                "Vendor management"
            ]),
            is_active=True,
            is_popular=True,
            sort_order=2
        ),
        Plan(
            name="Enterprise",
            slug="enterprise",
            description="For large organizations requiring high-volume document processing",
            price_monthly=400.00,
            documents_min=500,
            documents_max=1000,
            max_users=50,
            max_clients=100,
            max_branches=50,
            max_projects=200,
            features=json.dumps([
                "Up to 1000 documents/month",
                "Unlimited team members",
                "Unlimited clients",
                "Advanced AI extraction",
                "Dedicated support",
                "Full API access",
                "Custom integrations",
                "Audit logs",
                "SSO authentication",
                "Custom branding"
            ]),
            is_active=True,
            is_popular=False,
            sort_order=3
        )
    ]

    for plan in default_plans:
        db.add(plan)

    db.commit()

    for plan in default_plans:
        db.refresh(plan)

    logger.info("Created default subscription plans")
    return default_plans
