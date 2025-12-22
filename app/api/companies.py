from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Company, User, Plan
from app.utils.security import get_password_hash, create_access_token, verify_token
from app.utils.pm_seed import seed_pm_checklists_for_company
from app.utils.company_seed import seed_company_defaults
import re
import logging
import os
import uuid

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
    primary_currency: Optional[str] = None  # ISO 4217 currency code


# Supported currencies for the application
SUPPORTED_CURRENCIES = [
    {"code": "USD", "name": "US Dollar", "symbol": "$"},
    {"code": "EUR", "name": "Euro", "symbol": "€"},
    {"code": "GBP", "name": "British Pound", "symbol": "£"},
    {"code": "LBP", "name": "Lebanese Pound", "symbol": "ل.ل"},
    {"code": "SYP", "name": "Syrian Pound", "symbol": "ل.س"},
    {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ"},
    {"code": "SAR", "name": "Saudi Riyal", "symbol": "ر.س"},
    {"code": "QAR", "name": "Qatari Riyal", "symbol": "ر.ق"},
    {"code": "KWD", "name": "Kuwaiti Dinar", "symbol": "د.ك"},
    {"code": "BHD", "name": "Bahraini Dinar", "symbol": "د.ب"},
    {"code": "OMR", "name": "Omani Rial", "symbol": "ر.ع"},
    {"code": "JOD", "name": "Jordanian Dinar", "symbol": "د.أ"},
    {"code": "EGP", "name": "Egyptian Pound", "symbol": "ج.م"},
]


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
            subscription_end=datetime.utcnow() + timedelta(days=5),  # 5-day trial
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

        # Seed default company data (Chart of Accounts, Warehouse, Item Categories)
        try:
            seed_stats = seed_company_defaults(company.id, db)
            db.commit()
            logger.info(f"Company defaults seeded for company {company.id}: {seed_stats}")
        except Exception as seed_error:
            logger.warning(f"Failed to seed company defaults for company {company.id}: {seed_error}")
            # Don't fail company registration if seed fails

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
        "logo_url": company.logo_url,
        "primary_currency": company.primary_currency or "USD",
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


@router.get("/companies/currencies")
async def get_supported_currencies():
    """Get list of supported currencies"""
    return {
        "currencies": SUPPORTED_CURRENCIES
    }


@router.post("/companies/logo")
async def upload_company_logo(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Upload company logo (admin only)"""
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

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
        )

    # Validate file size (max 5MB)
    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 5MB limit"
        )

    try:
        # Create uploads directory if it doesn't exist
        upload_dir = "uploads/logos"
        os.makedirs(upload_dir, exist_ok=True)

        # Generate unique filename
        file_ext = os.path.splitext(file.filename)[1] if file.filename else ".png"
        unique_filename = f"company_{company.id}_{uuid.uuid4().hex[:8]}{file_ext}"
        file_path = os.path.join(upload_dir, unique_filename)

        # Delete old logo if exists
        if company.logo_url:
            old_path = company.logo_url.lstrip("/")
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception as e:
                    logger.warning(f"Failed to delete old logo: {e}")

        # Save new file
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Update company logo_url
        company.logo_url = f"/{file_path}"
        db.commit()

        logger.info(f"Company logo uploaded for company {company.id} by {user.email}")

        return {
            "success": True,
            "message": "Logo uploaded successfully",
            "logo_url": company.logo_url
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading company logo: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading logo: {str(e)}"
        )


@router.delete("/companies/logo")
async def delete_company_logo(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete company logo (admin only)"""
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
        # Delete file if exists
        if company.logo_url:
            old_path = company.logo_url.lstrip("/")
            if os.path.exists(old_path):
                os.remove(old_path)

        # Clear logo_url
        company.logo_url = None
        db.commit()

        logger.info(f"Company logo deleted for company {company.id} by {user.email}")

        return {
            "success": True,
            "message": "Logo deleted successfully"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting company logo: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting logo: {str(e)}"
        )


class FlushDataRequest(BaseModel):
    confirm: bool = False  # Must be True to proceed


@router.post("/companies/flush-data")
async def flush_company_data(
    request: FlushDataRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Flush all operational data for a company (admin only).

    This will DELETE:
    - Clients, Sites, Buildings, Spaces, Blocks
    - Contracts, Contract Scopes
    - Work Orders, Tickets, Calendar data
    - Technicians, Attendance, Evaluations
    - Invoices, Allocations, Petty Cash
    - Inventory (Items, Stock, Ledger, Transfers, Cycle Counts)
    - Purchase Orders, Purchase Requests
    - Accounting data (Journal Entries, Account Balances)
    - Vendors, Warehouses, Handheld Devices
    - Condition Reports, NPS Surveys
    - Assets (Equipment, Sub-equipment, Floors, Rooms)

    This will PRESERVE:
    - Company record and settings
    - User accounts
    - Plan subscription
    - PM Templates (Checklists, Activities, Equipment Classes, etc.)
    - Document Types
    - Item Categories
    - Account Types and Chart of Accounts structure
    """
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must confirm the flush operation by setting confirm=true"
        )

    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    company_id = user.company_id

    try:
        # Delete in order respecting foreign key constraints
        # Using raw SQL for efficiency and to handle complex FK relationships

        delete_queries = [
            # Purchase Order related
            ("purchase_order_invoices", "DELETE FROM purchase_order_invoices WHERE purchase_order_id IN (SELECT id FROM purchase_orders WHERE company_id = :company_id)"),
            ("purchase_order_lines", "DELETE FROM purchase_order_lines WHERE purchase_order_id IN (SELECT id FROM purchase_orders WHERE company_id = :company_id)"),
            ("purchase_orders", "DELETE FROM purchase_orders WHERE company_id = :company_id"),
            ("purchase_request_lines", "DELETE FROM purchase_request_lines WHERE purchase_request_id IN (SELECT id FROM purchase_requests WHERE company_id = :company_id)"),
            ("purchase_requests", "DELETE FROM purchase_requests WHERE company_id = :company_id"),

            # Accounting - Journal entries and balances
            ("journal_entry_lines", "DELETE FROM journal_entry_lines WHERE journal_entry_id IN (SELECT id FROM journal_entries WHERE company_id = :company_id)"),
            ("journal_entries", "DELETE FROM journal_entries WHERE company_id = :company_id"),
            ("account_balances", "DELETE FROM account_balances WHERE account_id IN (SELECT id FROM accounts WHERE company_id = :company_id)"),

            # Invoice allocations
            ("recognition_logs", "DELETE FROM recognition_logs WHERE allocation_id IN (SELECT id FROM invoice_allocations WHERE company_id = :company_id)"),
            ("allocation_periods", "DELETE FROM allocation_periods WHERE allocation_id IN (SELECT id FROM invoice_allocations WHERE company_id = :company_id)"),
            ("invoice_allocations", "DELETE FROM invoice_allocations WHERE company_id = :company_id"),

            # Petty cash
            ("petty_cash_receipts", "DELETE FROM petty_cash_receipts WHERE transaction_id IN (SELECT id FROM petty_cash_transactions WHERE fund_id IN (SELECT id FROM petty_cash_funds WHERE company_id = :company_id))"),
            ("petty_cash_replenishments", "DELETE FROM petty_cash_replenishments WHERE fund_id IN (SELECT id FROM petty_cash_funds WHERE company_id = :company_id)"),
            ("petty_cash_transactions", "DELETE FROM petty_cash_transactions WHERE fund_id IN (SELECT id FROM petty_cash_funds WHERE company_id = :company_id)"),
            ("petty_cash_funds", "DELETE FROM petty_cash_funds WHERE company_id = :company_id"),

            # NPS Surveys
            ("nps_surveys", "DELETE FROM nps_surveys WHERE company_id = :company_id"),

            # Technician evaluations
            ("technician_evaluations", "DELETE FROM technician_evaluations WHERE company_id = :company_id"),

            # Condition reports
            ("condition_report_images", "DELETE FROM condition_report_images WHERE report_id IN (SELECT id FROM condition_reports WHERE company_id = :company_id)"),
            ("condition_reports", "DELETE FROM condition_reports WHERE company_id = :company_id"),

            # Calendar and work order assignments
            ("work_order_slot_assignments", "DELETE FROM work_order_slot_assignments WHERE slot_id IN (SELECT id FROM calendar_slots WHERE company_id = :company_id)"),
            ("calendar_slots", "DELETE FROM calendar_slots WHERE company_id = :company_id"),
            ("calendar_templates", "DELETE FROM calendar_templates WHERE company_id = :company_id"),

            # Tickets
            ("tickets", "DELETE FROM tickets WHERE company_id = :company_id"),

            # Work orders and related
            ("work_order_snapshots", "DELETE FROM work_order_snapshots WHERE work_order_id IN (SELECT id FROM work_orders WHERE company_id = :company_id)"),
            ("work_order_completions", "DELETE FROM work_order_completions WHERE work_order_id IN (SELECT id FROM work_orders WHERE company_id = :company_id)"),
            ("work_order_checklist_items", "DELETE FROM work_order_checklist_items WHERE work_order_id IN (SELECT id FROM work_orders WHERE company_id = :company_id)"),
            ("work_order_time_entries", "DELETE FROM work_order_time_entries WHERE work_order_id IN (SELECT id FROM work_orders WHERE company_id = :company_id)"),
            ("work_order_spare_parts", "DELETE FROM work_order_spare_parts WHERE work_order_id IN (SELECT id FROM work_orders WHERE company_id = :company_id)"),
            ("work_orders", "DELETE FROM work_orders WHERE company_id = :company_id"),

            # PM Schedules (keep templates)
            ("pm_schedules", "DELETE FROM pm_schedules WHERE company_id = :company_id"),

            # Cycle counts
            ("cycle_count_items", "DELETE FROM cycle_count_items WHERE cycle_count_id IN (SELECT id FROM cycle_counts WHERE company_id = :company_id)"),
            ("cycle_counts", "DELETE FROM cycle_counts WHERE company_id = :company_id"),

            # Item inventory
            ("item_ledger", "DELETE FROM item_ledger WHERE company_id = :company_id"),
            ("item_transfer_lines", "DELETE FROM item_transfer_lines WHERE transfer_id IN (SELECT id FROM item_transfers WHERE company_id = :company_id)"),
            ("item_transfers", "DELETE FROM item_transfers WHERE company_id = :company_id"),
            ("item_stock", "DELETE FROM item_stock WHERE item_id IN (SELECT id FROM item_master WHERE company_id = :company_id)"),
            ("item_aliases", "DELETE FROM item_aliases WHERE item_id IN (SELECT id FROM item_master WHERE company_id = :company_id)"),
            ("item_master", "DELETE FROM item_master WHERE company_id = :company_id"),

            # Invoice items (from vendors/processed images)
            ("invoice_items", "DELETE FROM invoice_items WHERE company_id = :company_id"),

            # Spare parts
            ("spare_parts", "DELETE FROM spare_parts WHERE company_id = :company_id"),

            # Attendance
            ("technician_attendance", "DELETE FROM technician_attendance WHERE company_id = :company_id"),

            # Technician site shifts
            ("technician_site_shifts", "DELETE FROM technician_site_shifts WHERE technician_id IN (SELECT id FROM technicians WHERE company_id = :company_id)"),

            # Assets - Equipment hierarchy
            ("sub_equipment", "DELETE FROM sub_equipment WHERE equipment_id IN (SELECT id FROM equipment WHERE company_id = :company_id)"),
            ("equipment", "DELETE FROM equipment WHERE company_id = :company_id"),
            ("desks", "DELETE FROM desks WHERE room_id IN (SELECT id FROM rooms WHERE floor_id IN (SELECT id FROM floors WHERE company_id = :company_id))"),
            ("rooms", "DELETE FROM rooms WHERE floor_id IN (SELECT id FROM floors WHERE company_id = :company_id)"),
            ("units", "DELETE FROM units WHERE floor_id IN (SELECT id FROM floors WHERE company_id = :company_id)"),
            ("floors", "DELETE FROM floors WHERE company_id = :company_id"),

            # Contract scopes
            ("contract_scopes", "DELETE FROM contract_scopes WHERE contract_id IN (SELECT id FROM contracts WHERE company_id = :company_id)"),
            ("contracts", "DELETE FROM contracts WHERE company_id = :company_id"),

            # Scopes
            ("scopes", "DELETE FROM scopes WHERE company_id = :company_id"),

            # Spaces, Buildings, Blocks
            ("spaces", "DELETE FROM spaces WHERE building_id IN (SELECT id FROM buildings WHERE site_id IN (SELECT id FROM sites WHERE client_id IN (SELECT id FROM clients WHERE company_id = :company_id)))"),
            ("buildings", "DELETE FROM buildings WHERE site_id IN (SELECT id FROM sites WHERE client_id IN (SELECT id FROM clients WHERE company_id = :company_id))"),
            ("blocks", "DELETE FROM blocks WHERE site_id IN (SELECT id FROM sites WHERE client_id IN (SELECT id FROM clients WHERE company_id = :company_id))"),

            # Sites
            ("sites", "DELETE FROM sites WHERE client_id IN (SELECT id FROM clients WHERE company_id = :company_id)"),

            # Technicians
            ("technicians", "DELETE FROM technicians WHERE company_id = :company_id"),

            # Handheld devices
            ("handheld_devices", "DELETE FROM handheld_devices WHERE company_id = :company_id"),

            # Projects, Branches
            ("projects", "DELETE FROM projects WHERE company_id = :company_id"),
            ("branches", "DELETE FROM branches WHERE client_id IN (SELECT id FROM clients WHERE company_id = :company_id)"),

            # Clients
            ("clients", "DELETE FROM clients WHERE company_id = :company_id"),

            # Vendors
            ("vendors", "DELETE FROM vendors WHERE company_id = :company_id"),

            # Warehouses
            ("warehouses", "DELETE FROM warehouses WHERE company_id = :company_id"),

            # Processed images
            ("processed_images", "DELETE FROM processed_images WHERE user_id IN (SELECT id FROM users WHERE company_id = :company_id)"),

            # Exchange rate logs
            ("exchange_rate_logs", "DELETE FROM exchange_rate_logs WHERE rate_id IN (SELECT id FROM exchange_rates WHERE company_id = :company_id)"),
            ("exchange_rates", "DELETE FROM exchange_rates WHERE company_id = :company_id"),
        ]

        deleted_counts = {}

        for table_name, query in delete_queries:
            try:
                result = db.execute(text(query), {"company_id": company_id})
                deleted_counts[table_name] = result.rowcount
            except Exception as e:
                logger.warning(f"Error deleting from {table_name}: {e}")
                deleted_counts[table_name] = f"error: {str(e)}"

        db.commit()

        # Calculate total deleted
        total_deleted = sum(v for v in deleted_counts.values() if isinstance(v, int))

        logger.info(f"Company data flush completed for company {company_id} by {user.email}. Total records deleted: {total_deleted}")

        return {
            "success": True,
            "message": f"Successfully flushed all operational data. {total_deleted} records deleted.",
            "details": deleted_counts
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error flushing company data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error flushing data: {str(e)}"
        )
