from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Company, User, Plan
from app.utils.security import get_password_hash, create_access_token, verify_token
from app.utils.pm_seed import seed_pm_checklists_for_company
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)  # verify_token returns the email directly

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


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def slugify(text: str) -> str:
    """Convert text to slug"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text


class CompanyRegister(BaseModel):
    # Company details
    company_name: str
    company_email: EmailStr
    company_phone: Optional[str] = None
    company_address: Optional[str] = None
    company_city: Optional[str] = None
    company_country: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None

    # Admin user details
    admin_name: str
    admin_email: EmailStr
    admin_password: str
    admin_phone: Optional[str] = None

    # Plan selection
    plan_slug: str


class CompanyResponse(BaseModel):
    id: int
    name: str
    slug: str
    email: str
    phone: Optional[str]
    subscription_status: str
    plan_name: Optional[str]

    class Config:
        from_attributes = True


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    registration_number: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None


@router.post("/companies/register")
async def register_company(data: CompanyRegister, db: Session = Depends(get_db)):
    """Register a new company with admin user"""

    # Check if admin email already exists
    existing_user = db.query(User).filter(User.email == data.admin_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if company email already exists
    existing_company = db.query(Company).filter(Company.email == data.company_email).first()
    if existing_company:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company email already registered"
        )

    # Get the selected plan
    plan = db.query(Plan).filter(Plan.slug == data.plan_slug, Plan.is_active == True).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plan selected"
        )

    # Generate unique slug for company
    base_slug = slugify(data.company_name)
    slug = base_slug
    counter = 1
    while db.query(Company).filter(Company.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    try:
        # Create company
        company = Company(
            name=data.company_name,
            slug=slug,
            email=data.company_email,
            phone=data.company_phone,
            address=data.company_address,
            city=data.company_city,
            country=data.company_country,
            industry=data.industry,
            size=data.company_size,
            plan_id=plan.id,
            subscription_status="trial",
            subscription_start=datetime.utcnow(),
            subscription_end=datetime.utcnow() + timedelta(days=14),  # 14-day trial
            documents_used_this_month=0
        )
        db.add(company)
        db.flush()  # Get company ID before creating user

        # Create admin user
        admin_user = User(
            email=data.admin_email,
            name=data.admin_name,
            hashed_password=get_password_hash(data.admin_password),
            phone=data.admin_phone,
            company_id=company.id,
            role="admin",
            is_active=True,
            remaining_documents=plan.documents_max  # Set based on plan
        )
        db.add(admin_user)
        db.commit()

        db.refresh(company)
        db.refresh(admin_user)

        # Seed PM checklists for the new company
        try:
            pm_stats = seed_pm_checklists_for_company(company.id, db)
            db.commit()
            logger.info(f"PM checklists seeded for company {company.id}: {pm_stats}")
        except Exception as pm_error:
            logger.warning(f"Failed to seed PM checklists for company {company.id}: {pm_error}")
            # Don't fail company registration if PM seed fails

        # Create access token
        access_token = create_access_token(data={"sub": admin_user.email})

        logger.info(f"Company '{company.name}' registered with admin '{admin_user.email}'")

        return {
            "success": True,
            "message": "Company registered successfully",
            "company": {
                "id": company.id,
                "name": company.name,
                "slug": company.slug,
                "subscription_status": company.subscription_status,
                "plan": plan.name
            },
            "user": {
                "id": admin_user.id,
                "email": admin_user.email,
                "name": admin_user.name,
                "role": admin_user.role
            },
            "access_token": access_token,
            "token_type": "bearer"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error registering company: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error registering company: {str(e)}"
        )


@router.get("/companies/me")
async def get_my_company(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user's company details"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    plan_name = None
    if company.plan:
        plan_name = company.plan.name

    return {
        "id": company.id,
        "name": company.name,
        "slug": company.slug,
        "email": company.email,
        "phone": company.phone,
        "address": company.address,
        "city": company.city,
        "country": company.country,
        "tax_number": company.tax_number,
        "registration_number": company.registration_number,
        "website": company.website,
        "industry": company.industry,
        "size": company.size,
        "subscription_status": company.subscription_status,
        "subscription_start": company.subscription_start.isoformat() if company.subscription_start else None,
        "subscription_end": company.subscription_end.isoformat() if company.subscription_end else None,
        "documents_used_this_month": company.documents_used_this_month,
        "plan": {
            "id": company.plan.id,
            "name": company.plan.name,
            "documents_max": company.plan.documents_max,
            "max_users": company.plan.max_users,
            "max_clients": company.plan.max_clients,
            "max_branches": company.plan.max_branches,
            "max_projects": company.plan.max_projects
        } if company.plan else None
    }


@router.put("/companies/me")
async def update_my_company(
    data: CompanyUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update current user's company (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    try:
        # Update fields if provided
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(company, field, value)

        db.commit()
        db.refresh(company)

        logger.info(f"Company '{company.name}' updated by '{user.email}'")

        return {
            "success": True,
            "message": "Company updated successfully",
            "company": {
                "id": company.id,
                "name": company.name,
                "slug": company.slug,
                "email": company.email
            }
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating company: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating company: {str(e)}"
        )


@router.get("/companies/stats")
async def get_company_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get company statistics"""
    from app.models import Client, Branch, Project, ProcessedImage

    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Count stats
    total_users = db.query(User).filter(User.company_id == company.id).count()
    total_clients = db.query(Client).filter(Client.company_id == company.id).count()

    # Count branches through clients
    total_branches = db.query(Branch).join(Client).filter(Client.company_id == company.id).count()

    # Count projects through branches and clients
    total_projects = db.query(Project).join(Branch).join(Client).filter(Client.company_id == company.id).count()

    # Count invoices for this company's users
    total_invoices = db.query(ProcessedImage).join(User).filter(User.company_id == company.id).count()

    return {
        "total_users": total_users,
        "total_clients": total_clients,
        "total_branches": total_branches,
        "total_projects": total_projects,
        "total_invoices": total_invoices,
        "documents_used": company.documents_used_this_month,
        "documents_limit": company.plan.documents_max if company.plan else 0,
        "subscription_status": company.subscription_status
    }
