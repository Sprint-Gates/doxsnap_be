"""
Business Unit API Endpoints

Business Unit is the smallest accounting unit in the ERP system, inspired by Oracle JD Edwards.
It represents the "where" portion of an account and enables proper cost center tracking
across all accounting entries.

Key concepts:
- Each BU belongs to exactly one company
- Supports hierarchy via parent_id (up to 9 levels)
- Two types: balance_sheet (assets/liabilities/equity) and profit_loss (revenue/expenses)
- Warehouses are linked to BUs for inventory-accounting integration
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_
from typing import Optional, List
from datetime import date, datetime

from app.database import get_db
from app.models import BusinessUnit, User, Warehouse, JournalEntryLine, JournalEntry, Account
from app.api.auth import get_current_user
from app.schemas import (
    BusinessUnitCreate, BusinessUnitUpdate, BusinessUnit as BusinessUnitSchema,
    BusinessUnitBrief, BusinessUnitWithChildren, BusinessUnitHierarchy,
    BusinessUnitLedgerEntry, BusinessUnitLedgerReport, BusinessUnitSummary
)

router = APIRouter()


# =============================================================================
# Helper Functions
# =============================================================================

def build_hierarchy_tree(business_units: List[BusinessUnit], parent_id: Optional[int] = None) -> List[dict]:
    """Recursively build hierarchy tree from flat list of BUs"""
    children = []
    for bu in business_units:
        if bu.parent_id == parent_id:
            bu_dict = {
                "id": bu.id,
                "company_id": bu.company_id,
                "code": bu.code,
                "name": bu.name,
                "description": bu.description,
                "parent_id": bu.parent_id,
                "level_of_detail": bu.level_of_detail,
                "bu_type": bu.bu_type,
                "model_flag": bu.model_flag or "",
                "posting_edit": bu.posting_edit or "",
                "is_adjustment_only": bu.is_adjustment_only,
                "is_active": bu.is_active,
                "subsequent_bu_id": bu.subsequent_bu_id,
                "address": bu.address,
                "city": bu.city,
                "state": bu.state,
                "country": bu.country,
                "category_code_01": bu.category_code_01,
                "category_code_02": bu.category_code_02,
                "category_code_03": bu.category_code_03,
                "category_code_04": bu.category_code_04,
                "category_code_05": bu.category_code_05,
                "category_code_06": bu.category_code_06,
                "category_code_07": bu.category_code_07,
                "category_code_08": bu.category_code_08,
                "category_code_09": bu.category_code_09,
                "category_code_10": bu.category_code_10,
                "created_by": bu.created_by,
                "created_at": bu.created_at,
                "updated_at": bu.updated_at,
                "parent_name": bu.parent.name if bu.parent else None,
                "warehouse_count": len(bu.warehouses) if hasattr(bu, 'warehouses') else 0,
                "children": build_hierarchy_tree(business_units, bu.id)
            }
            children.append(bu_dict)
    return children


def validate_bu_code(code: str) -> str:
    """Validate and normalize BU code to uppercase, max 12 chars"""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business Unit code is required"
        )
    code = code.strip().upper()[:12]
    if len(code) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business Unit code must be at least 1 character"
        )
    return code


# =============================================================================
# CRUD Endpoints
# =============================================================================

@router.get("/business-units", response_model=List[BusinessUnitSchema])
async def list_business_units(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    bu_type: Optional[str] = Query(None, description="Filter by type: balance_sheet or profit_loss"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    parent_id: Optional[int] = Query(None, description="Filter by parent BU"),
    search: Optional[str] = Query(None, description="Search by code or name"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """
    List all business units for the current company.
    Supports filtering by type, status, parent, and search.
    """
    query = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == current_user.company_id
    )

    if bu_type:
        query = query.filter(BusinessUnit.bu_type == bu_type)

    if is_active is not None:
        query = query.filter(BusinessUnit.is_active == is_active)

    if parent_id is not None:
        query = query.filter(BusinessUnit.parent_id == parent_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                BusinessUnit.code.ilike(search_term),
                BusinessUnit.name.ilike(search_term)
            )
        )

    query = query.order_by(BusinessUnit.bu_type, BusinessUnit.level_of_detail, BusinessUnit.code)
    business_units = query.offset(offset).limit(limit).all()

    return business_units


@router.get("/business-units/brief", response_model=List[BusinessUnitBrief])
async def list_business_units_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    bu_type: Optional[str] = Query(None, description="Filter by type"),
    active_only: bool = Query(True, description="Only return active BUs")
):
    """
    Get brief list of business units for dropdowns and selectors.
    Returns minimal data for performance.
    """
    query = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == current_user.company_id
    )

    if bu_type:
        query = query.filter(BusinessUnit.bu_type == bu_type)

    if active_only:
        query = query.filter(BusinessUnit.is_active == True)
        query = query.filter(or_(BusinessUnit.posting_edit == "", BusinessUnit.posting_edit == None))

    return query.order_by(BusinessUnit.code).all()


@router.get("/business-units/hierarchy", response_model=BusinessUnitHierarchy)
async def get_business_unit_hierarchy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get full hierarchy tree of business units organized by type.
    Returns nested structure with parent-child relationships.
    """
    business_units = db.query(BusinessUnit).options(
        joinedload(BusinessUnit.parent),
        joinedload(BusinessUnit.warehouses)
    ).filter(
        BusinessUnit.company_id == current_user.company_id
    ).order_by(BusinessUnit.level_of_detail, BusinessUnit.code).all()

    # Separate by type
    bs_units = [bu for bu in business_units if bu.bu_type == "balance_sheet"]
    pl_units = [bu for bu in business_units if bu.bu_type == "profit_loss"]

    return {
        "company_id": current_user.company_id,
        "total_business_units": len(business_units),
        "balance_sheet_units": build_hierarchy_tree(bs_units),
        "profit_loss_units": build_hierarchy_tree(pl_units)
    }


