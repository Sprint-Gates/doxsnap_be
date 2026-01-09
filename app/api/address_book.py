"""
Address Book API Endpoints

Address Book is the master repository for all business entities, inspired by Oracle JD Edwards F0101.
It consolidates Vendors, Clients, and Site branches into a unified structure with automatic
Business Unit creation for cost tracking.

Search Types:
- V  = Vendor (supplier)
- C  = Customer (client)
- CB = Client Branch (site/location)
- E  = Employee
- MT = Maintenance Team
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from app.database import get_db
from app.models import AddressBook, AddressBookContact, BusinessUnit, User, Client
from app.api.auth import get_current_user
from app.schemas import (
    AddressBookCreate, AddressBookUpdate, AddressBookResponse,
    AddressBookBrief, AddressBookWithChildren, AddressBookHierarchy,
    AddressBookContactCreate, AddressBookContactUpdate, AddressBookContact as AddressBookContactSchema,
    AddressBookList
)

router = APIRouter()

# Valid search types
VALID_SEARCH_TYPES = {"V", "C", "CB", "E", "MT"}

# Parent type constraints: child_type -> allowed parent types
PARENT_TYPE_CONSTRAINTS = {
    "CB": {"C"},  # Client Branch must have Customer parent
    "MT": {"C", None},  # Maintenance Team can have Customer parent or no parent
    "V": {None},  # Vendor has no parent
    "C": {None},  # Customer has no parent
    "E": {None},  # Employee has no parent
}


# =============================================================================
# Helper Functions
# =============================================================================

def generate_next_address_number(db: Session, company_id: int) -> str:
    """Generate next sequential address number for company (8-digit padded)"""
    # Find the maximum numeric address number for this company
    # We need to handle both numeric and non-numeric address numbers
    entries = db.query(AddressBook.address_number).filter(
        AddressBook.company_id == company_id
    ).all()

    max_num = 0
    for (addr_num,) in entries:
        try:
            num = int(addr_num)
            if num > max_num:
                max_num = num
        except (ValueError, TypeError):
            # Skip non-numeric address numbers
            pass

    return str(max_num + 1).zfill(8)


def validate_parent_address_book(
    db: Session,
    parent_id: int,
    company_id: int,
    child_search_type: str
) -> AddressBook:
    """Validate parent address book exists and type constraints are met"""
    parent = db.query(AddressBook).filter(
        AddressBook.id == parent_id,
        AddressBook.company_id == company_id
    ).first()

    if not parent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent Address Book entry not found"
        )

    allowed_parent_types = PARENT_TYPE_CONSTRAINTS.get(child_search_type, {None})
    if parent.search_type not in allowed_parent_types and None not in allowed_parent_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Address Book type '{child_search_type}' cannot have parent of type '{parent.search_type}'"
        )

    return parent


def build_address_book_response(ab: AddressBook) -> dict:
    """Build standardized response dict from AddressBook model"""
    # Calculate totals for salary summary
    total_allowances = sum(filter(None, [
        float(ab.transport_allowance or 0),
        float(ab.housing_allowance or 0),
        float(ab.food_allowance or 0),
        float(ab.other_allowances or 0)
    ]))

    base = float(ab.base_salary) if ab.base_salary else 0
    ss_deduction = base * float(ab.social_security_rate or 0)
    tax_deduction = base * float(ab.tax_rate or 0)
    other_ded = float(ab.other_deductions or 0)
    total_deductions = ss_deduction + tax_deduction + other_ded

    net_salary = base + total_allowances - total_deductions if base else None

    return {
        "id": ab.id,
        "company_id": ab.company_id,
        "address_number": ab.address_number,
        "search_type": ab.search_type,
        "alpha_name": ab.alpha_name,
        "mailing_name": ab.mailing_name,
        "tax_id": ab.tax_id,
        "registration_number": ab.registration_number,
        "address_line_1": ab.address_line_1,
        "address_line_2": ab.address_line_2,
        "address_line_3": ab.address_line_3,
        "address_line_4": ab.address_line_4,
        "city": ab.city,
        "state": ab.state,
        "postal_code": ab.postal_code,
        "country": ab.country,
        "phone_primary": ab.phone_primary,
        "phone_secondary": ab.phone_secondary,
        "fax": ab.fax,
        "email": ab.email,
        "website": ab.website,
        "latitude": ab.latitude,
        "longitude": ab.longitude,
        "parent_address_book_id": ab.parent_address_book_id,
        "business_unit_id": ab.business_unit_id,
        "category_code_01": ab.category_code_01,
        "category_code_02": ab.category_code_02,
        "category_code_03": ab.category_code_03,
        "category_code_04": ab.category_code_04,
        "category_code_05": ab.category_code_05,
        "category_code_06": ab.category_code_06,
        "category_code_07": ab.category_code_07,
        "category_code_08": ab.category_code_08,
        "category_code_09": ab.category_code_09,
        "category_code_10": ab.category_code_10,
        # Employee salary fields
        "salary_type": ab.salary_type,
        "base_salary": float(ab.base_salary) if ab.base_salary else None,
        "salary_currency": ab.salary_currency,
        "hourly_rate": float(ab.hourly_rate) if ab.hourly_rate else None,
        "overtime_rate_multiplier": float(ab.overtime_rate_multiplier) if ab.overtime_rate_multiplier else None,
        "working_hours_per_day": float(ab.working_hours_per_day) if ab.working_hours_per_day else None,
        "working_days_per_month": ab.working_days_per_month,
        "transport_allowance": float(ab.transport_allowance) if ab.transport_allowance else None,
        "housing_allowance": float(ab.housing_allowance) if ab.housing_allowance else None,
        "food_allowance": float(ab.food_allowance) if ab.food_allowance else None,
        "other_allowances": float(ab.other_allowances) if ab.other_allowances else None,
        "allowances_notes": ab.allowances_notes,
        "social_security_rate": float(ab.social_security_rate) if ab.social_security_rate else None,
        "tax_rate": float(ab.tax_rate) if ab.tax_rate else None,
        "other_deductions": float(ab.other_deductions) if ab.other_deductions else None,
        "deductions_notes": ab.deductions_notes,
        "employee_id": ab.employee_id,
        "specialization": ab.specialization,
        "hire_date": ab.hire_date.isoformat() if ab.hire_date else None,
        "termination_date": ab.termination_date.isoformat() if ab.termination_date else None,
        # Computed salary fields
        "total_allowances": total_allowances if total_allowances > 0 else None,
        "total_deductions": total_deductions if total_deductions > 0 else None,
        "net_salary": net_salary,
        # Other fields
        "is_active": ab.is_active,
        "notes": ab.notes,
        "legacy_vendor_id": ab.legacy_vendor_id,
        "legacy_client_id": ab.legacy_client_id,
        "legacy_site_id": ab.legacy_site_id,
        "legacy_technician_id": ab.legacy_technician_id,
        "created_by": ab.created_by,
        "updated_by": ab.updated_by,
        "created_at": ab.created_at,
        "updated_at": ab.updated_at,
        "contacts": ab.contacts if ab.contacts else [],
        "parent_name": ab.parent.alpha_name if ab.parent else None,
        "business_unit_code": ab.business_unit.code if ab.business_unit else None,
    }


def build_hierarchy_tree(entries: List[AddressBook], parent_id: Optional[int] = None) -> List[dict]:
    """Recursively build hierarchy tree from flat list of address book entries"""
    children = []
    for ab in entries:
        if ab.parent_address_book_id == parent_id:
            ab_dict = build_address_book_response(ab)
            ab_dict["children"] = build_hierarchy_tree(entries, ab.id)
            children.append(ab_dict)
    return children


# =============================================================================
# Hourly Rate Computation
# =============================================================================

def compute_hourly_rate(
    salary_type: str,
    base_salary: float,
    hourly_rate: float = None,
    working_hours_per_day: float = None,
    working_days_per_month: int = None,
    transport_allowance: float = None,
    housing_allowance: float = None,
    food_allowance: float = None,
    other_allowances: float = None
) -> float:
    """
    Automatically compute hourly rate if not provided.

    For hourly salary type: use the provided hourly_rate
    For monthly/daily salary type: calculate from base_salary + allowances

    Formula: (base_salary + all_allowances) / (working_hours_per_day * working_days_per_month)
    """
    # If hourly rate is explicitly provided, use it
    if hourly_rate and hourly_rate > 0:
        return hourly_rate

    # For hourly type without explicit rate, no computation needed
    if salary_type == "hourly":
        return hourly_rate or 0

    # For monthly/daily, compute from salary
    if not base_salary or base_salary <= 0:
        return None

    # Default working hours if not provided
    hours_per_day = working_hours_per_day or 8.0
    days_per_month = working_days_per_month or 22

    # Calculate total monthly compensation
    total_monthly = float(base_salary)
    total_monthly += float(transport_allowance or 0)
    total_monthly += float(housing_allowance or 0)
    total_monthly += float(food_allowance or 0)
    total_monthly += float(other_allowances or 0)

    # Calculate monthly hours
    monthly_hours = float(hours_per_day) * float(days_per_month)

    if monthly_hours > 0:
        return round(total_monthly / monthly_hours, 2)

    return None


# =============================================================================
# CRUD Endpoints
# =============================================================================

@router.post("/address-book", response_model=AddressBookResponse, status_code=status.HTTP_201_CREATED)
async def create_address_book_entry(
    data: AddressBookCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new Address Book entry.
    Optionally auto-creates a linked Business Unit for cost tracking.
    """
    logger.info(f"[CreateAB] Creating entry: search_type={data.search_type}, alpha_name={data.alpha_name}")
    logger.info(f"[CreateAB] salary_type={data.salary_type}, base_salary={data.base_salary}, employee_id={data.employee_id}")

    # Validate search type
    if data.search_type not in VALID_SEARCH_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid search type. Must be one of: {', '.join(VALID_SEARCH_TYPES)}"
        )

    # Generate address number if not provided
    address_number = data.address_number
    if not address_number:
        address_number = generate_next_address_number(db, current_user.company_id)

    # Check for duplicate address number
    existing = db.query(AddressBook).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.address_number == address_number
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Address Book entry with number '{address_number}' already exists"
        )

    # Validate parent if specified
    if data.parent_address_book_id:
        validate_parent_address_book(
            db, data.parent_address_book_id,
            current_user.company_id, data.search_type
        )

    # Auto-create Business Unit if requested
    business_unit_id = None
    if data.auto_create_bu:
        bu = BusinessUnit(
            company_id=current_user.company_id,
            code=address_number[:12],  # BU code max 12 chars
            name=data.alpha_name[:100],
            bu_type="profit_loss",
            description=f"Auto-created for Address Book {address_number}",
            created_by=current_user.id
        )
        db.add(bu)
        db.flush()
        business_unit_id = bu.id

    # Create the Address Book entry
    ab_entry = AddressBook(
        company_id=current_user.company_id,
        address_number=address_number,
        search_type=data.search_type,
        alpha_name=data.alpha_name,
        mailing_name=data.mailing_name,
        tax_id=data.tax_id,
        registration_number=data.registration_number,
        address_line_1=data.address_line_1,
        address_line_2=data.address_line_2,
        address_line_3=data.address_line_3,
        address_line_4=data.address_line_4,
        city=data.city,
        state=data.state,
        postal_code=data.postal_code,
        country=data.country,
        phone_primary=data.phone_primary,
        phone_secondary=data.phone_secondary,
        fax=data.fax,
        email=data.email,
        website=data.website,
        latitude=data.latitude,
        longitude=data.longitude,
        parent_address_book_id=data.parent_address_book_id,
        business_unit_id=business_unit_id,
        category_code_01=data.category_code_01,
        category_code_02=data.category_code_02,
        category_code_03=data.category_code_03,
        category_code_04=data.category_code_04,
        category_code_05=data.category_code_05,
        category_code_06=data.category_code_06,
        category_code_07=data.category_code_07,
        category_code_08=data.category_code_08,
        category_code_09=data.category_code_09,
        category_code_10=data.category_code_10,
        # Employee salary fields (for search_type='E')
        salary_type=data.salary_type,
        base_salary=data.base_salary,
        salary_currency=data.salary_currency,
        # Auto-compute hourly rate if not provided
        hourly_rate=compute_hourly_rate(
            salary_type=data.salary_type,
            base_salary=data.base_salary,
            hourly_rate=data.hourly_rate,
            working_hours_per_day=data.working_hours_per_day,
            working_days_per_month=data.working_days_per_month,
            transport_allowance=data.transport_allowance,
            housing_allowance=data.housing_allowance,
            food_allowance=data.food_allowance,
            other_allowances=data.other_allowances
        ) if data.search_type == 'E' else data.hourly_rate,
        overtime_rate_multiplier=data.overtime_rate_multiplier,
        working_hours_per_day=data.working_hours_per_day,
        working_days_per_month=data.working_days_per_month,
        transport_allowance=data.transport_allowance,
        housing_allowance=data.housing_allowance,
        food_allowance=data.food_allowance,
        other_allowances=data.other_allowances,
        allowances_notes=data.allowances_notes,
        social_security_rate=data.social_security_rate,
        tax_rate=data.tax_rate,
        other_deductions=data.other_deductions,
        deductions_notes=data.deductions_notes,
        employee_id=data.employee_id,
        specialization=data.specialization,
        hire_date=data.hire_date,
        termination_date=data.termination_date,
        notes=data.notes,
        is_active=data.is_active,
        created_by=current_user.id
    )
    db.add(ab_entry)
    db.flush()

    # Add contacts if provided
    for i, contact_data in enumerate(data.contacts or []):
        contact = AddressBookContact(
            address_book_id=ab_entry.id,
            line_number=i + 1,
            full_name=contact_data.full_name,
            first_name=contact_data.first_name,
            last_name=contact_data.last_name,
            title=contact_data.title,
            contact_type=contact_data.contact_type,
            phone_primary=contact_data.phone_primary,
            phone_mobile=contact_data.phone_mobile,
            phone_fax=contact_data.phone_fax,
            email=contact_data.email,
            preferred_contact_method=contact_data.preferred_contact_method,
            language=contact_data.language,
            is_primary=contact_data.is_primary,
            is_active=contact_data.is_active,
            notes=contact_data.notes
        )
        db.add(contact)

    # Auto-create Client record if this is a Customer (type "C")
    if data.search_type == "C":
        client = Client(
            company_id=current_user.company_id,
            name=data.alpha_name,
            code=address_number,
            email=data.email,
            phone=data.phone_primary,
            address=data.address_line_1,
            city=data.city,
            country=data.country,
            tax_number=data.tax_id,
            contact_person=data.mailing_name,
            is_active=data.is_active,
            address_book_id=ab_entry.id  # Link back to Address Book
        )
        db.add(client)
        logger.info(f"Auto-created Client '{data.alpha_name}' from Address Book entry {address_number}")

    db.commit()
    db.refresh(ab_entry)

    return build_address_book_response(ab_entry)


