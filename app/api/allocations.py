from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional, List
from datetime import date, datetime, timedelta
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field
from app.database import get_db
from app.models import (
    InvoiceAllocation, AllocationPeriod, ProcessedImage, Contract, User, RecognitionLog,
    Site, Project, Client, Account
)
from app.services.journal_posting import JournalPostingService
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


# ============================================================================
# Pydantic Schemas
# ============================================================================

class AllocationCreate(BaseModel):
    invoice_id: int
    # Allocation target - exactly one must be set
    contract_id: Optional[int] = None
    site_id: Optional[int] = None
    project_id: Optional[int] = None
    total_amount: float
    distribution_type: str = Field(default="one_time", pattern="^(one_time|monthly|quarterly|custom)$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    number_of_periods: Optional[int] = Field(default=1, ge=1)
    notes: Optional[str] = None


class AllocationUpdate(BaseModel):
    distribution_type: Optional[str] = Field(default=None, pattern="^(one_time|monthly|quarterly|custom)$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    number_of_periods: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|cancelled|completed)$")


class RecognizePeriodRequest(BaseModel):
    reference: Optional[str] = Field(None, max_length=100, description="External reference (payment voucher, check #)")
    notes: Optional[str] = Field(None, description="Comments/reason for recognition")


class AllocationPeriodResponse(BaseModel):
    id: int
    period_start: date
    period_end: date
    period_number: int
    amount: float
    is_recognized: bool
    recognized_at: Optional[datetime] = None
    recognition_number: Optional[str] = None
    recognition_reference: Optional[str] = None
    recognition_notes: Optional[str] = None
    recognized_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class AllocationResponse(BaseModel):
    id: int
    invoice_id: int
    # Allocation target
    contract_id: Optional[int] = None
    site_id: Optional[int] = None
    project_id: Optional[int] = None
    allocation_type: str = "contract"  # contract, site, project
    total_amount: float
    distribution_type: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    number_of_periods: int
    status: str
    notes: Optional[str] = None
    created_at: datetime
    periods: List[AllocationPeriodResponse] = []
    # Related data
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    contract_name: Optional[str] = None
    contract_number: Optional[str] = None
    site_name: Optional[str] = None
    project_name: Optional[str] = None
    client_name: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================================
# Helper Functions
# ============================================================================

def calculate_periods(
    total_amount: Decimal,
    distribution_type: str,
    start_date: date,
    end_date: date,
    number_of_periods: int
) -> List[dict]:
    """
    Calculate period amounts based on distribution type.
    Returns a list of period dictionaries with start_date, end_date, period_number, and amount.
    """
    periods = []

    if distribution_type == "one_time":
        # Single period covering the entire range
        periods.append({
            "period_start": start_date,
            "period_end": end_date,
            "period_number": 1,
            "amount": total_amount
        })
    elif distribution_type == "monthly":
        # Calculate number of months
        months = 0
        current = start_date
        while current < end_date:
            months += 1
            current += relativedelta(months=1)

        if months == 0:
            months = 1

        # Distribute amount evenly across months
        period_amount = total_amount / months
        current = start_date

        for i in range(months):
            period_end = min(current + relativedelta(months=1) - timedelta(days=1), end_date)
            periods.append({
                "period_start": current,
                "period_end": period_end,
                "period_number": i + 1,
                "amount": round(period_amount, 2)
            })
            current = current + relativedelta(months=1)

        # Adjust last period to account for rounding
        if periods:
            total_allocated = sum(p["amount"] for p in periods[:-1])
            periods[-1]["amount"] = round(float(total_amount) - float(total_allocated), 2)

    elif distribution_type == "quarterly":
        # Calculate number of quarters
        quarters = 0
        current = start_date
        while current < end_date:
            quarters += 1
            current += relativedelta(months=3)

        if quarters == 0:
            quarters = 1

        # Distribute amount evenly across quarters
        period_amount = total_amount / quarters
        current = start_date

        for i in range(quarters):
            period_end = min(current + relativedelta(months=3) - timedelta(days=1), end_date)
            periods.append({
                "period_start": current,
                "period_end": period_end,
                "period_number": i + 1,
                "amount": round(period_amount, 2)
            })
            current = current + relativedelta(months=3)

        # Adjust last period to account for rounding
        if periods:
            total_allocated = sum(p["amount"] for p in periods[:-1])
            periods[-1]["amount"] = round(float(total_amount) - float(total_allocated), 2)

    elif distribution_type == "custom":
        # Use specified number of periods
        if number_of_periods <= 0:
            number_of_periods = 1

        # Calculate period length
        total_days = (end_date - start_date).days + 1
        days_per_period = total_days // number_of_periods

        period_amount = total_amount / number_of_periods
        current = start_date

        for i in range(number_of_periods):
            if i == number_of_periods - 1:
                # Last period goes to end_date
                period_end = end_date
            else:
                period_end = current + timedelta(days=days_per_period - 1)

            periods.append({
                "period_start": current,
                "period_end": period_end,
                "period_number": i + 1,
                "amount": round(period_amount, 2)
            })
            current = period_end + timedelta(days=1)

        # Adjust last period to account for rounding
        if periods:
            total_allocated = sum(p["amount"] for p in periods[:-1])
            periods[-1]["amount"] = round(float(total_amount) - float(total_allocated), 2)

    return periods


def decimal_to_float(val):
    """Convert Decimal to float safely"""
    if val is None:
        return 0
    if isinstance(val, Decimal):
        return float(val)
    return val


def get_allocation_with_access_check(
    db: Session,
    allocation_id: int,
    company_id: int,
    load_periods: bool = True
) -> Optional[InvoiceAllocation]:
    """Get an allocation and verify the user has access to it based on their company"""
    query = db.query(InvoiceAllocation).filter(InvoiceAllocation.id == allocation_id)

    if load_periods:
        query = query.options(joinedload(InvoiceAllocation.periods))

    allocation = query.first()

    if not allocation:
        return None

    # Verify access based on allocation type
    has_access = False

    if allocation.contract_id:
        contract = db.query(Contract).filter(
            Contract.id == allocation.contract_id,
            Contract.company_id == company_id
        ).first()
        has_access = contract is not None

    elif allocation.site_id:
        site = db.query(Site).join(Client).filter(
            Site.id == allocation.site_id,
            Client.company_id == company_id
        ).first()
        has_access = site is not None

    elif allocation.project_id:
        project = db.query(Project).join(Site).join(Client).filter(
            Project.id == allocation.project_id,
            Client.company_id == company_id
        ).first()
        has_access = project is not None

    return allocation if has_access else None


# ============================================================================
# Allocation Endpoints
# ============================================================================

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_allocation(
    allocation_data: AllocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new invoice allocation with cost distribution"""

    # Validate exactly one target is specified
    targets = [allocation_data.contract_id, allocation_data.site_id, allocation_data.project_id]
    targets_set = [t for t in targets if t is not None]

    if len(targets_set) != 1:
        raise HTTPException(
            status_code=400,
            detail="Exactly one allocation target must be specified (contract_id, site_id, or project_id)"
        )

    # Verify invoice exists and belongs to user's company
    invoice = db.query(ProcessedImage).filter(
        ProcessedImage.id == allocation_data.invoice_id
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Check if invoice already has an allocation
    existing = db.query(InvoiceAllocation).filter(
        InvoiceAllocation.invoice_id == allocation_data.invoice_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Invoice already has an allocation")

    # Determine allocation type and verify target exists
    allocation_type = None
    start_date = allocation_data.start_date
    end_date = allocation_data.end_date

    if allocation_data.contract_id:
        allocation_type = "contract"
        contract = db.query(Contract).filter(
            Contract.id == allocation_data.contract_id,
            Contract.company_id == current_user.company_id
        ).first()
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        # Use contract dates as defaults
        start_date = start_date or contract.start_date
        end_date = end_date or contract.end_date

    elif allocation_data.site_id:
        allocation_type = "site"
        # Verify site exists and belongs to user's company
        # Sites can be linked via client_id (legacy) or address_book_id (new)
        from app.models import AddressBook
        from sqlalchemy import or_

        site = db.query(Site).outerjoin(
            Client, Site.client_id == Client.id
        ).outerjoin(
            AddressBook, Site.address_book_id == AddressBook.id
        ).filter(
            Site.id == allocation_data.site_id,
            or_(
                Client.company_id == current_user.company_id,
                AddressBook.company_id == current_user.company_id
            )
        ).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        # Use current year as default date range for sites
        if not start_date:
            start_date = date(date.today().year, 1, 1)
        if not end_date:
            end_date = date(date.today().year, 12, 31)

    elif allocation_data.project_id:
        allocation_type = "project"
        # Verify project exists and belongs to a site in user's company
        # Sites can be linked via client_id (legacy) or address_book_id (new)
        from app.models import AddressBook
        from sqlalchemy import or_

        project = db.query(Project).join(Site).outerjoin(
            Client, Site.client_id == Client.id
        ).outerjoin(
            AddressBook, Site.address_book_id == AddressBook.id
        ).filter(
            Project.id == allocation_data.project_id,
            or_(
                Client.company_id == current_user.company_id,
                AddressBook.company_id == current_user.company_id
            )
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        # Use project dates as defaults if available
        if hasattr(project, 'start_date') and project.start_date:
            start_date = start_date or project.start_date
        if hasattr(project, 'end_date') and project.end_date:
            end_date = end_date or project.end_date
        # Fallback to current year
        if not start_date:
            start_date = date(date.today().year, 1, 1)
        if not end_date:
            end_date = date(date.today().year, 12, 31)

    if end_date <= start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    # Create allocation
    allocation = InvoiceAllocation(
        invoice_id=allocation_data.invoice_id,
        contract_id=allocation_data.contract_id,
        site_id=allocation_data.site_id,
        project_id=allocation_data.project_id,
        allocation_type=allocation_type,
        total_amount=Decimal(str(allocation_data.total_amount)),
        distribution_type=allocation_data.distribution_type,
        start_date=start_date,
        end_date=end_date,
        number_of_periods=allocation_data.number_of_periods or 1,
        notes=allocation_data.notes,
        created_by=current_user.id,
        status="active"
    )
    db.add(allocation)
    db.flush()

    # Calculate and create periods
    periods = calculate_periods(
        total_amount=allocation.total_amount,
        distribution_type=allocation.distribution_type,
        start_date=start_date,
        end_date=end_date,
        number_of_periods=allocation.number_of_periods
    )

    for period_data in periods:
        period = AllocationPeriod(
            allocation_id=allocation.id,
            period_start=period_data["period_start"],
            period_end=period_data["period_end"],
            period_number=period_data["period_number"],
            amount=Decimal(str(period_data["amount"]))
        )
        db.add(period)

    # Update invoice with contract_id if not already set (for contract allocations)
    if allocation_data.contract_id and not invoice.contract_id:
        invoice.contract_id = allocation_data.contract_id

    db.commit()
    db.refresh(allocation)

    logger.info(f"Created {allocation_type} allocation {allocation.id} for invoice {allocation_data.invoice_id}")

    # Build response
    return build_allocation_response(allocation, db)


@router.get("", response_model=List[AllocationResponse])
async def get_allocations(
    contract_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    allocation_type: Optional[str] = Query(None),
    invoice_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all allocations, optionally filtered by target, type, or invoice"""

    # Build query that handles all allocation types
    query = db.query(InvoiceAllocation)

    # Filter by company - need to check via contract, site->client, or project->site->client
    company_filter = db.query(InvoiceAllocation.id).outerjoin(
        Contract, InvoiceAllocation.contract_id == Contract.id
    ).outerjoin(
        Site, InvoiceAllocation.site_id == Site.id
    ).outerjoin(
        Client, Site.client_id == Client.id
    ).outerjoin(
        Project, InvoiceAllocation.project_id == Project.id
    ).filter(
        (Contract.company_id == current_user.company_id) |
        (Client.company_id == current_user.company_id)
    )

    query = query.filter(InvoiceAllocation.id.in_(company_filter))

    if contract_id:
        query = query.filter(InvoiceAllocation.contract_id == contract_id)

    if site_id:
        query = query.filter(InvoiceAllocation.site_id == site_id)

    if project_id:
        query = query.filter(InvoiceAllocation.project_id == project_id)

    if allocation_type:
        query = query.filter(InvoiceAllocation.allocation_type == allocation_type)

    if invoice_id:
        query = query.filter(InvoiceAllocation.invoice_id == invoice_id)

    if status_filter:
        query = query.filter(InvoiceAllocation.status == status_filter)

    allocations = query.options(
        joinedload(InvoiceAllocation.periods)
    ).order_by(InvoiceAllocation.created_at.desc()).offset(skip).limit(limit).all()

    return [build_allocation_response(a, db) for a in allocations]


@router.get("/{allocation_id}")
async def get_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific allocation"""

    allocation = get_allocation_with_access_check(db, allocation_id, current_user.company_id)

    if not allocation:
        raise HTTPException(status_code=404, detail="Allocation not found")

    return build_allocation_response(allocation, db)


@router.put("/{allocation_id}")
async def update_allocation(
    allocation_id: int,
    update_data: AllocationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an allocation (recalculates periods if distribution changes)"""

    allocation = get_allocation_with_access_check(db, allocation_id, current_user.company_id, load_periods=False)

    if not allocation:
        raise HTTPException(status_code=404, detail="Allocation not found")

    # Check if any periods have been recognized
    recognized_periods = db.query(AllocationPeriod).filter(
        AllocationPeriod.allocation_id == allocation_id,
        AllocationPeriod.is_recognized == True
    ).count()

    recalculate_periods = False
    data = update_data.model_dump(exclude_unset=True)

    # Check if we need to recalculate periods
    if any(key in data for key in ["distribution_type", "start_date", "end_date", "number_of_periods"]):
        if recognized_periods > 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot change distribution settings when periods have been recognized"
            )
        recalculate_periods = True

    # Update allocation fields
    for key, value in data.items():
        setattr(allocation, key, value)

    if recalculate_periods:
        # Delete existing periods
        db.query(AllocationPeriod).filter(AllocationPeriod.allocation_id == allocation_id).delete()

        # Recalculate periods
        start_date = allocation.start_date
        end_date = allocation.end_date

        periods = calculate_periods(
            total_amount=allocation.total_amount,
            distribution_type=allocation.distribution_type,
            start_date=start_date,
            end_date=end_date,
            number_of_periods=allocation.number_of_periods
        )

        for period_data in periods:
            period = AllocationPeriod(
                allocation_id=allocation.id,
                period_start=period_data["period_start"],
                period_end=period_data["period_end"],
                period_number=period_data["period_number"],
                amount=Decimal(str(period_data["amount"]))
            )
            db.add(period)

    db.commit()
    db.refresh(allocation)

    logger.info(f"Updated allocation {allocation_id}")

    return build_allocation_response(allocation, db)


@router.delete("/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an allocation"""

    allocation = get_allocation_with_access_check(db, allocation_id, current_user.company_id, load_periods=False)

    if not allocation:
        raise HTTPException(status_code=404, detail="Allocation not found")

    # Check if any periods have been recognized
    recognized_periods = db.query(AllocationPeriod).filter(
        AllocationPeriod.allocation_id == allocation_id,
        AllocationPeriod.is_recognized == True
    ).count()

    if recognized_periods > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete allocation with recognized periods. Cancel it instead."
        )

    db.delete(allocation)
    db.commit()

    logger.info(f"Deleted allocation {allocation_id}")


@router.post("/{allocation_id}/cancel")
async def cancel_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel an allocation (keeps history but marks as cancelled)"""

    allocation = get_allocation_with_access_check(db, allocation_id, current_user.company_id, load_periods=False)

    if not allocation:
        raise HTTPException(status_code=404, detail="Allocation not found")

    allocation.status = "cancelled"
    db.commit()

    logger.info(f"Cancelled allocation {allocation_id}")

    return {"message": "Allocation cancelled", "status": "cancelled"}


def get_period_with_access_check(db: Session, period_id: int, company_id: int) -> Optional[AllocationPeriod]:
    """Get an allocation period and verify the user has access to it based on their company"""
    period = db.query(AllocationPeriod).filter(AllocationPeriod.id == period_id).first()

    if not period:
        return None

    # Get the allocation
    allocation = db.query(InvoiceAllocation).filter(
        InvoiceAllocation.id == period.allocation_id
    ).first()

    if not allocation:
        return None

    # Verify access based on allocation type
    has_access = False

    if allocation.contract_id:
        contract = db.query(Contract).filter(
            Contract.id == allocation.contract_id,
            Contract.company_id == company_id
        ).first()
        has_access = contract is not None

    elif allocation.site_id:
        site = db.query(Site).join(Client).filter(
            Site.id == allocation.site_id,
            Client.company_id == company_id
        ).first()
        has_access = site is not None

    elif allocation.project_id:
        project = db.query(Project).join(Site).join(Client).filter(
            Project.id == allocation.project_id,
            Client.company_id == company_id
        ).first()
        has_access = project is not None

    return period if has_access else None


def generate_recognition_number(db: Session) -> str:
    """Generate a unique recognition number in format REC-YYYY-XXXX"""
    year = datetime.utcnow().year

    # Get the highest recognition number for this year
    latest = db.query(AllocationPeriod).filter(
        AllocationPeriod.recognition_number.like(f"REC-{year}-%")
    ).order_by(AllocationPeriod.recognition_number.desc()).first()

    if latest and latest.recognition_number:
        # Extract the sequence number and increment
        try:
            seq = int(latest.recognition_number.split('-')[-1])
            seq += 1
        except:
            seq = 1
    else:
        seq = 1

    return f"REC-{year}-{str(seq).zfill(4)}"


@router.post("/periods/{period_id}/recognize")
async def recognize_period(
    period_id: int,
    request: RecognizePeriodRequest = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Mark a period as recognized (cost posted to accounting).
    Creates an audit trail with recognition number and tracking info.
    """

    period = get_period_with_access_check(db, period_id, current_user.company_id)

    if not period:
        raise HTTPException(status_code=404, detail="Period not found")

    if period.is_recognized:
        raise HTTPException(status_code=400, detail="Period already recognized")

    # Generate recognition number
    recognition_number = generate_recognition_number(db)

    # Get reference and notes from request body
    reference = request.reference if request else None
    notes = request.notes if request else None

    # Update period with recognition details
    period.is_recognized = True
    period.recognized_at = datetime.utcnow()
    period.recognition_number = recognition_number
    period.recognition_reference = reference
    period.recognition_notes = notes
    period.recognized_by = current_user.id

    # Create audit log entry
    log_entry = RecognitionLog(
        period_id=period_id,
        action="recognized",
        recognition_number=recognition_number,
        previous_status=False,
        new_status=True,
        reference=reference,
        notes=notes,
        user_id=current_user.id
    )
    db.add(log_entry)

    db.commit()

    logger.info(f"Recognized period {period_id} with number {recognition_number} by user {current_user.id}")

    # Auto-post journal entry if accounting is set up
    journal_entry_number = None
    try:
        # Check if chart of accounts is initialized
        has_accounts = db.query(Account).filter(
            Account.company_id == current_user.company_id
        ).first()

        if has_accounts:
            journal_service = JournalPostingService(db, current_user.company_id, current_user.id)
            journal_entry = journal_service.post_invoice_allocation(period, post_immediately=True)
            if journal_entry:
                journal_entry_number = journal_entry.entry_number
                logger.info(f"Auto-posted journal entry {journal_entry_number} for period {period_id}")
    except Exception as e:
        logger.warning(f"Failed to auto-post journal entry for period {period_id}: {e}")
        # Don't fail the recognition if journal posting fails

    return {
        "message": "Period recognized successfully",
        "recognition_number": recognition_number,
        "recognized_at": period.recognized_at,
        "recognized_by": current_user.name or current_user.email,
        "reference": reference,
        "notes": notes,
        "journal_entry_number": journal_entry_number
    }


@router.post("/periods/{period_id}/unrecognize")
async def unrecognize_period(
    period_id: int,
    request: RecognizePeriodRequest = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reverse a period recognition (for corrections).
    Requires admin role and creates an audit trail.
    """

    # Only admins can unrecognize
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can reverse recognition")

    period = get_period_with_access_check(db, period_id, current_user.company_id)

    if not period:
        raise HTTPException(status_code=404, detail="Period not found")

    if not period.is_recognized:
        raise HTTPException(status_code=400, detail="Period is not recognized")

    notes = request.notes if request else None
    old_recognition_number = period.recognition_number

    # Create audit log entry before clearing
    log_entry = RecognitionLog(
        period_id=period_id,
        action="unrecognized",
        recognition_number=old_recognition_number,
        previous_status=True,
        new_status=False,
        notes=notes,
        user_id=current_user.id
    )
    db.add(log_entry)

    # Clear recognition details
    period.is_recognized = False
    period.recognized_at = None
    period.recognition_number = None
    period.recognition_reference = None
    period.recognition_notes = None
    period.recognized_by = None

    db.commit()

    logger.info(f"Unrecognized period {period_id} (was {old_recognition_number}) by user {current_user.id}")

    return {
        "message": "Period recognition reversed",
        "previous_recognition_number": old_recognition_number
    }


@router.get("/periods/{period_id}/history")
async def get_period_recognition_history(
    period_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the recognition audit history for a period"""

    period = get_period_with_access_check(db, period_id, current_user.company_id)

    if not period:
        raise HTTPException(status_code=404, detail="Period not found")

    # Get all log entries for this period
    logs = db.query(RecognitionLog).filter(
        RecognitionLog.period_id == period_id
    ).order_by(RecognitionLog.created_at.desc()).all()

    return {
        "period_id": period_id,
        "current_status": "recognized" if period.is_recognized else "pending",
        "recognition_number": period.recognition_number,
        "history": [
            {
                "id": log.id,
                "action": log.action,
                "recognition_number": log.recognition_number,
                "previous_status": "recognized" if log.previous_status else "pending",
                "new_status": "recognized" if log.new_status else "pending",
                "reference": log.reference,
                "notes": log.notes,
                "user": (log.user.name or log.user.email) if log.user else "System",
                "created_at": log.created_at
            }
            for log in logs
        ]
    }


@router.get("/contract/{contract_id}/summary")
async def get_contract_allocation_summary(
    contract_id: int,
    period_start: Optional[date] = Query(None),
    period_end: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get allocation summary for a contract, optionally filtered by period"""

    # Verify contract access
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Get all active allocations for this contract
    allocations = db.query(InvoiceAllocation).filter(
        InvoiceAllocation.contract_id == contract_id,
        InvoiceAllocation.status == "active"
    ).options(joinedload(InvoiceAllocation.periods)).all()

    total_allocated = Decimal("0")
    total_recognized = Decimal("0")
    total_pending = Decimal("0")

    period_amounts = {}  # {month_key: amount}

    for allocation in allocations:
        total_allocated += allocation.total_amount

        for period in allocation.periods:
            # Check if period is within filter range
            if period_start and period.period_end < period_start:
                continue
            if period_end and period.period_start > period_end:
                continue

            if period.is_recognized:
                total_recognized += period.amount
            else:
                total_pending += period.amount

            # Aggregate by month
            month_key = period.period_start.strftime("%Y-%m")
            if month_key not in period_amounts:
                period_amounts[month_key] = {"recognized": Decimal("0"), "pending": Decimal("0")}

            if period.is_recognized:
                period_amounts[month_key]["recognized"] += period.amount
            else:
                period_amounts[month_key]["pending"] += period.amount

    # Convert to list and sort by month
    monthly_breakdown = [
        {
            "month": month,
            "recognized": decimal_to_float(amounts["recognized"]),
            "pending": decimal_to_float(amounts["pending"]),
            "total": decimal_to_float(amounts["recognized"] + amounts["pending"])
        }
        for month, amounts in sorted(period_amounts.items())
    ]

    return {
        "contract_id": contract_id,
        "contract_name": contract.name,
        "allocation_count": len(allocations),
        "total_allocated": decimal_to_float(total_allocated),
        "total_recognized": decimal_to_float(total_recognized),
        "total_pending": decimal_to_float(total_pending),
        "monthly_breakdown": monthly_breakdown
    }


def build_allocation_response(allocation: InvoiceAllocation, db: Session) -> dict:
    """Build a complete allocation response with related data"""

    # Get invoice details
    invoice = db.query(ProcessedImage).filter(
        ProcessedImage.id == allocation.invoice_id
    ).first()

    invoice_number = None
    vendor_name = None
    if invoice and invoice.structured_data:
        import json
        try:
            data = json.loads(invoice.structured_data)
            invoice_number = data.get("invoice_number")
            vendor_name = data.get("vendor_name") or data.get("vendor")
        except:
            pass

    # Get target details based on allocation type
    contract = None
    contract_name = None
    contract_number = None
    site = None
    site_name = None
    project = None
    project_name = None
    client_name = None

    if allocation.contract_id:
        contract = db.query(Contract).filter(Contract.id == allocation.contract_id).first()
        if contract:
            contract_name = contract.name
            contract_number = contract.contract_number

    if allocation.site_id:
        site = db.query(Site).options(joinedload(Site.client)).filter(Site.id == allocation.site_id).first()
        if site:
            site_name = site.name
            if site.client:
                client_name = site.client.name

    if allocation.project_id:
        project = db.query(Project).options(
            joinedload(Project.site).joinedload(Site.client)
        ).filter(Project.id == allocation.project_id).first()
        if project:
            project_name = project.name
            if project.site and project.site.client:
                client_name = project.site.client.name

    return {
        "id": allocation.id,
        "invoice_id": allocation.invoice_id,
        "contract_id": allocation.contract_id,
        "site_id": allocation.site_id,
        "project_id": allocation.project_id,
        "allocation_type": allocation.allocation_type or "contract",
        "total_amount": decimal_to_float(allocation.total_amount),
        "distribution_type": allocation.distribution_type,
        "start_date": allocation.start_date,
        "end_date": allocation.end_date,
        "number_of_periods": allocation.number_of_periods,
        "status": allocation.status,
        "notes": allocation.notes,
        "created_at": allocation.created_at,
        "periods": [
            {
                "id": p.id,
                "period_start": p.period_start,
                "period_end": p.period_end,
                "period_number": p.period_number,
                "amount": decimal_to_float(p.amount),
                "is_recognized": p.is_recognized,
                "recognized_at": p.recognized_at,
                "recognition_number": p.recognition_number,
                "recognition_reference": p.recognition_reference,
                "recognition_notes": p.recognition_notes,
                "recognized_by_name": (p.recognized_by_user.name or p.recognized_by_user.email) if p.recognized_by and p.recognized_by_user else None
            }
            for p in sorted(allocation.periods, key=lambda x: x.period_number)
        ],
        "invoice_number": invoice_number,
        "vendor_name": vendor_name,
        "contract_name": contract_name,
        "contract_number": contract_number,
        "site_name": site_name,
        "project_name": project_name,
        "client_name": client_name
    }


@router.get("/clients/{client_id}/cost-center")
async def get_client_cost_center(
    client_id: int,
    period_start: Optional[date] = Query(None),
    period_end: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get aggregated cost center view for a client.
    Includes all allocations (contracts, sites, projects) related to this client.
    """

    # Verify client access
    client = db.query(Client).filter(
        Client.id == client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Get all sites for this client
    sites = db.query(Site).filter(Site.client_id == client_id).all()
    site_ids = [s.id for s in sites]

    # Get all projects for this client's sites
    projects = []
    project_ids = []
    if site_ids:
        projects = db.query(Project).filter(Project.site_id.in_(site_ids)).all()
        project_ids = [p.id for p in projects]

    # Get all allocations for:
    # 1. Sites belonging to this client
    # 2. Projects belonging to this client's sites
    allocations = db.query(InvoiceAllocation).filter(
        InvoiceAllocation.status == "active",
        (
            (InvoiceAllocation.site_id.in_(site_ids) if site_ids else False) |
            (InvoiceAllocation.project_id.in_(project_ids) if project_ids else False)
        )
    ).options(joinedload(InvoiceAllocation.periods)).all()

    # Aggregate by allocation type
    contract_totals = {"allocated": Decimal("0"), "recognized": Decimal("0"), "pending": Decimal("0")}
    site_totals = {"allocated": Decimal("0"), "recognized": Decimal("0"), "pending": Decimal("0")}
    project_totals = {"allocated": Decimal("0"), "recognized": Decimal("0"), "pending": Decimal("0")}

    # Detail breakdown
    site_breakdown = {}  # site_id -> {name, allocated, recognized, pending}
    project_breakdown = {}  # project_id -> {name, site_name, allocated, recognized, pending}

    monthly_breakdown = {}  # month_key -> {contracts, sites, projects}

    for allocation in allocations:
        alloc_type = allocation.allocation_type or "contract"

        if alloc_type == "site" and allocation.site_id:
            site_totals["allocated"] += allocation.total_amount

            if allocation.site_id not in site_breakdown:
                site = next((s for s in sites if s.id == allocation.site_id), None)
                site_breakdown[allocation.site_id] = {
                    "id": allocation.site_id,
                    "name": site.name if site else f"Site {allocation.site_id}",
                    "allocated": Decimal("0"),
                    "recognized": Decimal("0"),
                    "pending": Decimal("0")
                }
            site_breakdown[allocation.site_id]["allocated"] += allocation.total_amount

            for period in allocation.periods:
                if period_start and period.period_end < period_start:
                    continue
                if period_end and period.period_start > period_end:
                    continue

                if period.is_recognized:
                    site_totals["recognized"] += period.amount
                    site_breakdown[allocation.site_id]["recognized"] += period.amount
                else:
                    site_totals["pending"] += period.amount
                    site_breakdown[allocation.site_id]["pending"] += period.amount

                # Monthly
                month_key = period.period_start.strftime("%Y-%m")
                if month_key not in monthly_breakdown:
                    monthly_breakdown[month_key] = {
                        "contracts": Decimal("0"),
                        "sites": Decimal("0"),
                        "projects": Decimal("0")
                    }
                monthly_breakdown[month_key]["sites"] += period.amount

        elif alloc_type == "project" and allocation.project_id:
            project_totals["allocated"] += allocation.total_amount

            if allocation.project_id not in project_breakdown:
                project = next((p for p in projects if p.id == allocation.project_id), None)
                site = next((s for s in sites if s.id == project.site_id), None) if project else None
                project_breakdown[allocation.project_id] = {
                    "id": allocation.project_id,
                    "name": project.name if project else f"Project {allocation.project_id}",
                    "site_name": site.name if site else None,
                    "allocated": Decimal("0"),
                    "recognized": Decimal("0"),
                    "pending": Decimal("0")
                }
            project_breakdown[allocation.project_id]["allocated"] += allocation.total_amount

            for period in allocation.periods:
                if period_start and period.period_end < period_start:
                    continue
                if period_end and period.period_start > period_end:
                    continue

                if period.is_recognized:
                    project_totals["recognized"] += period.amount
                    project_breakdown[allocation.project_id]["recognized"] += period.amount
                else:
                    project_totals["pending"] += period.amount
                    project_breakdown[allocation.project_id]["pending"] += period.amount

                # Monthly
                month_key = period.period_start.strftime("%Y-%m")
                if month_key not in monthly_breakdown:
                    monthly_breakdown[month_key] = {
                        "contracts": Decimal("0"),
                        "sites": Decimal("0"),
                        "projects": Decimal("0")
                    }
                monthly_breakdown[month_key]["projects"] += period.amount

    # Convert to lists for response
    site_list = [
        {
            "id": data["id"],
            "name": data["name"],
            "allocated": decimal_to_float(data["allocated"]),
            "recognized": decimal_to_float(data["recognized"]),
            "pending": decimal_to_float(data["pending"])
        }
        for data in site_breakdown.values()
    ]

    project_list = [
        {
            "id": data["id"],
            "name": data["name"],
            "site_name": data["site_name"],
            "allocated": decimal_to_float(data["allocated"]),
            "recognized": decimal_to_float(data["recognized"]),
            "pending": decimal_to_float(data["pending"])
        }
        for data in project_breakdown.values()
    ]

    monthly_list = [
        {
            "month": month,
            "contracts": decimal_to_float(amounts["contracts"]),
            "sites": decimal_to_float(amounts["sites"]),
            "projects": decimal_to_float(amounts["projects"]),
            "total": decimal_to_float(amounts["contracts"] + amounts["sites"] + amounts["projects"])
        }
        for month, amounts in sorted(monthly_breakdown.items())
    ]

    # Grand totals
    grand_total = {
        "allocated": decimal_to_float(contract_totals["allocated"] + site_totals["allocated"] + project_totals["allocated"]),
        "recognized": decimal_to_float(contract_totals["recognized"] + site_totals["recognized"] + project_totals["recognized"]),
        "pending": decimal_to_float(contract_totals["pending"] + site_totals["pending"] + project_totals["pending"])
    }

    return {
        "client_id": client_id,
        "client_name": client.name,
        "totals": {
            "contracts": {
                "allocated": decimal_to_float(contract_totals["allocated"]),
                "recognized": decimal_to_float(contract_totals["recognized"]),
                "pending": decimal_to_float(contract_totals["pending"])
            },
            "sites": {
                "allocated": decimal_to_float(site_totals["allocated"]),
                "recognized": decimal_to_float(site_totals["recognized"]),
                "pending": decimal_to_float(site_totals["pending"])
            },
            "projects": {
                "allocated": decimal_to_float(project_totals["allocated"]),
                "recognized": decimal_to_float(project_totals["recognized"]),
                "pending": decimal_to_float(project_totals["pending"])
            },
            "grand": grand_total
        },
        "sites": site_list,
        "projects": project_list,
        "monthly_breakdown": monthly_list
    }