@router.post("/business-units", response_model=BusinessUnitSchema, status_code=status.HTTP_201_CREATED)
async def create_business_unit(
    bu_data: BusinessUnitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new business unit.
    Code must be unique within the company.
    """
    # Validate and normalize code
    code = validate_bu_code(bu_data.code)

    # Check for duplicate code
    existing = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == current_user.company_id,
        BusinessUnit.code == code
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Business Unit with code '{code}' already exists"
        )

    # Validate parent if specified
    if bu_data.parent_id:
        parent = db.query(BusinessUnit).filter(
            BusinessUnit.id == bu_data.parent_id,
            BusinessUnit.company_id == current_user.company_id
        ).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent Business Unit not found"
            )
        # Ensure child level is greater than parent
        if bu_data.level_of_detail <= parent.level_of_detail:
            bu_data.level_of_detail = parent.level_of_detail + 1

    # Create BU
    business_unit = BusinessUnit(
        company_id=current_user.company_id,
        code=code,
        name=bu_data.name,
        description=bu_data.description,
        parent_id=bu_data.parent_id,
        level_of_detail=bu_data.level_of_detail,
        bu_type=bu_data.bu_type,
        model_flag=bu_data.model_flag or "",
        posting_edit=bu_data.posting_edit or "",
        is_adjustment_only=bu_data.is_adjustment_only,
        is_active=bu_data.is_active,
        subsequent_bu_id=bu_data.subsequent_bu_id,
        address=bu_data.address,
        city=bu_data.city,
        state=bu_data.state,
        country=bu_data.country,
        category_code_01=bu_data.category_code_01,
        category_code_02=bu_data.category_code_02,
        category_code_03=bu_data.category_code_03,
        category_code_04=bu_data.category_code_04,
        category_code_05=bu_data.category_code_05,
        category_code_06=bu_data.category_code_06,
        category_code_07=bu_data.category_code_07,
        category_code_08=bu_data.category_code_08,
        category_code_09=bu_data.category_code_09,
        category_code_10=bu_data.category_code_10,
        created_by=current_user.id
    )

    db.add(business_unit)
    db.commit()
    db.refresh(business_unit)

    return business_unit


@router.get("/business-units/{bu_id}", response_model=BusinessUnitWithChildren)
async def get_business_unit(
    bu_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a single business unit with its children.
    """
    bu = db.query(BusinessUnit).options(
        joinedload(BusinessUnit.parent),
        joinedload(BusinessUnit.children),
        joinedload(BusinessUnit.warehouses)
    ).filter(
        BusinessUnit.id == bu_id,
        BusinessUnit.company_id == current_user.company_id
    ).first()

    if not bu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business Unit not found"
        )

    # Build response with children
    result = {
        "id": bu.id,
        "company_id": bu.company_id,
        "code": bu.code,
        "name": bu.name,
        "description": bu.description,
        "parent_id": bu.parent_id,
        "level_of_detail": bu.level_of_detail,
        "bu_type": bu.bu_type,
        "model_flag": bu.model_flag or "",
        "posting_edit": bu.posting_edit or "",
        "is_adjustment_only": bu.is_adjustment_only,
        "is_active": bu.is_active,
        "subsequent_bu_id": bu.subsequent_bu_id,
        "address": bu.address,
        "city": bu.city,
        "state": bu.state,
        "country": bu.country,
        "category_code_01": bu.category_code_01,
        "category_code_02": bu.category_code_02,
        "category_code_03": bu.category_code_03,
        "category_code_04": bu.category_code_04,
        "category_code_05": bu.category_code_05,
        "category_code_06": bu.category_code_06,
        "category_code_07": bu.category_code_07,
        "category_code_08": bu.category_code_08,
        "category_code_09": bu.category_code_09,
        "category_code_10": bu.category_code_10,
        "created_by": bu.created_by,
        "created_at": bu.created_at,
        "updated_at": bu.updated_at,
        "parent_name": bu.parent.name if bu.parent else None,
        "warehouse_count": len(bu.warehouses) if bu.warehouses else 0,
        "children": [
            {
                "id": child.id,
                "company_id": child.company_id,
                "code": child.code,
                "name": child.name,
                "description": child.description,
                "parent_id": child.parent_id,
                "level_of_detail": child.level_of_detail,
                "bu_type": child.bu_type,
                "model_flag": child.model_flag or "",
                "posting_edit": child.posting_edit or "",
                "is_adjustment_only": child.is_adjustment_only,
                "is_active": child.is_active,
                "subsequent_bu_id": child.subsequent_bu_id,
                "address": child.address,
                "city": child.city,
                "state": child.state,
                "country": child.country,
                "category_code_01": child.category_code_01,
                "category_code_02": child.category_code_02,
                "category_code_03": child.category_code_03,
                "category_code_04": child.category_code_04,
                "category_code_05": child.category_code_05,
                "category_code_06": child.category_code_06,
                "category_code_07": child.category_code_07,
                "category_code_08": child.category_code_08,
                "category_code_09": child.category_code_09,
                "category_code_10": child.category_code_10,
                "created_by": child.created_by,
                "created_at": child.created_at,
                "updated_at": child.updated_at,
                "parent_name": bu.name,
                "warehouse_count": 0,
                "children": []
            }
            for child in bu.children
        ]
    }

    return result