@router.get("/address-book", response_model=List[AddressBookResponse])
async def list_address_book_entries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    search_type: Optional[str] = Query(None, description="Filter by search type: V, C, CB, E, MT"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    parent_id: Optional[int] = Query(None, description="Filter by parent address book ID"),
    search: Optional[str] = Query(None, description="Search by name, address number, or tax ID"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """
    List all address book entries for the current company.
    Supports filtering by type, status, parent, and search.
    """
    query = db.query(AddressBook).options(
        joinedload(AddressBook.parent),
        joinedload(AddressBook.business_unit),
        joinedload(AddressBook.contacts)
    ).filter(
        AddressBook.company_id == current_user.company_id
    )

    if search_type:
        if search_type not in VALID_SEARCH_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid search type. Must be one of: {', '.join(VALID_SEARCH_TYPES)}"
            )
        query = query.filter(AddressBook.search_type == search_type)

    if is_active is not None:
        query = query.filter(AddressBook.is_active == is_active)

    if parent_id is not None:
        query = query.filter(AddressBook.parent_address_book_id == parent_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.address_number.ilike(search_term),
                AddressBook.tax_id.ilike(search_term),
                AddressBook.mailing_name.ilike(search_term)
            )
        )

    query = query.order_by(AddressBook.search_type, AddressBook.alpha_name)
    entries = query.offset(offset).limit(limit).all()

    return [build_address_book_response(ab) for ab in entries]


