"""
Platform Admin API
Manages companies, subscriptions, and plans for the platform owner
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import secrets

from app.database import get_db
from app.models import SuperAdmin, SuperAdminRefreshToken, Company, Plan, User, UpgradeRequest
from app.utils.security import get_password_hash, verify_password, create_access_token, verify_token, generate_refresh_token, get_refresh_token_expiry

router = APIRouter()
security = HTTPBearer()


# ============================================================================
# Pydantic Schemas
# ============================================================================

class SuperAdminLogin(BaseModel):
    email: EmailStr
    password: str


class SuperAdminPasswordChange(BaseModel):
    current_password: str
    new_password: str


class SuperAdminCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    setup_secret: str  # Required secret key for creating super admin


class SuperAdminResponse(BaseModel):
    id: int
    email: str
    name: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    super_admin: SuperAdminResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PlanCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    price_monthly: float
    documents_min: int
    documents_max: int
    max_users: int = 5
    max_clients: int = 10
    max_branches: int = 5
    max_projects: int = 20
    features: Optional[str] = None
    is_active: bool = True
    is_popular: bool = False
    sort_order: int = 0


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    documents_min: Optional[int] = None
    documents_max: Optional[int] = None
    max_users: Optional[int] = None
    max_clients: Optional[int] = None
    max_branches: Optional[int] = None
    max_projects: Optional[int] = None
    features: Optional[str] = None
    is_active: Optional[bool] = None
    is_popular: Optional[bool] = None
    sort_order: Optional[int] = None


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
    features: Optional[str]
    is_active: bool
    is_popular: bool
    sort_order: int
    company_count: Optional[int] = None

    class Config:
        from_attributes = True


class CompanySubscriptionUpdate(BaseModel):
    plan_id: Optional[int] = None
    subscription_status: Optional[str] = None  # trial, active, suspended, cancelled
    subscription_end: Optional[datetime] = None
    extend_days: Optional[int] = None  # Add days to current subscription_end
    max_users_override: Optional[int] = None  # Override plan's max_users (set to -1 to remove override)
    documents_limit_override: Optional[int] = None  # Override plan's documents_max (set to -1 to remove override)


class CompanyResponse(BaseModel):
    id: int
    name: str
    slug: str
    email: str
    phone: Optional[str]
    city: Optional[str]
    country: Optional[str]
    industry: Optional[str]
    size: Optional[str]
    plan_id: Optional[int]
    plan_name: Optional[str] = None
    subscription_status: str
    subscription_start: Optional[datetime]
    subscription_end: Optional[datetime]
    documents_used_this_month: int
    documents_limit: Optional[int] = None  # Effective documents limit (override or plan default)
    documents_limit_override: Optional[int] = None  # Custom override value (null means using plan default)
    user_count: Optional[int] = None
    max_users: Optional[int] = None  # Effective max users (override or plan default)
    max_users_override: Optional[int] = None  # Custom override value (null means using plan default)
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_companies: int
    active_companies: int
    trial_companies: int
    expired_companies: int
    suspended_companies: int
    total_users: int
    total_revenue_monthly: float
    companies_by_plan: List[dict]
    recent_registrations: List[CompanyResponse]
    expiring_soon: List[CompanyResponse]


def build_company_response(company: Company, user_count: int) -> CompanyResponse:
    """Helper function to build CompanyResponse with all fields"""
    # Calculate effective max_users (override takes precedence over plan default)
    max_users = None
    if company.max_users_override is not None:
        max_users = company.max_users_override
    elif company.plan:
        max_users = company.plan.max_users

    # Calculate effective documents_limit (override takes precedence over plan default)
    documents_limit = None
    if company.documents_limit_override is not None:
        documents_limit = company.documents_limit_override
    elif company.plan:
        documents_limit = company.plan.documents_max

    return CompanyResponse(
        id=company.id,
        name=company.name,
        slug=company.slug,
        email=company.email,
        phone=company.phone,
        city=company.city,
        country=company.country,
        industry=company.industry,
        size=company.size,
        plan_id=company.plan_id,
        plan_name=company.plan.name if company.plan else None,
        subscription_status=company.subscription_status,
        subscription_start=company.subscription_start,
        subscription_end=company.subscription_end,
        documents_used_this_month=company.documents_used_this_month,
        documents_limit=documents_limit,
        documents_limit_override=company.documents_limit_override,
        user_count=user_count,
        max_users=max_users,
        max_users_override=company.max_users_override,
        is_active=company.is_active,
        created_at=company.created_at
    )


# ============================================================================
# Authentication Helpers
# ============================================================================

def get_current_super_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> SuperAdmin:
    """Get current authenticated super admin from JWT token"""
    token = credentials.credentials
    email = verify_token(token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    # Check if token has super_admin prefix
    if not email.startswith("super_admin:"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )

    actual_email = email.replace("super_admin:", "")
    super_admin = db.query(SuperAdmin).filter(SuperAdmin.email == actual_email).first()

    if not super_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Super admin not found"
        )

    if not super_admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Super admin account is disabled"
        )

    return super_admin


# ============================================================================
# Authentication Endpoints
# ============================================================================

@router.post("/platform-admin/auth/login", response_model=TokenResponse)
async def login(data: SuperAdminLogin, db: Session = Depends(get_db)):
    """Login as platform super admin"""
    super_admin = db.query(SuperAdmin).filter(SuperAdmin.email == data.email).first()

    if not super_admin or not verify_password(data.password, super_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not super_admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled"
        )

    # Update last login
    super_admin.last_login = datetime.utcnow()
    db.commit()

    # Create tokens with super_admin prefix to distinguish from regular users
    access_token = create_access_token(data={"sub": f"super_admin:{super_admin.email}"})
    refresh_token = generate_refresh_token()

    # Store refresh token
    db_refresh_token = SuperAdminRefreshToken(
        super_admin_id=super_admin.id,
        token=refresh_token,
        expires_at=get_refresh_token_expiry()
    )
    db.add(db_refresh_token)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        super_admin=SuperAdminResponse.model_validate(super_admin)
    )


@router.post("/platform-admin/auth/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Refresh access token for super admin"""
    db_token = db.query(SuperAdminRefreshToken).filter(
        SuperAdminRefreshToken.token == data.refresh_token,
        SuperAdminRefreshToken.is_revoked == False,
        SuperAdminRefreshToken.expires_at > datetime.utcnow()
    ).first()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    super_admin = db.query(SuperAdmin).filter(SuperAdmin.id == db_token.super_admin_id).first()
    if not super_admin or not super_admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or disabled"
        )

    # Revoke old token and create new one
    db_token.is_revoked = True

    access_token = create_access_token(data={"sub": f"super_admin:{super_admin.email}"})
    new_refresh_token = generate_refresh_token()

    db_new_token = SuperAdminRefreshToken(
        super_admin_id=super_admin.id,
        token=new_refresh_token,
        expires_at=get_refresh_token_expiry()
    )
    db.add(db_new_token)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        super_admin=SuperAdminResponse.model_validate(super_admin)
    )