@router.put("/business-units/{bu_id}", response_model=BusinessUnitSchema)
async def update_business_unit(
    bu_id: int,
    bu_data: BusinessUnitUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a business unit.
    Code cannot be changed after creation.
    """
    bu = db.query(BusinessUnit).filter(
        BusinessUnit.id == bu_id,
        BusinessUnit.company_id == current_user.company_id
    ).first()

    if not bu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business Unit not found"
        )

    # Validate parent if changing
    if bu_data.parent_id is not None and bu_data.parent_id != bu.parent_id:
        if bu_data.parent_id == bu.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Business Unit cannot be its own parent"
            )
        if bu_data.parent_id != 0:  # 0 means remove parent
            parent = db.query(BusinessUnit).filter(
                BusinessUnit.id == bu_data.parent_id,
                BusinessUnit.company_id == current_user.company_id
            ).first()
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent Business Unit not found"
                )

    # Update fields
    update_data = bu_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "parent_id" and value == 0:
            setattr(bu, field, None)
        else:
            setattr(bu, field, value)

    db.commit()
    db.refresh(bu)

    return bu


@router.delete("/business-units/{bu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business_unit(
    bu_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a business unit.
    Cannot delete if:
    - Has posted journal entries
    - Has child business units
    - Has linked warehouses
    """
    bu = db.query(BusinessUnit).filter(
        BusinessUnit.id == bu_id,
        BusinessUnit.company_id == current_user.company_id
    ).first()

    if not bu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business Unit not found"
        )

    # Check for children
    has_children = db.query(BusinessUnit).filter(
        BusinessUnit.parent_id == bu_id
    ).first()
    if has_children:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete Business Unit with child units. Delete or reassign children first."
        )

    # Check for linked warehouses
    has_warehouses = db.query(Warehouse).filter(
        Warehouse.business_unit_id == bu_id
    ).first()
    if has_warehouses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete Business Unit with linked warehouses. Unlink warehouses first."
        )

    # Check for journal entries
    has_entries = db.query(JournalEntryLine).filter(
        JournalEntryLine.business_unit_id == bu_id
    ).first()
    if has_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete Business Unit with posted journal entries. Deactivate instead."
        )

    db.delete(bu)
    db.commit()

    return None