@router.get("/address-book/brief", response_model=List[AddressBookBrief])
async def list_address_book_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    search_type: Optional[str] = Query(None, description="Filter by search type"),
    active_only: bool = Query(True, description="Only return active entries")
):
    """
    Get brief list of address book entries for dropdowns and selectors.
    Returns minimal data for performance.
    """
    query = db.query(AddressBook).filter(
        AddressBook.company_id == current_user.company_id
    )

    if search_type:
        query = query.filter(AddressBook.search_type == search_type)

    if active_only:
        query = query.filter(AddressBook.is_active == True)

    return query.order_by(AddressBook.alpha_name).all()


@router.get("/address-book/hierarchy", response_model=AddressBookHierarchy)
async def get_address_book_hierarchy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get full hierarchy tree of address book entries organized by type.
    Returns nested structure with parent-child relationships.
    """
    entries = db.query(AddressBook).options(
        joinedload(AddressBook.parent),
        joinedload(AddressBook.business_unit),
        joinedload(AddressBook.contacts)
    ).filter(
        AddressBook.company_id == current_user.company_id
    ).order_by(AddressBook.alpha_name).all()

    # Separate by type
    vendors = [ab for ab in entries if ab.search_type == "V"]
    customers = [ab for ab in entries if ab.search_type == "C"]
    branches = [ab for ab in entries if ab.search_type == "CB"]
    employees = [ab for ab in entries if ab.search_type == "E"]
    teams = [ab for ab in entries if ab.search_type == "MT"]

    return {
        "vendors": build_hierarchy_tree(vendors),
        "customers": build_hierarchy_tree(customers + branches),  # Include branches under customers
        "branches": build_hierarchy_tree(branches),
        "employees": build_hierarchy_tree(employees),
        "teams": build_hierarchy_tree(teams)
    }


# =============================================================================
# Type-Specific Convenience Endpoints
# NOTE: These MUST come BEFORE the /{ab_id} route to avoid path conflicts
# =============================================================================

@router.get("/address-book/vendors", response_model=List[AddressBookResponse])
async def list_vendors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """List all vendors (search_type = 'V')"""
    query = db.query(AddressBook).options(
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.business_unit)
    ).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "V"
    )

    if is_active is not None:
        query = query.filter(AddressBook.is_active == is_active)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.address_number.ilike(search_term)
            )
        )

    return [build_address_book_response(ab) for ab in query.offset(offset).limit(limit).all()]


@router.get("/address-book/customers", response_model=List[AddressBookResponse])
async def list_customers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """List all customers (search_type = 'C')"""
    query = db.query(AddressBook).options(
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.business_unit)
    ).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "C"
    )

    if is_active is not None:
        query = query.filter(AddressBook.is_active == is_active)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.address_number.ilike(search_term)
            )
        )

    return [build_address_book_response(ab) for ab in query.offset(offset).limit(limit).all()]


@router.get("/address-book/branches", response_model=List[AddressBookResponse])
async def list_branches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    parent_id: Optional[int] = Query(None, description="Filter by parent customer ID"),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """List all branches (search_type = 'CB')"""
    query = db.query(AddressBook).options(
        joinedload(AddressBook.parent),
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.business_unit)
    ).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "CB"
    )

    if parent_id is not None:
        query = query.filter(AddressBook.parent_address_book_id == parent_id)

    if is_active is not None:
        query = query.filter(AddressBook.is_active == is_active)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.address_number.ilike(search_term)
            )
        )

    return [build_address_book_response(ab) for ab in query.offset(offset).limit(limit).all()]


@router.get("/address-book/employees", response_model=List[AddressBookResponse])
async def list_employees(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """List all employees (search_type = 'E')"""
    query = db.query(AddressBook).options(
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.business_unit)
    ).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "E"
    )

    if is_active is not None:
        query = query.filter(AddressBook.is_active == is_active)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.address_number.ilike(search_term)
            )
        )

    return [build_address_book_response(ab) for ab in query.offset(offset).limit(limit).all()]


@router.get("/address-book/teams", response_model=List[AddressBookResponse])
async def list_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """List all maintenance teams (search_type = 'MT')"""
    query = db.query(AddressBook).options(
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.business_unit)
    ).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == "MT"
    )

    if is_active is not None:
        query = query.filter(AddressBook.is_active == is_active)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AddressBook.alpha_name.ilike(search_term),
                AddressBook.address_number.ilike(search_term)
            )
        )

    return [build_address_book_response(ab) for ab in query.offset(offset).limit(limit).all()]


# =============================================================================
# Individual Entry Endpoints (with {ab_id} path parameter)
# NOTE: These MUST come AFTER the /vendors, /customers, etc. routes
# =============================================================================

@router.get("/address-book/{ab_id}", response_model=AddressBookWithChildren)
async def get_address_book_entry(
    ab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a single address book entry with its contacts and children.
    """
    ab = db.query(AddressBook).options(
        joinedload(AddressBook.parent),
        joinedload(AddressBook.business_unit),
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.children)
    ).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    result = build_address_book_response(ab)
    result["children"] = [build_address_book_response(child) for child in ab.children]

    return result