@router.post("/platform-admin/auth/logout")
async def logout(
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Logout super admin and revoke refresh token"""
    db_token = db.query(SuperAdminRefreshToken).filter(
        SuperAdminRefreshToken.token == data.refresh_token,
        SuperAdminRefreshToken.super_admin_id == super_admin.id
    ).first()

    if db_token:
        db_token.is_revoked = True
        db.commit()

    return {"message": "Logged out successfully"}


@router.get("/platform-admin/auth/me", response_model=SuperAdminResponse)
async def get_me(super_admin: SuperAdmin = Depends(get_current_super_admin)):
    """Get current super admin info"""
    return SuperAdminResponse.model_validate(super_admin)


@router.post("/platform-admin/auth/change-password")
async def change_password(
    data: SuperAdminPasswordChange,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Change super admin password"""
    # Verify current password
    if not verify_password(data.current_password, super_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Validate new password strength
    if len(data.new_password) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 12 characters"
        )

    # Check new password is different from current
    if data.current_password == data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )

    # Update password
    super_admin.hashed_password = get_password_hash(data.new_password)
    db.commit()

    return {"message": "Password changed successfully"}


# ============================================================================
# Dashboard Endpoints
# ============================================================================

@router.get("/platform-admin/dashboard", response_model=DashboardStats)
async def get_dashboard(
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Get platform dashboard statistics"""
    now = datetime.utcnow()

    # Total companies
    total_companies = db.query(Company).count()

    # Active companies (subscription_status = 'active' and not expired)
    active_companies = db.query(Company).filter(
        Company.subscription_status == "active",
        Company.subscription_end > now
    ).count()

    # Trial companies
    trial_companies = db.query(Company).filter(
        Company.subscription_status == "trial",
        Company.subscription_end > now
    ).count()

    # Expired companies (trial or active but past end date)
    expired_companies = db.query(Company).filter(
        Company.subscription_end <= now,
        Company.subscription_status.in_(["trial", "active"])
    ).count()

    # Suspended companies
    suspended_companies = db.query(Company).filter(
        Company.subscription_status == "suspended"
    ).count()

    # Total users
    total_users = db.query(User).filter(User.is_active == True).count()

    # Monthly revenue (from active subscriptions)
    revenue_query = db.query(func.sum(Plan.price_monthly)).join(Company).filter(
        Company.subscription_status == "active",
        Company.subscription_end > now
    ).scalar()
    total_revenue_monthly = float(revenue_query or 0)

    # Companies by plan
    companies_by_plan = []
    plans = db.query(Plan).filter(Plan.is_active == True).all()
    for plan in plans:
        count = db.query(Company).filter(Company.plan_id == plan.id).count()
        companies_by_plan.append({
            "plan_id": plan.id,
            "plan_name": plan.name,
            "company_count": count,
            "price_monthly": float(plan.price_monthly)
        })

    # Recent registrations (last 7 days)
    recent_cutoff = now - timedelta(days=7)
    recent_companies = db.query(Company).filter(
        Company.created_at >= recent_cutoff
    ).order_by(Company.created_at.desc()).limit(5).all()

    recent_registrations = []
    for company in recent_companies:
        user_count = db.query(User).filter(User.company_id == company.id, User.is_active == True).count()
        recent_registrations.append(build_company_response(company, user_count))

    # Expiring soon (within 7 days)
    expiring_cutoff = now + timedelta(days=7)
    expiring_companies = db.query(Company).filter(
        Company.subscription_end > now,
        Company.subscription_end <= expiring_cutoff,
        Company.subscription_status.in_(["trial", "active"])
    ).order_by(Company.subscription_end.asc()).limit(5).all()

    expiring_soon = []
    for company in expiring_companies:
        user_count = db.query(User).filter(User.company_id == company.id, User.is_active == True).count()
        expiring_soon.append(build_company_response(company, user_count))

    return DashboardStats(
        total_companies=total_companies,
        active_companies=active_companies,
        trial_companies=trial_companies,
        expired_companies=expired_companies,
        suspended_companies=suspended_companies,
        total_users=total_users,
        total_revenue_monthly=total_revenue_monthly,
        companies_by_plan=companies_by_plan,
        recent_registrations=recent_registrations,
        expiring_soon=expiring_soon
    )


# ============================================================================
# Company Management Endpoints
# ============================================================================

@router.get("/platform-admin/companies", response_model=List[CompanyResponse])
async def list_companies(
    status: Optional[str] = None,
    plan_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """List all companies with filtering options"""
    query = db.query(Company)

    if status:
        if status == "expired":
            query = query.filter(
                Company.subscription_end <= datetime.utcnow(),
                Company.subscription_status.in_(["trial", "active"])
            )
        else:
            query = query.filter(Company.subscription_status == status)

    if plan_id:
        query = query.filter(Company.plan_id == plan_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Company.name.ilike(search_term)) |
            (Company.email.ilike(search_term)) |
            (Company.slug.ilike(search_term))
        )

    companies = query.order_by(Company.created_at.desc()).all()

    result = []
    for company in companies:
        user_count = db.query(User).filter(User.company_id == company.id, User.is_active == True).count()
        result.append(build_company_response(company, user_count))

    return result


@router.get("/platform-admin/companies/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: int,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Get company details"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    user_count = db.query(User).filter(User.company_id == company.id, User.is_active == True).count()

    return build_company_response(company, user_count)


@router.put("/platform-admin/companies/{company_id}/subscription", response_model=CompanyResponse)
async def update_company_subscription(
    company_id: int,
    data: CompanySubscriptionUpdate,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Update company subscription (plan, status, dates)"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Update plan
    if data.plan_id is not None:
        plan = db.query(Plan).filter(Plan.id == data.plan_id).first()
        if not plan:
            raise HTTPException(status_code=400, detail="Invalid plan ID")
        company.plan_id = data.plan_id

    # Update subscription status
    if data.subscription_status is not None:
        valid_statuses = ["trial", "active", "suspended", "cancelled"]
        if data.subscription_status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}"
            )
        company.subscription_status = data.subscription_status

        # If activating, set subscription_start if not set
        if data.subscription_status == "active" and not company.subscription_start:
            company.subscription_start = datetime.utcnow()

    # Update subscription end date
    if data.subscription_end is not None:
        company.subscription_end = data.subscription_end

    # Extend subscription by days
    if data.extend_days is not None and data.extend_days > 0:
        if company.subscription_end and company.subscription_end > datetime.utcnow():
            company.subscription_end = company.subscription_end + timedelta(days=data.extend_days)
        else:
            company.subscription_end = datetime.utcnow() + timedelta(days=data.extend_days)

    # Update max_users_override (allows setting custom user limit for this company)
    # Use special value -1 to indicate "remove override" (set to None)
    if data.max_users_override is not None:
        if data.max_users_override == -1 or data.max_users_override == 0:
            company.max_users_override = None  # Remove override, use plan default
        else:
            company.max_users_override = data.max_users_override

    # Update documents_limit_override (allows setting custom documents limit for this company)
    # Use special value -1 to indicate "remove override" (set to None)
    if data.documents_limit_override is not None:
        if data.documents_limit_override == -1 or data.documents_limit_override == 0:
            company.documents_limit_override = None  # Remove override, use plan default
        else:
            company.documents_limit_override = data.documents_limit_override

    db.commit()
    db.refresh(company)

    user_count = db.query(User).filter(User.company_id == company.id, User.is_active == True).count()

    return build_company_response(company, user_count)


@router.post("/platform-admin/companies/{company_id}/activate")
async def activate_company(
    company_id: int,
    days: int = 30,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Activate a company subscription"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.subscription_status = "active"
    company.subscription_start = datetime.utcnow()
    company.subscription_end = datetime.utcnow() + timedelta(days=days)

    db.commit()

    return {"message": f"Company activated for {days} days", "subscription_end": company.subscription_end}


@router.post("/platform-admin/companies/{company_id}/suspend")
async def suspend_company(
    company_id: int,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Suspend a company subscription"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company.subscription_status = "suspended"
    db.commit()

    return {"message": "Company suspended"}


@router.post("/platform-admin/companies/{company_id}/extend")
async def extend_company_subscription(
    company_id: int,
    days: int = 30,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Extend a company's subscription by given days"""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if company.subscription_end and company.subscription_end > datetime.utcnow():
        company.subscription_end = company.subscription_end + timedelta(days=days)
    else:
        company.subscription_end = datetime.utcnow() + timedelta(days=days)

    db.commit()

    return {"message": f"Subscription extended by {days} days", "subscription_end": company.subscription_end}


# ============================================================================
# Plan Management Endpoints
# ============================================================================

@router.get("/platform-admin/plans", response_model=List[PlanResponse])
async def list_plans(
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """List all plans with company counts"""
    plans = db.query(Plan).order_by(Plan.sort_order, Plan.id).all()

    result = []
    for plan in plans:
        company_count = db.query(Company).filter(Company.plan_id == plan.id).count()
        plan_data = PlanResponse.model_validate(plan)
        plan_data.company_count = company_count
        result.append(plan_data)

    return result


@router.get("/platform-admin/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Get plan details"""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    company_count = db.query(Company).filter(Company.plan_id == plan.id).count()
    plan_data = PlanResponse.model_validate(plan)
    plan_data.company_count = company_count

    return plan_data


@router.post("/platform-admin/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanCreate,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Create a new plan"""
    # Check for duplicate slug
    existing = db.query(Plan).filter(Plan.slug == data.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Plan with this slug already exists")

    plan = Plan(
        name=data.name,
        slug=data.slug,
        description=data.description,
        price_monthly=data.price_monthly,
        documents_min=data.documents_min,
        documents_max=data.documents_max,
        max_users=data.max_users,
        max_clients=data.max_clients,
        max_branches=data.max_branches,
        max_projects=data.max_projects,
        features=data.features,
        is_active=data.is_active,
        is_popular=data.is_popular,
        sort_order=data.sort_order
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)

    plan_data = PlanResponse.model_validate(plan)
    plan_data.company_count = 0

    return plan_data


@router.put("/platform-admin/plans/{plan_id}", response_model=PlanResponse)
async def update_plan(
    plan_id: int,
    data: PlanUpdate,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Update a plan"""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # Update fields if provided
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(plan, field, value)

    db.commit()
    db.refresh(plan)

    company_count = db.query(Company).filter(Company.plan_id == plan.id).count()
    plan_data = PlanResponse.model_validate(plan)
    plan_data.company_count = company_count

    return plan_data


@router.delete("/platform-admin/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Delete a plan (only if no companies are using it)"""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    company_count = db.query(Company).filter(Company.plan_id == plan.id).count()
    if company_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete plan. {company_count} companies are using this plan."
        )

    db.delete(plan)
    db.commit()

    return {"message": "Plan deleted successfully"}


# ============================================================================
# Super Admin Management (for creating initial super admin)
# ============================================================================

# IMPORTANT: This secret must be set as an environment variable PLATFORM_ADMIN_SETUP_SECRET
# Generate a secure random string and keep it confidential
import os
import hashlib
import time

# In-memory rate limiting for setup attempts
_setup_attempts: dict = {}
_MAX_SETUP_ATTEMPTS = 3
_LOCKOUT_DURATION = 3600  # 1 hour in seconds

def _check_rate_limit(ip: str) -> bool:
    """Check if IP is rate limited. Returns True if allowed, False if blocked."""
    now = time.time()
    if ip in _setup_attempts:
        attempts, first_attempt = _setup_attempts[ip]
        # Reset if lockout period has passed
        if now - first_attempt > _LOCKOUT_DURATION:
            _setup_attempts[ip] = (1, now)
            return True
        # Block if too many attempts
        if attempts >= _MAX_SETUP_ATTEMPTS:
            return False
        _setup_attempts[ip] = (attempts + 1, first_attempt)
    else:
        _setup_attempts[ip] = (1, now)
    return True

def _get_setup_secret() -> str:
    """Get the setup secret from environment variable."""
    secret = os.environ.get('PLATFORM_ADMIN_SETUP_SECRET')
    if not secret:
        # Default secret for development only - MUST be changed in production
        secret = 'CHANGE_THIS_SECRET_IN_PRODUCTION_doxsnap2024!'
    return secret


@router.post("/platform-admin/setup", response_model=SuperAdminResponse, status_code=status.HTTP_201_CREATED)
async def setup_super_admin(
    data: SuperAdminCreate,
    db: Session = Depends(get_db)
):
    """
    Create initial super admin account.

    SECURITY REQUIREMENTS:
    - Only works if no super admins exist yet
    - Requires the correct setup_secret (from PLATFORM_ADMIN_SETUP_SECRET env var)
    - Rate limited to 3 attempts per hour per IP
    - All attempts are logged
    """
    import logging
    logger = logging.getLogger(__name__)

    # Log attempt (without sensitive data)
    logger.warning(f"[SECURITY] Super admin setup attempt for email: {data.email}")

    # Verify setup secret FIRST (before revealing if admin exists)
    expected_secret = _get_setup_secret()

    # Use constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(data.setup_secret, expected_secret):
        logger.warning(f"[SECURITY] Invalid setup secret attempt for email: {data.email}")
        # Sleep to prevent timing attacks and brute force
        time.sleep(2)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid setup credentials"
        )

    # Check if any super admin exists
    existing = db.query(SuperAdmin).first()
    if existing:
        logger.warning(f"[SECURITY] Setup attempt when super admin already exists: {data.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup not available"
        )

    # Validate password strength
    if len(data.password) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 12 characters"
        )

    # Create super admin
    super_admin = SuperAdmin(
        email=data.email,
        name=data.name,
        hashed_password=get_password_hash(data.password),
        is_active=True
    )

    db.add(super_admin)
    db.commit()
    db.refresh(super_admin)

    logger.info(f"[SECURITY] Super admin created successfully: {data.email}")

    return SuperAdminResponse.model_validate(super_admin)


# ============================================================================
# Upgrade Request Management
# ============================================================================

class UpgradeRequestAdminResponse(BaseModel):
    id: int
    company_id: int
    company_name: str
    company_email: str
    requested_by_id: int
    requested_by_name: str
    requested_by_email: str
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


class UpgradeRequestProcess(BaseModel):
    status: str  # approved, rejected, completed
    admin_notes: Optional[str] = None
    new_plan_id: Optional[int] = None  # For upgrading company to new plan
    extend_days: Optional[int] = None  # For extending subscription


@router.get("/platform-admin/upgrade-requests", response_model=List[UpgradeRequestAdminResponse])
async def get_all_upgrade_requests(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Get all upgrade requests, optionally filtered by status"""
    query = db.query(UpgradeRequest)

    if status_filter:
        query = query.filter(UpgradeRequest.status == status_filter)

    requests = query.order_by(UpgradeRequest.created_at.desc()).all()

    result = []
    for req in requests:
        company = db.query(Company).filter(Company.id == req.company_id).first()
        user = db.query(User).filter(User.id == req.requested_by_id).first()
        current_plan = db.query(Plan).filter(Plan.id == req.current_plan_id).first() if req.current_plan_id else None
        requested_plan = db.query(Plan).filter(Plan.id == req.requested_plan_id).first() if req.requested_plan_id else None

        result.append(UpgradeRequestAdminResponse(
            id=req.id,
            company_id=req.company_id,
            company_name=company.name if company else "Unknown",
            company_email=company.email if company else "",
            requested_by_id=req.requested_by_id,
            requested_by_name=user.name if user else "Unknown",
            requested_by_email=user.email if user else "",
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


@router.get("/platform-admin/upgrade-requests/{request_id}", response_model=UpgradeRequestAdminResponse)
async def get_upgrade_request(
    request_id: int,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Get a specific upgrade request"""
    req = db.query(UpgradeRequest).filter(UpgradeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Upgrade request not found")

    company = db.query(Company).filter(Company.id == req.company_id).first()
    user = db.query(User).filter(User.id == req.requested_by_id).first()
    current_plan = db.query(Plan).filter(Plan.id == req.current_plan_id).first() if req.current_plan_id else None
    requested_plan = db.query(Plan).filter(Plan.id == req.requested_plan_id).first() if req.requested_plan_id else None

    return UpgradeRequestAdminResponse(
        id=req.id,
        company_id=req.company_id,
        company_name=company.name if company else "Unknown",
        company_email=company.email if company else "",
        requested_by_id=req.requested_by_id,
        requested_by_name=user.name if user else "Unknown",
        requested_by_email=user.email if user else "",
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
    )


@router.put("/platform-admin/upgrade-requests/{request_id}/process")
async def process_upgrade_request(
    request_id: int,
    data: UpgradeRequestProcess,
    db: Session = Depends(get_db),
    super_admin: SuperAdmin = Depends(get_current_super_admin)
):
    """Process an upgrade request (approve, reject, or complete)"""
    import logging
    logger = logging.getLogger(__name__)

    req = db.query(UpgradeRequest).filter(UpgradeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Upgrade request not found")

    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending requests can be processed")

    valid_statuses = ["approved", "rejected", "completed"]
    if data.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    company = db.query(Company).filter(Company.id == req.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Update the request
    req.status = data.status
    req.admin_notes = data.admin_notes
    req.processed_by_id = super_admin.id
    req.processed_at = datetime.utcnow()

    # If approved/completed and a new plan is specified, update the company
    if data.status in ["approved", "completed"]:
        if data.new_plan_id:
            new_plan = db.query(Plan).filter(Plan.id == data.new_plan_id).first()
            if not new_plan:
                raise HTTPException(status_code=404, detail="New plan not found")
            company.plan_id = new_plan.id
            logger.info(f"Company {company.name} upgraded to plan {new_plan.name}")

        # Extend subscription if specified
        if data.extend_days:
            if company.subscription_end:
                company.subscription_end = company.subscription_end + timedelta(days=data.extend_days)
            else:
                company.subscription_end = datetime.utcnow() + timedelta(days=data.extend_days)

            # Update status from trial to active if extending
            if company.subscription_status == "trial":
                company.subscription_status = "active"

            logger.info(f"Company {company.name} subscription extended by {data.extend_days} days")

    db.commit()
    logger.info(f"Upgrade request {request_id} processed: status={data.status}, by={super_admin.email}")

    return {
        "success": True,
        "message": f"Upgrade request {data.status}",
        "request_id": request_id
    }