# =============================================================================
# Warehouse Linkage
# =============================================================================

@router.post("/business-units/{bu_id}/link-warehouse/{warehouse_id}")
async def link_warehouse_to_bu(
    bu_id: int,
    warehouse_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Link a warehouse to a business unit.
    All inventory transactions for this warehouse will post to this BU.
    """
    bu = db.query(BusinessUnit).filter(
        BusinessUnit.id == bu_id,
        BusinessUnit.company_id == current_user.company_id
    ).first()

    if not bu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business Unit not found"
        )

    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found"
        )

    warehouse.business_unit_id = bu_id
    db.commit()

    return {"message": f"Warehouse '{warehouse.name}' linked to Business Unit '{bu.code}'"}


@router.post("/business-units/{bu_id}/unlink-warehouse/{warehouse_id}")
async def unlink_warehouse_from_bu(
    bu_id: int,
    warehouse_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Unlink a warehouse from a business unit.
    """
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == current_user.company_id,
        Warehouse.business_unit_id == bu_id
    ).first()

    if not warehouse:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Warehouse not found or not linked to this Business Unit"
        )

    warehouse.business_unit_id = None
    db.commit()

    return {"message": f"Warehouse '{warehouse.name}' unlinked from Business Unit"}


# =============================================================================
# Reports
# =============================================================================