@router.put("/address-book/{ab_id}", response_model=AddressBookResponse)
async def update_address_book_entry(
    ab_id: int,
    data: AddressBookUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an address book entry.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    # Validate new parent if specified
    if data.parent_address_book_id is not None and data.parent_address_book_id != ab.parent_address_book_id:
        if data.parent_address_book_id:
            # Prevent circular reference
            if data.parent_address_book_id == ab.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot set entry as its own parent"
                )
            validate_parent_address_book(
                db, data.parent_address_book_id,
                current_user.company_id, ab.search_type
            )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(ab, field, value)

    # Auto-recompute hourly rate for employees if salary fields changed
    if ab.search_type == 'E':
        # Check if any salary-related field was updated
        salary_fields = {'base_salary', 'working_hours_per_day', 'working_days_per_month',
                        'transport_allowance', 'housing_allowance', 'food_allowance',
                        'other_allowances', 'salary_type'}
        if salary_fields.intersection(update_data.keys()) or 'hourly_rate' not in update_data:
            computed_rate = compute_hourly_rate(
                salary_type=ab.salary_type,
                base_salary=ab.base_salary,
                hourly_rate=ab.hourly_rate if 'hourly_rate' in update_data else None,
                working_hours_per_day=ab.working_hours_per_day,
                working_days_per_month=ab.working_days_per_month,
                transport_allowance=ab.transport_allowance,
                housing_allowance=ab.housing_allowance,
                food_allowance=ab.food_allowance,
                other_allowances=ab.other_allowances
            )
            if computed_rate is not None:
                ab.hourly_rate = computed_rate

    ab.updated_by = current_user.id
    ab.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(ab)

    return build_address_book_response(ab)


