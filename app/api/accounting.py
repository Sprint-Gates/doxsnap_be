"""
Accounting Ledger API Routes
Handles Chart of Accounts, Journal Entries, Fiscal Periods, and Financial Reporting
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_, desc
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal
from app.database import get_db
from app.models import (
    User, Company, Site,
    AccountType, Account, FiscalPeriod, JournalEntry, JournalEntryLine,
    AccountBalance, DefaultAccountMapping
)
from app.schemas import (
    AccountType as AccountTypeSchema, AccountTypeCreate, AccountTypeUpdate,
    Account as AccountSchema, AccountCreate, AccountUpdate, AccountBrief, AccountWithChildren,
    FiscalPeriod as FiscalPeriodSchema, FiscalPeriodCreate, FiscalPeriodUpdate,
    JournalEntry as JournalEntrySchema, JournalEntryCreate, JournalEntryUpdate,
    JournalEntryBrief, JournalEntryList,
    DefaultAccountMapping as DefaultAccountMappingSchema,
    DefaultAccountMappingCreate, DefaultAccountMappingUpdate,
    SiteLedgerReport, SiteLedgerEntry, TrialBalanceReport, TrialBalanceRow,
    ChartOfAccountsInit, ProfitLossReport, PLSection, PLLineItem,
    BalanceSheetReport, BSSection, BSLineItem
)
from app.utils.security import verify_token
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get current authenticated user from JWT token"""
    token = credentials.credentials
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def get_company_id(user: User, db: Session) -> int:
    """Get company ID for the current user"""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    return user.company_id


def generate_entry_number(db: Session, company_id: int) -> str:
    """Generate unique journal entry number for a company"""
    year = datetime.now().year
    prefix = f"JE-{year}-"

    # Get last entry number for this year
    last_entry = db.query(JournalEntry).filter(
        JournalEntry.company_id == company_id,
        JournalEntry.entry_number.like(f"{prefix}%")
    ).order_by(desc(JournalEntry.entry_number)).first()

    if last_entry:
        try:
            last_num = int(last_entry.entry_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:06d}"


# ============================================================================
# Account Types Endpoints
# ============================================================================

@router.get("/account-types", response_model=List[AccountTypeSchema])
def list_account_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all account types for the company"""
    company_id = get_company_id(current_user, db)

    types = db.query(AccountType).filter(
        AccountType.company_id == company_id,
        AccountType.is_active == True
    ).order_by(AccountType.display_order).all()

    return types


@router.post("/account-types", response_model=AccountTypeSchema)
def create_account_type(
    account_type: AccountTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new account type"""
    company_id = get_company_id(current_user, db)

    # Check for duplicate code
    existing = db.query(AccountType).filter(
        AccountType.company_id == company_id,
        AccountType.code == account_type.code
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail=f"Account type with code '{account_type.code}' already exists")

    db_type = AccountType(
        company_id=company_id,
        **account_type.model_dump()
    )
    db.add(db_type)
    db.commit()
    db.refresh(db_type)

    return db_type


# ============================================================================
# Chart of Accounts Endpoints
# ============================================================================

@router.get("/accounts", response_model=List[AccountSchema])
def list_accounts(
    include_inactive: bool = False,
    account_type_id: Optional[int] = None,
    is_site_specific: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all accounts with optional filters"""
    company_id = get_company_id(current_user, db)

    query = db.query(Account).options(
        joinedload(Account.account_type)
    ).filter(Account.company_id == company_id)

    if not include_inactive:
        query = query.filter(Account.is_active == True)

    if account_type_id:
        query = query.filter(Account.account_type_id == account_type_id)

    if is_site_specific is not None:
        query = query.filter(Account.is_site_specific == is_site_specific)

    if search:
        query = query.filter(
            or_(
                Account.code.ilike(f"%{search}%"),
                Account.name.ilike(f"%{search}%")
            )
        )

    accounts = query.order_by(Account.code).all()
    return accounts


@router.get("/accounts/tree", response_model=List[AccountWithChildren])
def get_accounts_tree(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get accounts as a hierarchical tree structure"""
    company_id = get_company_id(current_user, db)

    accounts = db.query(Account).options(
        joinedload(Account.account_type)
    ).filter(
        Account.company_id == company_id,
        Account.is_active == True
    ).order_by(Account.code).all()

    # Build tree structure
    account_dict = {a.id: {**a.__dict__, 'children': []} for a in accounts}
    root_accounts = []

    for account in accounts:
        if account.parent_id and account.parent_id in account_dict:
            account_dict[account.parent_id]['children'].append(account_dict[account.id])
        else:
            root_accounts.append(account_dict[account.id])

    return root_accounts


@router.get("/accounts/{account_id}", response_model=AccountSchema)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single account by ID"""
    company_id = get_company_id(current_user, db)

    account = db.query(Account).options(
        joinedload(Account.account_type)
    ).filter(
        Account.id == account_id,
        Account.company_id == company_id
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return account


@router.post("/accounts", response_model=AccountSchema)
def create_account(
    account: AccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new account"""
    company_id = get_company_id(current_user, db)

    # Validate account type exists
    account_type = db.query(AccountType).filter(
        AccountType.id == account.account_type_id,
        AccountType.company_id == company_id
    ).first()

    if not account_type:
        raise HTTPException(status_code=400, detail="Invalid account type")

    # Check for duplicate code
    existing = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == account.code
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail=f"Account with code '{account.code}' already exists")

    # Validate parent if specified
    if account.parent_id:
        parent = db.query(Account).filter(
            Account.id == account.parent_id,
            Account.company_id == company_id
        ).first()
        if not parent:
            raise HTTPException(status_code=400, detail="Parent account not found")

    db_account = Account(
        company_id=company_id,
        created_by=current_user.id,
        **account.model_dump()
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)

    return db_account