@router.get("/business-units/{bu_id}/ledger", response_model=BusinessUnitLedgerReport)
async def get_business_unit_ledger(
    bu_id: int,
    start_date: date = Query(..., description="Start date for the report"),
    end_date: date = Query(..., description="End date for the report"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get ledger report for a business unit showing all journal entries.
    Similar to Site Ledger but for Business Units.
    """
    bu = db.query(BusinessUnit).filter(
        BusinessUnit.id == bu_id,
        BusinessUnit.company_id == current_user.company_id
    ).first()

    if not bu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business Unit not found"
        )

    # Get all journal entry lines for this BU
    lines = db.query(JournalEntryLine).join(
        JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
    ).join(
        Account, JournalEntryLine.account_id == Account.id
    ).filter(
        JournalEntry.company_id == current_user.company_id,
        JournalEntry.status == "posted",
        JournalEntryLine.business_unit_id == bu_id,
        JournalEntry.entry_date >= start_date,
        JournalEntry.entry_date <= end_date
    ).order_by(JournalEntry.entry_date, JournalEntry.entry_number).all()

    # Calculate totals
    total_debits = sum(float(line.debit or 0) for line in lines)
    total_credits = sum(float(line.credit or 0) for line in lines)

    # Get opening balance (sum of all entries before start_date)
    opening_result = db.query(
        func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
        func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
    ).join(
        JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
    ).filter(
        JournalEntry.company_id == current_user.company_id,
        JournalEntry.status == "posted",
        JournalEntryLine.business_unit_id == bu_id,
        JournalEntry.entry_date < start_date
    ).first()

    opening_balance = float(opening_result.total_debit or 0) - float(opening_result.total_credit or 0)
    closing_balance = opening_balance + total_debits - total_credits

    # Build entries
    entries = []
    for line in lines:
        je = line.journal_entry
        entries.append(BusinessUnitLedgerEntry(
            entry_date=je.entry_date,
            entry_number=je.entry_number,
            account_code=line.account.code,
            account_name=line.account.name,
            description=line.description or je.description,
            debit=float(line.debit or 0),
            credit=float(line.credit or 0),
            source_type=je.source_type,
            source_number=je.source_number
        ))

    return BusinessUnitLedgerReport(
        business_unit_id=bu.id,
        business_unit_code=bu.code,
        business_unit_name=bu.name,
        bu_type=bu.bu_type,
        start_date=start_date,
        end_date=end_date,
        opening_balance=opening_balance,
        total_debits=total_debits,
        total_credits=total_credits,
        closing_balance=closing_balance,
        entries=entries
    )


@router.get("/business-units/summary/all", response_model=List[BusinessUnitSummary])
async def get_all_business_units_summary(
    as_of_date: Optional[date] = Query(None, description="Calculate balances as of this date"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get summary of all business units with their balances and transaction counts.
    """
    if not as_of_date:
        as_of_date = date.today()

    business_units = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == current_user.company_id,
        BusinessUnit.is_active == True
    ).all()

    summaries = []
    for bu in business_units:
        # Get totals
        totals = db.query(
            func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
            func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit'),
            func.count(JournalEntryLine.id).label('transaction_count')
        ).join(
            JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
        ).filter(
            JournalEntry.company_id == current_user.company_id,
            JournalEntry.status == "posted",
            JournalEntryLine.business_unit_id == bu.id,
            JournalEntry.entry_date <= as_of_date
        ).first()

        # Get warehouse count
        warehouse_count = db.query(func.count(Warehouse.id)).filter(
            Warehouse.business_unit_id == bu.id
        ).scalar() or 0

        total_debits = float(totals.total_debit or 0)
        total_credits = float(totals.total_credit or 0)

        summaries.append(BusinessUnitSummary(
            id=bu.id,
            code=bu.code,
            name=bu.name,
            bu_type=bu.bu_type,
            total_debits=total_debits,
            total_credits=total_credits,
            net_balance=total_debits - total_credits,
            warehouse_count=warehouse_count,
            transaction_count=totals.transaction_count or 0
        ))

    return summaries


# =============================================================================
# Setup / Migration Helpers
# =============================================================================

@router.post("/business-units/setup-defaults")
async def setup_default_business_units(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create default business units for a company if none exist.
    Creates:
    - One balance sheet BU (code: CORP)
    - One profit/loss BU (code: MAIN)
    """
    existing = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == current_user.company_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business Units already exist for this company"
        )

    # Create balance sheet BU
    bs_bu = BusinessUnit(
        company_id=current_user.company_id,
        code="CORP",
        name="Corporate (Balance Sheet)",
        description="Default balance sheet business unit for assets, liabilities, and equity",
        bu_type="balance_sheet",
        level_of_detail=1,
        created_by=current_user.id
    )

    # Create profit/loss BU
    pl_bu = BusinessUnit(
        company_id=current_user.company_id,
        code="MAIN",
        name="Main Operations (P&L)",
        description="Default profit/loss business unit for revenue and expenses",
        bu_type="profit_loss",
        level_of_detail=1,
        created_by=current_user.id
    )

    db.add(bs_bu)
    db.add(pl_bu)
    db.commit()

    # Link all existing warehouses to the balance sheet BU
    db.query(Warehouse).filter(
        Warehouse.company_id == current_user.company_id,
        Warehouse.business_unit_id == None
    ).update({"business_unit_id": bs_bu.id})
    db.commit()

    return {
        "message": "Default business units created",
        "balance_sheet_bu": {"id": bs_bu.id, "code": bs_bu.code, "name": bs_bu.name},
        "profit_loss_bu": {"id": pl_bu.id, "code": pl_bu.code, "name": pl_bu.name},
        "warehouses_linked": True
    }