@router.patch("/address-book/{ab_id}/toggle-status", response_model=AddressBookResponse)
async def toggle_address_book_status(
    ab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Toggle the active status of an address book entry.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    ab.is_active = not ab.is_active
    ab.updated_by = current_user.id
    ab.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(ab)

    return build_address_book_response(ab)


@router.delete("/address-book/{ab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address_book_entry(
    ab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Soft delete an address book entry (sets is_active=False).
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    # Check for children
    children_count = db.query(AddressBook).filter(
        AddressBook.parent_address_book_id == ab_id
    ).count()

    if children_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete: entry has {children_count} child entries"
        )

    ab.is_active = False
    ab.updated_by = current_user.id
    ab.updated_at = datetime.utcnow()

    db.commit()


# =============================================================================
# Lookup Endpoints
# =============================================================================

@router.get("/address-book/lookup/by-name", response_model=List[AddressBookBrief])
async def lookup_by_name(
    name: str = Query(..., description="Name to search for"),
    search_type: Optional[str] = Query(None, description="Filter by search type"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(10, le=50)
):
    """
    Lookup address book entries by name (for OCR matching, autocomplete, etc.)
    """
    query = db.query(AddressBook).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.is_active == True,
        AddressBook.alpha_name.ilike(f"%{name}%")
    )

    if search_type:
        query = query.filter(AddressBook.search_type == search_type)

    return query.order_by(AddressBook.alpha_name).limit(limit).all()


@router.get("/address-book/lookup/by-tax-id", response_model=List[AddressBookBrief])
async def lookup_by_tax_id(
    tax_id: str = Query(..., description="Tax ID to search for"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lookup address book entries by tax ID.
    """
    entries = db.query(AddressBook).filter(
        AddressBook.company_id == current_user.company_id,
        AddressBook.tax_id == tax_id
    ).all()

    return entries


# =============================================================================
# Contact (Who's Who) Endpoints
# =============================================================================

@router.post("/address-book/{ab_id}/contacts", response_model=AddressBookContactSchema, status_code=status.HTTP_201_CREATED)
async def add_contact(
    ab_id: int,
    data: AddressBookContactCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Add a new contact to an address book entry.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    # Get next line number
    max_line = db.query(func.max(AddressBookContact.line_number)).filter(
        AddressBookContact.address_book_id == ab_id
    ).scalar() or 0

    contact = AddressBookContact(
        address_book_id=ab_id,
        line_number=max_line + 1,
        full_name=data.full_name,
        first_name=data.first_name,
        last_name=data.last_name,
        title=data.title,
        contact_type=data.contact_type,
        phone_primary=data.phone_primary,
        phone_mobile=data.phone_mobile,
        phone_fax=data.phone_fax,
        email=data.email,
        preferred_contact_method=data.preferred_contact_method,
        language=data.language,
        is_primary=data.is_primary,
        is_active=data.is_active,
        notes=data.notes
    )

    db.add(contact)
    db.commit()
    db.refresh(contact)

    return contact


@router.get("/address-book/{ab_id}/contacts", response_model=List[AddressBookContactSchema])
async def list_contacts(
    ab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all contacts for an address book entry.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    contacts = db.query(AddressBookContact).filter(
        AddressBookContact.address_book_id == ab_id
    ).order_by(AddressBookContact.line_number).all()

    return contacts


@router.put("/address-book/{ab_id}/contacts/{contact_id}", response_model=AddressBookContactSchema)
async def update_contact(
    ab_id: int,
    contact_id: int,
    data: AddressBookContactUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a contact.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    contact = db.query(AddressBookContact).filter(
        AddressBookContact.id == contact_id,
        AddressBookContact.address_book_id == ab_id
    ).first()

    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(contact, field, value)

    contact.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(contact)

    return contact


@router.delete("/address-book/{ab_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    ab_id: int,
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a contact.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    contact = db.query(AddressBookContact).filter(
        AddressBookContact.id == contact_id,
        AddressBookContact.address_book_id == ab_id
    ).first()

    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )

    db.delete(contact)
    db.commit()


# =============================================================================
# Children Endpoints
# =============================================================================

@router.get("/address-book/{ab_id}/children", response_model=List[AddressBookResponse])
async def get_children(
    ab_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all child entries of an address book entry.
    """
    ab = db.query(AddressBook).filter(
        AddressBook.id == ab_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not ab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address Book entry not found"
        )

    children = db.query(AddressBook).options(
        joinedload(AddressBook.contacts),
        joinedload(AddressBook.business_unit)
    ).filter(
        AddressBook.parent_address_book_id == ab_id
    ).order_by(AddressBook.alpha_name).all()

    return [build_address_book_response(child) for child in children]