@router.put("/accounts/{account_id}", response_model=AccountSchema)
def update_account(
    account_id: int,
    account: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an existing account"""
    company_id = get_company_id(current_user, db)

    db_account = db.query(Account).filter(
        Account.id == account_id,
        Account.company_id == company_id
    ).first()

    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")

    if db_account.is_system:
        raise HTTPException(status_code=400, detail="Cannot modify system account")

    update_data = account.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_account, field, value)

    db.commit()
    db.refresh(db_account)

    return db_account


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete (deactivate) an account"""
    company_id = get_company_id(current_user, db)

    account = db.query(Account).filter(
        Account.id == account_id,
        Account.company_id == company_id
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if account.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system account")

    # Check if account has transactions
    has_transactions = db.query(JournalEntryLine).filter(
        JournalEntryLine.account_id == account_id
    ).first()

    if has_transactions:
        # Soft delete - just deactivate
        account.is_active = False
        db.commit()
        return {"message": "Account deactivated (has transactions)"}

    # Hard delete if no transactions
    db.delete(account)
    db.commit()

    return {"message": "Account deleted"}


# ============================================================================
# Fiscal Periods Endpoints
# ============================================================================

@router.get("/fiscal-periods", response_model=List[FiscalPeriodSchema])
def list_fiscal_periods(
    fiscal_year: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List fiscal periods"""
    company_id = get_company_id(current_user, db)

    query = db.query(FiscalPeriod).filter(FiscalPeriod.company_id == company_id)

    if fiscal_year:
        query = query.filter(FiscalPeriod.fiscal_year == fiscal_year)

    if status:
        query = query.filter(FiscalPeriod.status == status)

    periods = query.order_by(FiscalPeriod.fiscal_year.desc(), FiscalPeriod.period_number).all()
    return periods


@router.post("/fiscal-periods/generate")
def generate_fiscal_periods(
    fiscal_year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate 12 monthly fiscal periods for a year"""
    company_id = get_company_id(current_user, db)

    # Check if periods already exist
    existing = db.query(FiscalPeriod).filter(
        FiscalPeriod.company_id == company_id,
        FiscalPeriod.fiscal_year == fiscal_year
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail=f"Fiscal periods for {fiscal_year} already exist")

    import calendar
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    periods = []
    for month_num in range(1, 13):
        last_day = calendar.monthrange(fiscal_year, month_num)[1]
        period = FiscalPeriod(
            company_id=company_id,
            fiscal_year=fiscal_year,
            period_number=month_num,
            period_name=f"{months[month_num - 1]} {fiscal_year}",
            start_date=date(fiscal_year, month_num, 1),
            end_date=date(fiscal_year, month_num, last_day),
            status="open"
        )
        db.add(period)
        periods.append(period)

    db.commit()

    return {"message": f"Generated 12 fiscal periods for {fiscal_year}", "count": 12}


@router.post("/fiscal-periods/{period_id}/close")
def close_fiscal_period(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Close a fiscal period"""
    company_id = get_company_id(current_user, db)

    period = db.query(FiscalPeriod).filter(
        FiscalPeriod.id == period_id,
        FiscalPeriod.company_id == company_id
    ).first()

    if not period:
        raise HTTPException(status_code=404, detail="Fiscal period not found")

    if period.status == "closed":
        raise HTTPException(status_code=400, detail="Period is already closed")

    # Check for unposted entries in this period
    unposted = db.query(JournalEntry).filter(
        JournalEntry.company_id == company_id,
        JournalEntry.fiscal_period_id == period_id,
        JournalEntry.status == "draft"
    ).count()

    if unposted > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot close period: {unposted} unposted journal entries exist"
        )

    period.status = "closed"
    period.closed_at = datetime.utcnow()
    period.closed_by = current_user.id

    db.commit()

    return {"message": f"Period '{period.period_name}' closed successfully"}


# ============================================================================
# Journal Entries Endpoints
# ============================================================================

@router.get("/journal-entries", response_model=JournalEntryList)
def list_journal_entries(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    site_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List journal entries with pagination and filters"""
    company_id = get_company_id(current_user, db)

    query = db.query(JournalEntry).filter(JournalEntry.company_id == company_id)

    if status:
        query = query.filter(JournalEntry.status == status)

    if source_type:
        query = query.filter(JournalEntry.source_type == source_type)

    if start_date:
        query = query.filter(JournalEntry.entry_date >= start_date)

    if end_date:
        query = query.filter(JournalEntry.entry_date <= end_date)

    if site_id:
        # Filter entries that have lines for this site
        query = query.join(JournalEntryLine).filter(JournalEntryLine.site_id == site_id)

    if search:
        query = query.filter(
            or_(
                JournalEntry.entry_number.ilike(f"%{search}%"),
                JournalEntry.description.ilike(f"%{search}%"),
                JournalEntry.reference.ilike(f"%{search}%")
            )
        )

    total = query.count()

    entries = query.order_by(
        desc(JournalEntry.entry_date),
        desc(JournalEntry.entry_number)
    ).offset((page - 1) * size).limit(size).all()

    return JournalEntryList(
        entries=[JournalEntryBrief.model_validate(e) for e in entries],
        total=total,
        page=page,
        size=size
    )


@router.get("/journal-entries/{entry_id}", response_model=JournalEntrySchema)
def get_journal_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single journal entry with all lines"""
    company_id = get_company_id(current_user, db)

    entry = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines).joinedload(JournalEntryLine.account)
    ).filter(
        JournalEntry.id == entry_id,
        JournalEntry.company_id == company_id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    return entry


@router.post("/journal-entries", response_model=JournalEntrySchema)
def create_journal_entry(
    entry: JournalEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new journal entry with lines"""
    company_id = get_company_id(current_user, db)

    # Validate lines exist
    if not entry.lines or len(entry.lines) < 2:
        raise HTTPException(status_code=400, detail="Journal entry must have at least 2 lines")

    # Calculate totals
    total_debit = sum(Decimal(str(line.debit)) for line in entry.lines)
    total_credit = sum(Decimal(str(line.credit)) for line in entry.lines)

    # Validate balance
    if total_debit != total_credit:
        raise HTTPException(
            status_code=400,
            detail=f"Entry does not balance. Debits: {total_debit}, Credits: {total_credit}"
        )

    # Validate each line has either debit or credit (not both, not neither)
    for i, line in enumerate(entry.lines):
        if line.debit > 0 and line.credit > 0:
            raise HTTPException(status_code=400, detail=f"Line {i+1}: Cannot have both debit and credit")
        if line.debit == 0 and line.credit == 0:
            raise HTTPException(status_code=400, detail=f"Line {i+1}: Must have either debit or credit")

        # Validate account exists
        account = db.query(Account).filter(
            Account.id == line.account_id,
            Account.company_id == company_id,
            Account.is_header == False
        ).first()
        if not account:
            raise HTTPException(status_code=400, detail=f"Line {i+1}: Invalid account ID {line.account_id}")

    # Find fiscal period
    fiscal_period = db.query(FiscalPeriod).filter(
        FiscalPeriod.company_id == company_id,
        FiscalPeriod.start_date <= entry.entry_date,
        FiscalPeriod.end_date >= entry.entry_date
    ).first()

    if fiscal_period and fiscal_period.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot post to a closed fiscal period")

    # Generate entry number
    entry_number = generate_entry_number(db, company_id)

    # Create entry
    db_entry = JournalEntry(
        company_id=company_id,
        entry_number=entry_number,
        entry_date=entry.entry_date,
        description=entry.description,
        reference=entry.reference,
        source_type=entry.source_type,
        source_id=entry.source_id,
        source_number=entry.source_number,
        fiscal_period_id=fiscal_period.id if fiscal_period else None,
        total_debit=float(total_debit),
        total_credit=float(total_credit),
        status="draft",
        created_by=current_user.id
    )
    db.add(db_entry)
    db.flush()

    # Create lines
    for i, line in enumerate(entry.lines):
        db_line = JournalEntryLine(
            journal_entry_id=db_entry.id,
            account_id=line.account_id,
            debit=line.debit,
            credit=line.credit,
            description=line.description,
            site_id=line.site_id,
            contract_id=line.contract_id,
            work_order_id=line.work_order_id,
            vendor_id=line.vendor_id,
            project_id=line.project_id,
            technician_id=line.technician_id,
            line_number=i + 1
        )
        db.add(db_line)

    db.commit()
    db.refresh(db_entry)

    # Reload with relationships
    return get_journal_entry(db_entry.id, db, current_user)


@router.post("/journal-entries/{entry_id}/post")
def post_journal_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Post a draft journal entry"""
    company_id = get_company_id(current_user, db)

    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.company_id == company_id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.status != "draft":
        raise HTTPException(status_code=400, detail=f"Cannot post entry with status '{entry.status}'")

    # Check fiscal period
    if entry.fiscal_period_id:
        period = db.query(FiscalPeriod).filter(FiscalPeriod.id == entry.fiscal_period_id).first()
        if period and period.status == "closed":
            raise HTTPException(status_code=400, detail="Cannot post to a closed fiscal period")

    entry.status = "posted"
    entry.posted_at = datetime.utcnow()
    entry.posted_by = current_user.id

    # Update account balances
    update_account_balances(db, entry)

    db.commit()

    return {"message": "Journal entry posted successfully", "entry_number": entry.entry_number}


@router.post("/journal-entries/{entry_id}/reverse")
def reverse_journal_entry(
    entry_id: int,
    reversal_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a reversal entry for a posted journal entry"""
    company_id = get_company_id(current_user, db)

    original = db.query(JournalEntry).options(
        joinedload(JournalEntry.lines)
    ).filter(
        JournalEntry.id == entry_id,
        JournalEntry.company_id == company_id
    ).first()

    if not original:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if original.status != "posted":
        raise HTTPException(status_code=400, detail="Can only reverse posted entries")

    if original.reversed_by_id:
        raise HTTPException(status_code=400, detail="Entry has already been reversed")

    rev_date = reversal_date or date.today()

    # Find fiscal period for reversal
    fiscal_period = db.query(FiscalPeriod).filter(
        FiscalPeriod.company_id == company_id,
        FiscalPeriod.start_date <= rev_date,
        FiscalPeriod.end_date >= rev_date
    ).first()

    if fiscal_period and fiscal_period.status == "closed":
        raise HTTPException(status_code=400, detail="Cannot post reversal to a closed fiscal period")

    # Create reversal entry
    reversal_number = generate_entry_number(db, company_id)

    reversal = JournalEntry(
        company_id=company_id,
        entry_number=reversal_number,
        entry_date=rev_date,
        description=f"Reversal of {original.entry_number}: {original.description}",
        reference=original.reference,
        source_type="reversal",
        source_id=original.id,
        source_number=original.entry_number,
        fiscal_period_id=fiscal_period.id if fiscal_period else None,
        total_debit=original.total_credit,  # Swap
        total_credit=original.total_debit,  # Swap
        status="posted",
        is_auto_generated=True,
        is_reversal=True,
        reversal_of_id=original.id,
        posted_at=datetime.utcnow(),
        posted_by=current_user.id,
        created_by=current_user.id
    )
    db.add(reversal)
    db.flush()

    # Create reversed lines (swap debit/credit)
    for orig_line in original.lines:
        rev_line = JournalEntryLine(
            journal_entry_id=reversal.id,
            account_id=orig_line.account_id,
            debit=orig_line.credit,  # Swap
            credit=orig_line.debit,  # Swap
            description=f"Reversal: {orig_line.description or ''}",
            site_id=orig_line.site_id,
            contract_id=orig_line.contract_id,
            work_order_id=orig_line.work_order_id,
            vendor_id=orig_line.vendor_id,
            project_id=orig_line.project_id,
            technician_id=orig_line.technician_id,
            line_number=orig_line.line_number
        )
        db.add(rev_line)

    # Mark original as reversed
    original.reversed_by_id = reversal.id

    # Update account balances
    update_account_balances(db, reversal)

    db.commit()

    return {
        "message": "Journal entry reversed successfully",
        "original_entry": original.entry_number,
        "reversal_entry": reversal.entry_number
    }


def update_account_balances(db: Session, entry: JournalEntry):
    """Update account balances when an entry is posted"""
    if not entry.fiscal_period_id:
        return

    for line in entry.lines:
        # Get or create balance record
        balance = db.query(AccountBalance).filter(
            AccountBalance.company_id == entry.company_id,
            AccountBalance.account_id == line.account_id,
            AccountBalance.fiscal_period_id == entry.fiscal_period_id,
            AccountBalance.site_id == line.site_id
        ).first()

        if not balance:
            balance = AccountBalance(
                company_id=entry.company_id,
                account_id=line.account_id,
                fiscal_period_id=entry.fiscal_period_id,
                site_id=line.site_id,
                period_debit=0,
                period_credit=0,
                opening_balance=0,
                closing_balance=0
            )
            db.add(balance)

        balance.period_debit = float(Decimal(str(balance.period_debit)) + Decimal(str(line.debit)))
        balance.period_credit = float(Decimal(str(balance.period_credit)) + Decimal(str(line.credit)))

        # Get account's normal balance
        account = db.query(Account).options(
            joinedload(Account.account_type)
        ).filter(Account.id == line.account_id).first()

        if account and account.account_type:
            if account.account_type.normal_balance == "debit":
                balance.closing_balance = float(
                    Decimal(str(balance.opening_balance)) +
                    Decimal(str(balance.period_debit)) -
                    Decimal(str(balance.period_credit))
                )
            else:
                balance.closing_balance = float(
                    Decimal(str(balance.opening_balance)) +
                    Decimal(str(balance.period_credit)) -
                    Decimal(str(balance.period_debit))
                )


# ============================================================================
# Default Account Mappings Endpoints
# ============================================================================

@router.get("/account-mappings", response_model=List[DefaultAccountMappingSchema])
def list_account_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all default account mappings"""
    company_id = get_company_id(current_user, db)

    mappings = db.query(DefaultAccountMapping).options(
        joinedload(DefaultAccountMapping.debit_account),
        joinedload(DefaultAccountMapping.credit_account)
    ).filter(
        DefaultAccountMapping.company_id == company_id
    ).order_by(DefaultAccountMapping.transaction_type).all()

    return mappings


@router.post("/account-mappings", response_model=DefaultAccountMappingSchema)
def create_account_mapping(
    mapping: DefaultAccountMappingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a default account mapping"""
    company_id = get_company_id(current_user, db)

    # Check for duplicate
    existing = db.query(DefaultAccountMapping).filter(
        DefaultAccountMapping.company_id == company_id,
        DefaultAccountMapping.transaction_type == mapping.transaction_type,
        DefaultAccountMapping.category == mapping.category
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Mapping already exists for this transaction type/category")

    db_mapping = DefaultAccountMapping(
        company_id=company_id,
        **mapping.model_dump()
    )
    db.add(db_mapping)
    db.commit()
    db.refresh(db_mapping)

    return db_mapping


@router.put("/account-mappings/{mapping_id}", response_model=DefaultAccountMappingSchema)
def update_account_mapping(
    mapping_id: int,
    mapping: DefaultAccountMappingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an account mapping"""
    company_id = get_company_id(current_user, db)

    db_mapping = db.query(DefaultAccountMapping).filter(
        DefaultAccountMapping.id == mapping_id,
        DefaultAccountMapping.company_id == company_id
    ).first()

    if not db_mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    update_data = mapping.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_mapping, field, value)

    db.commit()
    db.refresh(db_mapping)

    return db_mapping


# ============================================================================
# Reports Endpoints
# ============================================================================

@router.get("/reports/site-ledger/{site_id}", response_model=SiteLedgerReport)
def get_site_ledger(
    site_id: int,
    start_date: date,
    end_date: date,
    account_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get ledger report for a specific site"""
    company_id = get_company_id(current_user, db)

    # Verify site belongs to company
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Get all posted entries for this site in date range
    query = db.query(JournalEntryLine).join(JournalEntry).join(Account).filter(
        JournalEntry.company_id == company_id,
        JournalEntry.status == "posted",
        JournalEntry.entry_date >= start_date,
        JournalEntry.entry_date <= end_date,
        JournalEntryLine.site_id == site_id
    )

    if account_id:
        query = query.filter(JournalEntryLine.account_id == account_id)

    lines = query.order_by(JournalEntry.entry_date, JournalEntry.entry_number).all()

    # Calculate opening balance (sum of all entries before start_date)
    opening_query = db.query(
        func.sum(JournalEntryLine.debit).label('total_debit'),
        func.sum(JournalEntryLine.credit).label('total_credit')
    ).join(JournalEntry).filter(
        JournalEntry.company_id == company_id,
        JournalEntry.status == "posted",
        JournalEntry.entry_date < start_date,
        JournalEntryLine.site_id == site_id
    )

    if account_id:
        opening_query = opening_query.filter(JournalEntryLine.account_id == account_id)

    opening = opening_query.first()
    opening_debit = float(opening.total_debit or 0)
    opening_credit = float(opening.total_credit or 0)
    opening_balance = opening_debit - opening_credit

    # Build entries list
    entries = []
    running_balance = opening_balance
    total_debits = 0
    total_credits = 0

    for line in lines:
        entry = line.journal_entry
        account = line.account

        running_balance += float(line.debit) - float(line.credit)
        total_debits += float(line.debit)
        total_credits += float(line.credit)

        entries.append(SiteLedgerEntry(
            entry_date=entry.entry_date,
            entry_number=entry.entry_number,
            description=line.description or entry.description,
            account_code=account.code,
            account_name=account.name,
            debit=float(line.debit),
            credit=float(line.credit),
            balance=running_balance,
            source_type=entry.source_type,
            source_number=entry.source_number
        ))

    return SiteLedgerReport(
        site_id=site_id,
        site_name=site.name,
        site_code=site.code,
        period_start=start_date,
        period_end=end_date,
        opening_balance=opening_balance,
        total_debits=total_debits,
        total_credits=total_credits,
        closing_balance=running_balance,
        entries=entries
    )


@router.get("/reports/trial-balance", response_model=TrialBalanceReport)
def get_trial_balance(
    as_of_date: date,
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get trial balance as of a specific date"""
    company_id = get_company_id(current_user, db)

    # Get all accounts with their balances
    query = db.query(
        Account.id,
        Account.code,
        Account.name,
        AccountType.code.label('type_code'),
        AccountType.normal_balance,
        func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
        func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
    ).join(
        AccountType, Account.account_type_id == AccountType.id
    ).outerjoin(
        JournalEntryLine, Account.id == JournalEntryLine.account_id
    ).outerjoin(
        JournalEntry, and_(
            JournalEntryLine.journal_entry_id == JournalEntry.id,
            JournalEntry.status == "posted",
            JournalEntry.entry_date <= as_of_date
        )
    ).filter(
        Account.company_id == company_id,
        Account.is_active == True,
        Account.is_header == False
    )

    if site_id:
        query = query.filter(
            or_(
                JournalEntryLine.site_id == site_id,
                JournalEntryLine.site_id == None
            )
        )

    query = query.group_by(
        Account.id, Account.code, Account.name,
        AccountType.code, AccountType.normal_balance
    ).order_by(Account.code)

    results = query.all()

    rows = []
    total_debit = 0
    total_credit = 0

    for row in results:
        debit = float(row.total_debit)
        credit = float(row.total_credit)

        # Calculate balance based on normal balance
        if row.normal_balance == "debit":
            balance = debit - credit
            if balance >= 0:
                row_debit = balance
                row_credit = 0
            else:
                row_debit = 0
                row_credit = abs(balance)
        else:
            balance = credit - debit
            if balance >= 0:
                row_debit = 0
                row_credit = balance
            else:
                row_debit = abs(balance)
                row_credit = 0

        if row_debit != 0 or row_credit != 0:
            rows.append(TrialBalanceRow(
                account_id=row.id,
                account_code=row.code,
                account_name=row.name,
                account_type=row.type_code,
                debit=row_debit,
                credit=row_credit
            ))
            total_debit += row_debit
            total_credit += row_credit

    site_name = None
    if site_id:
        site = db.query(Site).filter(Site.id == site_id).first()
        site_name = site.name if site else None

    return TrialBalanceReport(
        as_of_date=as_of_date,
        site_id=site_id,
        site_name=site_name,
        rows=rows,
        total_debit=total_debit,
        total_credit=total_credit
    )


@router.get("/reports/profit-loss", response_model=ProfitLossReport)
def get_profit_loss(
    start_date: date,
    end_date: date,
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get Profit & Loss (Income Statement) report for a date range"""
    company_id = get_company_id(current_user, db)

    # Get all account types to identify revenue vs expense
    account_types = {
        at.code: at.id for at in db.query(AccountType).filter(
            AccountType.company_id == company_id
        ).all()
    }

    revenue_type_id = account_types.get("REVENUE")
    expense_type_id = account_types.get("EXPENSE")

    if not revenue_type_id or not expense_type_id:
        raise HTTPException(status_code=400, detail="Chart of accounts not properly initialized")

    # Helper to get account balances by type
    def get_account_balances(account_type_id: int, parent_codes: list = None):
        query = db.query(
            Account.id,
            Account.code,
            Account.name,
            Account.parent_id,
            func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
            func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
        ).outerjoin(
            JournalEntryLine, Account.id == JournalEntryLine.account_id
        ).outerjoin(
            JournalEntry, and_(
                JournalEntryLine.journal_entry_id == JournalEntry.id,
                JournalEntry.status == "posted",
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date
            )
        ).filter(
            Account.company_id == company_id,
            Account.account_type_id == account_type_id,
            Account.is_active == True,
            Account.is_header == False
        )

        if site_id:
            query = query.filter(
                or_(
                    JournalEntryLine.site_id == site_id,
                    JournalEntryLine.site_id == None
                )
            )

        # Filter by parent codes if specified (for expense subcategories)
        if parent_codes:
            parent_accounts = db.query(Account.id).filter(
                Account.company_id == company_id,
                Account.code.in_(parent_codes)
            ).all()
            parent_ids = [p.id for p in parent_accounts]
            if parent_ids:
                query = query.filter(Account.parent_id.in_(parent_ids))

        query = query.group_by(
            Account.id, Account.code, Account.name, Account.parent_id
        ).order_by(Account.code)

        return query.all()

    # Get parent account codes for categorization
    direct_cost_parent = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "5100"  # Direct Costs header
    ).first()

    operating_exp_parent = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "5200"  # Operating Expenses header
    ).first()

    admin_exp_parent = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "5300"  # Administrative Expenses header
    ).first()

    # Get Revenue accounts
    revenue_results = get_account_balances(revenue_type_id)
    revenue_items = []
    total_revenue = 0.0

    for row in revenue_results:
        # Revenue has credit normal balance, so amount = credit - debit
        amount = float(row.total_credit) - float(row.total_debit)
        if amount != 0:
            revenue_items.append(PLLineItem(
                account_id=row.id,
                account_code=row.code,
                account_name=row.name,
                amount=amount,
                percentage=0.0  # Calculate after getting total
            ))
            total_revenue += amount

    # Update percentages for revenue
    for item in revenue_items:
        if total_revenue > 0:
            item.percentage = round((item.amount / total_revenue) * 100, 2)

    # Get Direct Cost / Cost of Sales accounts (parent code 5100)
    cost_items = []
    total_cost_of_sales = 0.0

    if direct_cost_parent:
        cost_query = db.query(
            Account.id,
            Account.code,
            Account.name,
            func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
            func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
        ).outerjoin(
            JournalEntryLine, Account.id == JournalEntryLine.account_id
        ).outerjoin(
            JournalEntry, and_(
                JournalEntryLine.journal_entry_id == JournalEntry.id,
                JournalEntry.status == "posted",
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date
            )
        ).filter(
            Account.company_id == company_id,
            Account.parent_id == direct_cost_parent.id,
            Account.is_active == True,
            Account.is_header == False
        )

        if site_id:
            cost_query = cost_query.filter(
                or_(
                    JournalEntryLine.site_id == site_id,
                    JournalEntryLine.site_id == None
                )
            )

        cost_results = cost_query.group_by(
            Account.id, Account.code, Account.name
        ).order_by(Account.code).all()

        for row in cost_results:
            # Expenses have debit normal balance, so amount = debit - credit
            amount = float(row.total_debit) - float(row.total_credit)
            if amount != 0:
                cost_items.append(PLLineItem(
                    account_id=row.id,
                    account_code=row.code,
                    account_name=row.name,
                    amount=amount,
                    percentage=round((amount / total_revenue) * 100, 2) if total_revenue > 0 else 0.0
                ))
                total_cost_of_sales += amount

    # Calculate Gross Profit
    gross_profit = total_revenue - total_cost_of_sales
    gross_profit_margin = round((gross_profit / total_revenue) * 100, 2) if total_revenue > 0 else 0.0

    # Get Operating Expenses (parent codes 5200 and 5300)
    operating_items = []
    total_operating_expenses = 0.0

    parent_ids = []
    if operating_exp_parent:
        parent_ids.append(operating_exp_parent.id)
    if admin_exp_parent:
        parent_ids.append(admin_exp_parent.id)

    if parent_ids:
        opex_query = db.query(
            Account.id,
            Account.code,
            Account.name,
            func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
            func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
        ).outerjoin(
            JournalEntryLine, Account.id == JournalEntryLine.account_id
        ).outerjoin(
            JournalEntry, and_(
                JournalEntryLine.journal_entry_id == JournalEntry.id,
                JournalEntry.status == "posted",
                JournalEntry.entry_date >= start_date,
                JournalEntry.entry_date <= end_date
            )
        ).filter(
            Account.company_id == company_id,
            Account.parent_id.in_(parent_ids),
            Account.is_active == True,
            Account.is_header == False
        )

        if site_id:
            opex_query = opex_query.filter(
                or_(
                    JournalEntryLine.site_id == site_id,
                    JournalEntryLine.site_id == None
                )
            )

        opex_results = opex_query.group_by(
            Account.id, Account.code, Account.name
        ).order_by(Account.code).all()

        for row in opex_results:
            amount = float(row.total_debit) - float(row.total_credit)
            if amount != 0:
                operating_items.append(PLLineItem(
                    account_id=row.id,
                    account_code=row.code,
                    account_name=row.name,
                    amount=amount,
                    percentage=round((amount / total_revenue) * 100, 2) if total_revenue > 0 else 0.0
                ))
                total_operating_expenses += amount

    # Calculate Net Income
    net_income = gross_profit - total_operating_expenses
    net_profit_margin = round((net_income / total_revenue) * 100, 2) if total_revenue > 0 else 0.0

    # Get site name if filtered
    site_name = None
    if site_id:
        site = db.query(Site).filter(Site.id == site_id).first()
        site_name = site.name if site else None

    return ProfitLossReport(
        start_date=start_date,
        end_date=end_date,
        site_id=site_id,
        site_name=site_name,
        revenue=PLSection(
            name="Revenue",
            items=revenue_items,
            total=total_revenue
        ),
        total_revenue=total_revenue,
        cost_of_sales=PLSection(
            name="Cost of Sales",
            items=cost_items,
            total=total_cost_of_sales
        ),
        total_cost_of_sales=total_cost_of_sales,
        gross_profit=gross_profit,
        gross_profit_margin=gross_profit_margin,
        operating_expenses=PLSection(
            name="Operating Expenses",
            items=operating_items,
            total=total_operating_expenses
        ),
        total_operating_expenses=total_operating_expenses,
        net_income=net_income,
        net_profit_margin=net_profit_margin
    )


@router.get("/reports/balance-sheet", response_model=BalanceSheetReport)
def get_balance_sheet(
    as_of_date: date,
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get Balance Sheet report as of a specific date"""
    company_id = get_company_id(current_user, db)

    # Get all account types
    account_types = {
        at.code: at.id for at in db.query(AccountType).filter(
            AccountType.company_id == company_id
        ).all()
    }

    asset_type_id = account_types.get("ASSET")
    liability_type_id = account_types.get("LIABILITY")
    equity_type_id = account_types.get("EQUITY")
    revenue_type_id = account_types.get("REVENUE")
    expense_type_id = account_types.get("EXPENSE")

    if not all([asset_type_id, liability_type_id, equity_type_id]):
        raise HTTPException(status_code=400, detail="Chart of accounts not properly initialized")

    # Helper to get account balances
    def get_account_balances(account_type_id: int, parent_code: str = None):
        query = db.query(
            Account.id,
            Account.code,
            Account.name,
            Account.parent_id,
            AccountType.normal_balance,
            func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
            func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
        ).join(
            AccountType, Account.account_type_id == AccountType.id
        ).outerjoin(
            JournalEntryLine, Account.id == JournalEntryLine.account_id
        ).outerjoin(
            JournalEntry, and_(
                JournalEntryLine.journal_entry_id == JournalEntry.id,
                JournalEntry.status == "posted",
                JournalEntry.entry_date <= as_of_date
            )
        ).filter(
            Account.company_id == company_id,
            Account.account_type_id == account_type_id,
            Account.is_active == True,
            Account.is_header == False
        )

        if site_id:
            query = query.filter(
                or_(
                    JournalEntryLine.site_id == site_id,
                    JournalEntryLine.site_id == None
                )
            )

        if parent_code:
            parent = db.query(Account).filter(
                Account.company_id == company_id,
                Account.code == parent_code
            ).first()
            if parent:
                query = query.filter(Account.parent_id == parent.id)

        query = query.group_by(
            Account.id, Account.code, Account.name, Account.parent_id, AccountType.normal_balance
        ).order_by(Account.code)

        return query.all()

    def calculate_balance(row):
        """Calculate balance based on normal balance type"""
        if row.normal_balance == "debit":
            return float(row.total_debit) - float(row.total_credit)
        else:
            return float(row.total_credit) - float(row.total_debit)

    # Get Current Assets (parent code 1100)
    current_asset_results = get_account_balances(asset_type_id, "1100")
    current_asset_items = []
    total_current_assets = 0.0

    for row in current_asset_results:
        balance = calculate_balance(row)
        if balance != 0:
            current_asset_items.append(BSLineItem(
                account_id=row.id,
                account_code=row.code,
                account_name=row.name,
                balance=balance
            ))
            total_current_assets += balance

    # Get Fixed Assets (parent code 1200)
    fixed_asset_results = get_account_balances(asset_type_id, "1200")
    fixed_asset_items = []
    total_fixed_assets = 0.0

    for row in fixed_asset_results:
        balance = calculate_balance(row)
        if balance != 0:
            fixed_asset_items.append(BSLineItem(
                account_id=row.id,
                account_code=row.code,
                account_name=row.name,
                balance=balance
            ))
            total_fixed_assets += balance

    total_assets = total_current_assets + total_fixed_assets

    # Get Current Liabilities (parent code 2100)
    liability_results = get_account_balances(liability_type_id, "2100")
    liability_items = []
    total_current_liabilities = 0.0

    for row in liability_results:
        balance = calculate_balance(row)
        if balance != 0:
            liability_items.append(BSLineItem(
                account_id=row.id,
                account_code=row.code,
                account_name=row.name,
                balance=balance
            ))
            total_current_liabilities += balance

    total_liabilities = total_current_liabilities

    # Get Equity accounts (parent code 3000)
    equity_results = get_account_balances(equity_type_id, "3000")
    equity_items = []
    retained_earnings = 0.0

    for row in equity_results:
        balance = calculate_balance(row)
        if balance != 0:
            equity_items.append(BSLineItem(
                account_id=row.id,
                account_code=row.code,
                account_name=row.name,
                balance=balance
            ))
            # Track retained earnings specifically
            if row.code == "3100":
                retained_earnings = balance

    # Calculate current period earnings (Revenue - Expenses for current period)
    # Get start of current fiscal year
    current_year_start = date(as_of_date.year, 1, 1)

    # Revenue for current period
    revenue_query = db.query(
        func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit'),
        func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit')
    ).join(
        Account, JournalEntryLine.account_id == Account.id
    ).join(
        JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
    ).filter(
        Account.company_id == company_id,
        Account.account_type_id == revenue_type_id,
        JournalEntry.status == "posted",
        JournalEntry.entry_date >= current_year_start,
        JournalEntry.entry_date <= as_of_date
    )

    if site_id:
        revenue_query = revenue_query.filter(
            or_(
                JournalEntryLine.site_id == site_id,
                JournalEntryLine.site_id == None
            )
        )

    revenue_result = revenue_query.first()
    total_revenue = float(revenue_result.total_credit or 0) - float(revenue_result.total_debit or 0)

    # Expenses for current period
    expense_query = db.query(
        func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
        func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
    ).join(
        Account, JournalEntryLine.account_id == Account.id
    ).join(
        JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id
    ).filter(
        Account.company_id == company_id,
        Account.account_type_id == expense_type_id,
        JournalEntry.status == "posted",
        JournalEntry.entry_date >= current_year_start,
        JournalEntry.entry_date <= as_of_date
    )

    if site_id:
        expense_query = expense_query.filter(
            or_(
                JournalEntryLine.site_id == site_id,
                JournalEntryLine.site_id == None
            )
        )

    expense_result = expense_query.first()
    total_expenses = float(expense_result.total_debit or 0) - float(expense_result.total_credit or 0)

    current_period_earnings = total_revenue - total_expenses

    # Calculate total equity
    equity_from_accounts = sum(item.balance for item in equity_items)
    total_equity = equity_from_accounts + current_period_earnings

    # Calculate total liabilities and equity
    total_liabilities_and_equity = total_liabilities + total_equity

    # Check if balanced
    is_balanced = abs(total_assets - total_liabilities_and_equity) < 0.01

    # Get site name if filtered
    site_name = None
    if site_id:
        site = db.query(Site).filter(Site.id == site_id).first()
        site_name = site.name if site else None

    return BalanceSheetReport(
        as_of_date=as_of_date,
        site_id=site_id,
        site_name=site_name,
        current_assets=BSSection(
            name="Current Assets",
            items=current_asset_items,
            total=total_current_assets
        ),
        total_current_assets=total_current_assets,
        fixed_assets=BSSection(
            name="Fixed Assets",
            items=fixed_asset_items,
            total=total_fixed_assets
        ),
        total_fixed_assets=total_fixed_assets,
        total_assets=total_assets,
        current_liabilities=BSSection(
            name="Current Liabilities",
            items=liability_items,
            total=total_current_liabilities
        ),
        total_current_liabilities=total_current_liabilities,
        total_liabilities=total_liabilities,
        equity=BSSection(
            name="Equity",
            items=equity_items,
            total=equity_from_accounts
        ),
        retained_earnings=retained_earnings,
        current_period_earnings=current_period_earnings,
        total_equity=total_equity,
        total_liabilities_and_equity=total_liabilities_and_equity,
        is_balanced=is_balanced
    )


# ============================================================================
# Chart of Accounts Initialization
# ============================================================================

@router.post("/initialize-chart-of-accounts")
def initialize_chart_of_accounts(
    init: ChartOfAccountsInit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Initialize default chart of accounts for a company"""
    company_id = get_company_id(current_user, db)

    # Check if already initialized
    existing = db.query(Account).filter(Account.company_id == company_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Chart of accounts already initialized")

    # Create account types
    account_types_data = [
        {"code": "ASSET", "name": "Assets", "normal_balance": "debit", "display_order": 1},
        {"code": "LIABILITY", "name": "Liabilities", "normal_balance": "credit", "display_order": 2},
        {"code": "EQUITY", "name": "Equity", "normal_balance": "credit", "display_order": 3},
        {"code": "REVENUE", "name": "Revenue", "normal_balance": "credit", "display_order": 4},
        {"code": "EXPENSE", "name": "Expenses", "normal_balance": "debit", "display_order": 5},
    ]

    type_map = {}
    for type_data in account_types_data:
        at = AccountType(company_id=company_id, **type_data)
        db.add(at)
        db.flush()
        type_map[type_data["code"]] = at.id

    # Default chart of accounts for property/facility management
    accounts_data = [
        # Assets
        {"code": "1000", "name": "Assets", "type": "ASSET", "is_header": True},
        {"code": "1100", "name": "Current Assets", "type": "ASSET", "is_header": True, "parent": "1000"},
        {"code": "1110", "name": "Cash and Bank", "type": "ASSET", "is_bank_account": True, "parent": "1100"},
        {"code": "1120", "name": "Petty Cash Funds", "type": "ASSET", "is_bank_account": True, "parent": "1100"},
        {"code": "1130", "name": "VAT Input (Receivable)", "type": "ASSET", "parent": "1100"},
        {"code": "1140", "name": "Spare Parts Inventory", "type": "ASSET", "parent": "1100"},
        {"code": "1150", "name": "Prepaid Expenses", "type": "ASSET", "parent": "1100"},
        {"code": "1200", "name": "Fixed Assets", "type": "ASSET", "is_header": True, "parent": "1000"},
        {"code": "1210", "name": "Tools and Equipment", "type": "ASSET", "parent": "1200"},
        {"code": "1220", "name": "Vehicles", "type": "ASSET", "parent": "1200"},
        {"code": "1290", "name": "Accumulated Depreciation", "type": "ASSET", "parent": "1200"},

        # Liabilities
        {"code": "2000", "name": "Liabilities", "type": "LIABILITY", "is_header": True},
        {"code": "2100", "name": "Current Liabilities", "type": "LIABILITY", "is_header": True, "parent": "2000"},
        {"code": "2110", "name": "Accounts Payable", "type": "LIABILITY", "is_control_account": True, "parent": "2100"},
        {"code": "2120", "name": "VAT Output (Payable)", "type": "LIABILITY", "parent": "2100"},
        {"code": "2130", "name": "Accrued Labor", "type": "LIABILITY", "parent": "2100"},
        {"code": "2140", "name": "Accrued Expenses", "type": "LIABILITY", "parent": "2100"},

        # Equity
        {"code": "3000", "name": "Equity", "type": "EQUITY", "is_header": True},
        {"code": "3100", "name": "Retained Earnings", "type": "EQUITY", "parent": "3000"},
        {"code": "3200", "name": "Current Year Earnings", "type": "EQUITY", "parent": "3000"},

        # Revenue
        {"code": "4000", "name": "Revenue", "type": "REVENUE", "is_header": True},
        {"code": "4100", "name": "Service Revenue", "type": "REVENUE", "is_site_specific": True, "parent": "4000"},
        {"code": "4200", "name": "Billable Work Orders", "type": "REVENUE", "is_site_specific": True, "parent": "4000"},
        {"code": "4300", "name": "Contract Revenue", "type": "REVENUE", "is_site_specific": True, "parent": "4000"},

        # Expenses
        {"code": "5000", "name": "Expenses", "type": "EXPENSE", "is_header": True},
        {"code": "5100", "name": "Direct Costs", "type": "EXPENSE", "is_header": True, "parent": "5000"},
        {"code": "5110", "name": "Labor Cost", "type": "EXPENSE", "is_site_specific": True, "parent": "5100"},
        {"code": "5120", "name": "Spare Parts Cost", "type": "EXPENSE", "is_site_specific": True, "parent": "5100"},
        {"code": "5130", "name": "Subcontractor Cost", "type": "EXPENSE", "is_site_specific": True, "parent": "5100"},
        {"code": "5140", "name": "Equipment Rental", "type": "EXPENSE", "is_site_specific": True, "parent": "5100"},
        {"code": "5200", "name": "Operating Expenses", "type": "EXPENSE", "is_header": True, "parent": "5000"},
        {"code": "5210", "name": "Transport Expense", "type": "EXPENSE", "is_site_specific": True, "parent": "5200"},
        {"code": "5220", "name": "Supplies Expense", "type": "EXPENSE", "is_site_specific": True, "parent": "5200"},
        {"code": "5230", "name": "Utilities Expense", "type": "EXPENSE", "is_site_specific": True, "parent": "5200"},
        {"code": "5240", "name": "Meals Expense", "type": "EXPENSE", "is_site_specific": True, "parent": "5200"},
        {"code": "5250", "name": "Tools Expense", "type": "EXPENSE", "is_site_specific": True, "parent": "5200"},
        {"code": "5300", "name": "Administrative Expenses", "type": "EXPENSE", "is_header": True, "parent": "5000"},
        {"code": "5310", "name": "Office Supplies", "type": "EXPENSE", "parent": "5300"},
        {"code": "5320", "name": "Insurance", "type": "EXPENSE", "parent": "5300"},
        {"code": "5330", "name": "Depreciation Expense", "type": "EXPENSE", "parent": "5300"},
    ]

    # Create accounts
    code_to_id = {}
    for acct_data in accounts_data:
        parent_id = None
        if "parent" in acct_data:
            parent_id = code_to_id.get(acct_data["parent"])

        account = Account(
            company_id=company_id,
            code=acct_data["code"],
            name=acct_data["name"],
            account_type_id=type_map[acct_data["type"]],
            parent_id=parent_id,
            is_header=acct_data.get("is_header", False),
            is_site_specific=acct_data.get("is_site_specific", False),
            is_bank_account=acct_data.get("is_bank_account", False),
            is_control_account=acct_data.get("is_control_account", False),
            is_system=True,
            created_by=current_user.id
        )
        db.add(account)
        db.flush()
        code_to_id[acct_data["code"]] = account.id

    # Create default account mappings
    mappings_data = [
        {"transaction_type": "invoice_expense", "category": "service", "debit": "5130", "credit": "2110", "desc": "Subcontractor invoice"},
        {"transaction_type": "invoice_expense", "category": "spare_parts", "debit": "1140", "credit": "2110", "desc": "Spare parts purchase"},
        {"transaction_type": "invoice_expense", "category": "expense", "debit": "5220", "credit": "2110", "desc": "General expense invoice"},
        {"transaction_type": "invoice_expense", "category": "equipment", "debit": "1210", "credit": "2110", "desc": "Equipment purchase"},
        {"transaction_type": "invoice_expense", "category": "utilities", "debit": "5230", "credit": "2110", "desc": "Utilities invoice"},
        {"transaction_type": "invoice_vat", "category": None, "debit": "1130", "credit": "2110", "desc": "VAT on invoice"},
        {"transaction_type": "work_order_labor", "category": None, "debit": "5110", "credit": "2130", "desc": "Work order labor cost"},
        {"transaction_type": "work_order_parts", "category": None, "debit": "5120", "credit": "1140", "desc": "Work order parts usage"},
        {"transaction_type": "petty_cash_expense", "category": "supplies", "debit": "5220", "credit": "1120", "desc": "Petty cash - supplies"},
        {"transaction_type": "petty_cash_expense", "category": "transport", "debit": "5210", "credit": "1120", "desc": "Petty cash - transport"},
        {"transaction_type": "petty_cash_expense", "category": "meals", "debit": "5240", "credit": "1120", "desc": "Petty cash - meals"},
        {"transaction_type": "petty_cash_expense", "category": "tools", "debit": "5250", "credit": "1120", "desc": "Petty cash - tools"},
        {"transaction_type": "petty_cash_expense", "category": "materials", "debit": "5120", "credit": "1120", "desc": "Petty cash - materials"},
        {"transaction_type": "petty_cash_replenishment", "category": None, "debit": "1120", "credit": "1110", "desc": "Petty cash replenishment"},
    ]

    for map_data in mappings_data:
        mapping = DefaultAccountMapping(
            company_id=company_id,
            transaction_type=map_data["transaction_type"],
            category=map_data["category"],
            debit_account_id=code_to_id.get(map_data["debit"]),
            credit_account_id=code_to_id.get(map_data["credit"]),
            description=map_data["desc"],
            is_active=True
        )
        db.add(mapping)

    db.commit()

    return {
        "message": "Chart of accounts initialized successfully",
        "account_types_created": len(account_types_data),
        "accounts_created": len(accounts_data),
        "mappings_created": len(mappings_data)
    }
