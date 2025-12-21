from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func, case
from typing import Optional, List
from decimal import Decimal
from datetime import datetime, date
from app.database import get_db
from app.models import (
    PettyCashFund, PettyCashTransaction, PettyCashReceipt, PettyCashReplenishment,
    User, Technician, WorkOrder, Contract, Account
)
from app.services.journal_posting import JournalPostingService
from app.api.auth import get_current_user
from app.config import settings
from jose import jwt
import os
import uuid
import logging

logger = logging.getLogger(__name__)


def verify_token_payload(token: str) -> Optional[dict]:
    """Verify token and return full payload"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except:
        return None


router = APIRouter()

# Upload directory for petty cash receipts
PETTY_CASH_RECEIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads", "petty_cash_receipts"
)

# Ensure upload directory exists
os.makedirs(PETTY_CASH_RECEIPTS_DIR, exist_ok=True)

# Valid categories
VALID_CATEGORIES = ["supplies", "tools", "transport", "meals", "materials", "services", "other"]
VALID_STATUSES = ["pending", "approved", "rejected", "reimbursed"]
VALID_FUND_STATUSES = ["active", "suspended", "closed"]
VALID_REPLENISHMENT_METHODS = ["cash", "transfer", "check"]


# ============================================================================
# Pydantic Schemas
# ============================================================================

class PettyCashFundCreate(BaseModel):
    technician_id: int
    fund_limit: float = 500.00
    currency: str = "USD"
    auto_approve_threshold: float = 50.00


class PettyCashFundUpdate(BaseModel):
    fund_limit: Optional[float] = None
    currency: Optional[str] = None
    auto_approve_threshold: Optional[float] = None
    status: Optional[str] = None


class PettyCashTransactionCreate(BaseModel):
    transaction_date: Optional[datetime] = None
    amount: float
    description: str
    category: Optional[str] = None
    merchant_name: Optional[str] = None
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    notes: Optional[str] = None


class PettyCashTransactionUpdate(BaseModel):
    transaction_date: Optional[datetime] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    category: Optional[str] = None
    merchant_name: Optional[str] = None
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    notes: Optional[str] = None


class ReplenishmentCreate(BaseModel):
    amount: float
    method: Optional[str] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class RejectTransactionRequest(BaseModel):
    reason: str


class PettyCashReceiptResponse(BaseModel):
    id: int
    transaction_id: int
    filename: str
    original_filename: str
    file_size: Optional[int]
    mime_type: Optional[str]
    caption: Optional[str]
    uploaded_by: Optional[int]
    uploaded_by_name: Optional[str]
    uploaded_at: Optional[str]

    class Config:
        from_attributes = True


class PettyCashTransactionResponse(BaseModel):
    id: int
    fund_id: int
    technician_id: int
    technician_name: str
    transaction_number: str
    transaction_date: str
    amount: float
    currency: str
    description: str
    category: Optional[str]
    merchant_name: Optional[str]
    work_order_id: Optional[int]
    work_order_number: Optional[str]
    contract_id: Optional[int]
    contract_name: Optional[str]
    status: str
    auto_approved: bool
    approved_by: Optional[int]
    approved_by_name: Optional[str]
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    balance_before: Optional[float]
    balance_after: Optional[float]
    notes: Optional[str]
    receipts: List[PettyCashReceiptResponse]
    receipt_count: int
    created_by: int
    created_by_name: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class PettyCashFundResponse(BaseModel):
    id: int
    technician_id: int
    technician_name: str
    fund_limit: float
    current_balance: float
    currency: str
    status: str
    auto_approve_threshold: float
    transaction_count: int
    pending_count: int
    total_spent: float
    created_by: Optional[int]
    created_by_name: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class PettyCashReplenishmentResponse(BaseModel):
    id: int
    fund_id: int
    technician_name: str
    replenishment_number: str
    replenishment_date: str
    amount: float
    currency: str
    method: Optional[str]
    reference_number: Optional[str]
    balance_before: Optional[float]
    balance_after: Optional[float]
    notes: Optional[str]
    processed_by: int
    processed_by_name: str
    created_at: str

    class Config:
        from_attributes = True


class PettyCashStatsResponse(BaseModel):
    total_funds: int
    active_funds: int
    total_allocated: float
    total_balance: float
    pending_transactions: int
    pending_amount: float
    month_spent: float
    month_transactions: int
    by_category: dict
    by_status: dict


# ============================================================================
# Helper Functions
# ============================================================================

def generate_transaction_number(db: Session, company_id: int) -> str:
    """Generate unique transaction number: PCT-YYYYMMDD-XXX"""
    today = date.today()
    prefix = f"PCT-{today.strftime('%Y%m%d')}"

    # Count existing transactions for today
    count = db.query(PettyCashTransaction).join(PettyCashFund).filter(
        PettyCashFund.company_id == company_id,
        func.date(PettyCashTransaction.transaction_date) == today
    ).count()

    return f"{prefix}-{count + 1:03d}"


def generate_replenishment_number(db: Session, company_id: int) -> str:
    """Generate unique replenishment number: PCR-YYYYMMDD-XXX"""
    today = date.today()
    prefix = f"PCR-{today.strftime('%Y%m%d')}"

    # Count existing replenishments for today
    count = db.query(PettyCashReplenishment).filter(
        PettyCashReplenishment.company_id == company_id,
        func.date(PettyCashReplenishment.replenishment_date) == today
    ).count()

    return f"{prefix}-{count + 1:03d}"


def fund_to_response(fund: PettyCashFund, db: Session) -> dict:
    """Convert fund model to response dict"""
    # Calculate stats
    transaction_count = len(fund.transactions) if fund.transactions else 0
    pending_count = len([t for t in fund.transactions if t.status == "pending"]) if fund.transactions else 0
    total_spent = sum([float(t.amount) for t in fund.transactions if t.status in ["approved", "reimbursed"]]) if fund.transactions else 0

    return {
        "id": fund.id,
        "technician_id": fund.technician_id,
        "technician_name": fund.technician.name if fund.technician else "Unknown",
        "fund_limit": float(fund.fund_limit),
        "current_balance": float(fund.current_balance),
        "currency": fund.currency,
        "status": fund.status,
        "auto_approve_threshold": float(fund.auto_approve_threshold),
        "transaction_count": transaction_count,
        "pending_count": pending_count,
        "total_spent": total_spent,
        "created_by": fund.created_by,
        "created_by_name": fund.creator.email if fund.creator else None,
        "created_at": fund.created_at.isoformat() if fund.created_at else None,
        "updated_at": fund.updated_at.isoformat() if fund.updated_at else None
    }


def transaction_to_response(txn: PettyCashTransaction) -> dict:
    """Convert transaction model to response dict"""
    receipts = []
    if txn.receipts:
        for r in txn.receipts:
            receipts.append({
                "id": r.id,
                "transaction_id": r.transaction_id,
                "filename": r.filename,
                "original_filename": r.original_filename,
                "file_size": r.file_size,
                "mime_type": r.mime_type,
                "caption": r.caption,
                "uploaded_by": r.uploaded_by,
                "uploaded_by_name": r.uploader.email if r.uploader else None,
                "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None
            })

    return {
        "id": txn.id,
        "fund_id": txn.fund_id,
        "technician_id": txn.fund.technician_id if txn.fund else None,
        "technician_name": txn.fund.technician.name if txn.fund and txn.fund.technician else "Unknown",
        "transaction_number": txn.transaction_number,
        "transaction_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
        "amount": float(txn.amount),
        "currency": txn.currency,
        "description": txn.description,
        "category": txn.category,
        "merchant_name": txn.merchant_name,
        "work_order_id": txn.work_order_id,
        "work_order_number": txn.work_order.work_order_number if txn.work_order else None,
        "contract_id": txn.contract_id,
        "contract_name": txn.contract.contract_name if txn.contract else None,
        "status": txn.status,
        "auto_approved": txn.auto_approved,
        "approved_by": txn.approved_by,
        "approved_by_name": txn.approver.email if txn.approver else None,
        "approved_at": txn.approved_at.isoformat() if txn.approved_at else None,
        "rejection_reason": txn.rejection_reason,
        "balance_before": float(txn.balance_before) if txn.balance_before else None,
        "balance_after": float(txn.balance_after) if txn.balance_after else None,
        "notes": txn.notes,
        "receipts": receipts,
        "receipt_count": len(receipts),
        "created_by": txn.created_by,
        "created_by_name": txn.creator.email if txn.creator else None,
        "created_at": txn.created_at.isoformat() if txn.created_at else None,
        "updated_at": txn.updated_at.isoformat() if txn.updated_at else None
    }


def replenishment_to_response(repl: PettyCashReplenishment) -> dict:
    """Convert replenishment model to response dict"""
    return {
        "id": repl.id,
        "fund_id": repl.fund_id,
        "technician_name": repl.fund.technician.name if repl.fund and repl.fund.technician else "Unknown",
        "replenishment_number": repl.replenishment_number,
        "replenishment_date": repl.replenishment_date.isoformat() if repl.replenishment_date else None,
        "amount": float(repl.amount),
        "currency": repl.currency,
        "method": repl.method,
        "reference_number": repl.reference_number,
        "balance_before": float(repl.balance_before) if repl.balance_before else None,
        "balance_after": float(repl.balance_after) if repl.balance_after else None,
        "notes": repl.notes,
        "processed_by": repl.processed_by,
        "processed_by_name": repl.processor.email if repl.processor else None,
        "created_at": repl.created_at.isoformat() if repl.created_at else None
    }


def receipt_to_response(receipt: PettyCashReceipt) -> dict:
    """Convert receipt model to response dict"""
    return {
        "id": receipt.id,
        "transaction_id": receipt.transaction_id,
        "filename": receipt.filename,
        "original_filename": receipt.original_filename,
        "file_size": receipt.file_size,
        "mime_type": receipt.mime_type,
        "caption": receipt.caption,
        "uploaded_by": receipt.uploaded_by,
        "uploaded_by_name": receipt.uploader.email if receipt.uploader else None,
        "uploaded_at": receipt.uploaded_at.isoformat() if receipt.uploaded_at else None
    }


# ============================================================================
# Fund Management Endpoints
# ============================================================================

@router.get("/funds/")
async def get_petty_cash_funds(
    status: Optional[str] = Query(None),
    technician_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all petty cash funds for the company"""
    query = db.query(PettyCashFund).options(
        joinedload(PettyCashFund.technician),
        joinedload(PettyCashFund.creator),
        joinedload(PettyCashFund.transactions)
    ).filter(PettyCashFund.company_id == current_user.company_id)

    if status:
        query = query.filter(PettyCashFund.status == status)
    if technician_id:
        query = query.filter(PettyCashFund.technician_id == technician_id)

    funds = query.order_by(PettyCashFund.created_at.desc()).all()

    return [fund_to_response(f, db) for f in funds]


@router.get("/funds/{fund_id}")
async def get_petty_cash_fund(
    fund_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific petty cash fund"""
    fund = db.query(PettyCashFund).options(
        joinedload(PettyCashFund.technician),
        joinedload(PettyCashFund.creator),
        joinedload(PettyCashFund.transactions)
    ).filter(
        PettyCashFund.id == fund_id,
        PettyCashFund.company_id == current_user.company_id
    ).first()

    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Petty cash fund not found"
        )

    return fund_to_response(fund, db)


@router.post("/funds/")
async def create_petty_cash_fund(
    fund_data: PettyCashFundCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a petty cash fund for a technician"""
    # Verify technician exists and belongs to company
    technician = db.query(Technician).filter(
        Technician.id == fund_data.technician_id,
        Technician.company_id == current_user.company_id
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    # Check if technician already has a fund
    existing = db.query(PettyCashFund).filter(
        PettyCashFund.technician_id == fund_data.technician_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Technician already has a petty cash fund"
        )

    # Create fund
    fund = PettyCashFund(
        company_id=current_user.company_id,
        technician_id=fund_data.technician_id,
        fund_limit=Decimal(str(fund_data.fund_limit)),
        current_balance=Decimal(str(fund_data.fund_limit)),  # Start with full balance
        currency=fund_data.currency,
        auto_approve_threshold=Decimal(str(fund_data.auto_approve_threshold)),
        status="active",
        created_by=current_user.id
    )

    db.add(fund)
    db.commit()
    db.refresh(fund)

    # Reload with relationships
    fund = db.query(PettyCashFund).options(
        joinedload(PettyCashFund.technician),
        joinedload(PettyCashFund.creator),
        joinedload(PettyCashFund.transactions)
    ).filter(PettyCashFund.id == fund.id).first()

    return fund_to_response(fund, db)


@router.put("/funds/{fund_id}")
async def update_petty_cash_fund(
    fund_id: int,
    fund_data: PettyCashFundUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a petty cash fund"""
    fund = db.query(PettyCashFund).filter(
        PettyCashFund.id == fund_id,
        PettyCashFund.company_id == current_user.company_id
    ).first()

    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Petty cash fund not found"
        )

    # Validate status if provided
    if fund_data.status and fund_data.status not in VALID_FUND_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(VALID_FUND_STATUSES)}"
        )

    # Update fields
    if fund_data.fund_limit is not None:
        fund.fund_limit = Decimal(str(fund_data.fund_limit))
    if fund_data.currency is not None:
        fund.currency = fund_data.currency
    if fund_data.auto_approve_threshold is not None:
        fund.auto_approve_threshold = Decimal(str(fund_data.auto_approve_threshold))
    if fund_data.status is not None:
        fund.status = fund_data.status

    db.commit()
    db.refresh(fund)

    # Reload with relationships
    fund = db.query(PettyCashFund).options(
        joinedload(PettyCashFund.technician),
        joinedload(PettyCashFund.creator),
        joinedload(PettyCashFund.transactions)
    ).filter(PettyCashFund.id == fund.id).first()

    return fund_to_response(fund, db)


@router.delete("/funds/{fund_id}")
async def delete_petty_cash_fund(
    fund_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Close/deactivate a petty cash fund"""
    fund = db.query(PettyCashFund).filter(
        PettyCashFund.id == fund_id,
        PettyCashFund.company_id == current_user.company_id
    ).first()

    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Petty cash fund not found"
        )

    # Check for pending transactions
    pending = db.query(PettyCashTransaction).filter(
        PettyCashTransaction.fund_id == fund_id,
        PettyCashTransaction.status == "pending"
    ).count()

    if pending > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot close fund with {pending} pending transactions"
        )

    fund.status = "closed"
    db.commit()

    return {"success": True, "message": "Fund closed successfully"}


# ============================================================================
# Transaction Endpoints
# ============================================================================

@router.get("/transactions/")
async def get_petty_cash_transactions(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    technician_id: Optional[int] = Query(None),
    fund_id: Optional[int] = Query(None),
    work_order_id: Optional[int] = Query(None),
    contract_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all petty cash transactions for the company"""
    query = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashTransaction.work_order),
        joinedload(PettyCashTransaction.contract),
        joinedload(PettyCashTransaction.approver),
        joinedload(PettyCashTransaction.creator),
        joinedload(PettyCashTransaction.receipts).joinedload(PettyCashReceipt.uploader)
    ).filter(PettyCashTransaction.company_id == current_user.company_id)

    if status:
        query = query.filter(PettyCashTransaction.status == status)
    if category:
        query = query.filter(PettyCashTransaction.category == category)
    if technician_id:
        query = query.join(PettyCashFund).filter(PettyCashFund.technician_id == technician_id)
    if fund_id:
        query = query.filter(PettyCashTransaction.fund_id == fund_id)
    if work_order_id:
        query = query.filter(PettyCashTransaction.work_order_id == work_order_id)
    if contract_id:
        query = query.filter(PettyCashTransaction.contract_id == contract_id)
    if date_from:
        query = query.filter(func.date(PettyCashTransaction.transaction_date) >= date_from)
    if date_to:
        query = query.filter(func.date(PettyCashTransaction.transaction_date) <= date_to)
    if search:
        query = query.filter(
            or_(
                PettyCashTransaction.description.ilike(f"%{search}%"),
                PettyCashTransaction.merchant_name.ilike(f"%{search}%"),
                PettyCashTransaction.transaction_number.ilike(f"%{search}%")
            )
        )

    transactions = query.order_by(PettyCashTransaction.transaction_date.desc()).all()

    return [transaction_to_response(t) for t in transactions]


@router.get("/transactions/{transaction_id}")
async def get_petty_cash_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific petty cash transaction"""
    txn = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashTransaction.work_order),
        joinedload(PettyCashTransaction.contract),
        joinedload(PettyCashTransaction.approver),
        joinedload(PettyCashTransaction.creator),
        joinedload(PettyCashTransaction.receipts).joinedload(PettyCashReceipt.uploader)
    ).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    return transaction_to_response(txn)


@router.post("/transactions/")
async def create_petty_cash_transaction(
    txn_data: PettyCashTransactionCreate,
    fund_id: Optional[int] = Query(None, description="Fund ID (required if user has multiple funds)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new petty cash transaction"""
    # Find the fund - either by ID or by user's technician association
    if fund_id:
        fund = db.query(PettyCashFund).filter(
            PettyCashFund.id == fund_id,
            PettyCashFund.company_id == current_user.company_id,
            PettyCashFund.status == "active"
        ).first()
    else:
        # Try to find fund by user's technician association
        # For now, allow creating transactions for any fund in the company
        fund = db.query(PettyCashFund).filter(
            PettyCashFund.company_id == current_user.company_id,
            PettyCashFund.status == "active"
        ).first()

    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active petty cash fund found. Please specify fund_id."
        )

    # Validate category
    if txn_data.category and txn_data.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"
        )

    # Validate work order if provided
    if txn_data.work_order_id:
        wo = db.query(WorkOrder).filter(
            WorkOrder.id == txn_data.work_order_id,
            WorkOrder.company_id == current_user.company_id
        ).first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work order not found"
            )

    # Validate contract if provided
    if txn_data.contract_id:
        contract = db.query(Contract).filter(
            Contract.id == txn_data.contract_id,
            Contract.company_id == current_user.company_id
        ).first()
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contract not found"
            )

    amount = Decimal(str(txn_data.amount))

    # Check if amount exceeds available balance
    if amount > fund.current_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Available: {fund.current_balance}, Requested: {amount}"
        )

    # Generate transaction number
    transaction_number = generate_transaction_number(db, current_user.company_id)

    # Determine if auto-approved
    auto_approved = amount <= fund.auto_approve_threshold
    transaction_status = "approved" if auto_approved else "pending"

    # Calculate balance changes
    balance_before = fund.current_balance
    balance_after = balance_before - amount if auto_approved else balance_before

    # Create transaction
    txn = PettyCashTransaction(
        company_id=current_user.company_id,
        fund_id=fund.id,
        transaction_number=transaction_number,
        transaction_date=txn_data.transaction_date or datetime.now(),
        amount=amount,
        currency=fund.currency,
        description=txn_data.description,
        category=txn_data.category,
        merchant_name=txn_data.merchant_name,
        work_order_id=txn_data.work_order_id,
        contract_id=txn_data.contract_id,
        status=transaction_status,
        auto_approved=auto_approved,
        approved_by=current_user.id if auto_approved else None,
        approved_at=datetime.now() if auto_approved else None,
        balance_before=balance_before,
        balance_after=balance_after if auto_approved else None,
        notes=txn_data.notes,
        created_by=current_user.id
    )

    db.add(txn)

    # Update fund balance if auto-approved
    if auto_approved:
        fund.current_balance = balance_after

    db.commit()
    db.refresh(txn)

    # Reload with relationships
    txn = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashTransaction.work_order),
        joinedload(PettyCashTransaction.contract),
        joinedload(PettyCashTransaction.approver),
        joinedload(PettyCashTransaction.creator),
        joinedload(PettyCashTransaction.receipts)
    ).filter(PettyCashTransaction.id == txn.id).first()

    return transaction_to_response(txn)


@router.put("/transactions/{transaction_id}")
async def update_petty_cash_transaction(
    transaction_id: int,
    txn_data: PettyCashTransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a pending petty cash transaction"""
    txn = db.query(PettyCashTransaction).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    if txn.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update pending transactions"
        )

    # Validate category if provided
    if txn_data.category and txn_data.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}"
        )

    # Update fields
    update_data = txn_data.model_dump(exclude_unset=True)

    if "amount" in update_data and update_data["amount"] is not None:
        update_data["amount"] = Decimal(str(update_data["amount"]))

    for field, value in update_data.items():
        setattr(txn, field, value)

    db.commit()
    db.refresh(txn)

    # Reload with relationships
    txn = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashTransaction.work_order),
        joinedload(PettyCashTransaction.contract),
        joinedload(PettyCashTransaction.approver),
        joinedload(PettyCashTransaction.creator),
        joinedload(PettyCashTransaction.receipts)
    ).filter(PettyCashTransaction.id == txn.id).first()

    return transaction_to_response(txn)


@router.delete("/transactions/{transaction_id}")
async def delete_petty_cash_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a pending petty cash transaction"""
    txn = db.query(PettyCashTransaction).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    if txn.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete pending transactions"
        )

    # Delete associated receipts files
    for receipt in txn.receipts:
        if os.path.exists(receipt.file_path):
            try:
                os.remove(receipt.file_path)
            except:
                pass

    db.delete(txn)
    db.commit()

    return {"success": True, "message": "Transaction deleted successfully"}


@router.post("/transactions/{transaction_id}/approve")
async def approve_petty_cash_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Approve a pending petty cash transaction"""
    txn = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund)
    ).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    if txn.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction is not pending"
        )

    fund = txn.fund

    # Check balance
    if txn.amount > fund.current_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Available: {fund.current_balance}, Required: {txn.amount}"
        )

    # Update transaction
    txn.status = "approved"
    txn.approved_by = current_user.id
    txn.approved_at = datetime.now()
    txn.balance_before = fund.current_balance
    txn.balance_after = fund.current_balance - txn.amount

    # Update fund balance
    fund.current_balance = txn.balance_after

    db.commit()
    db.refresh(txn)

    # Auto-post journal entry if accounting is set up
    try:
        has_accounts = db.query(Account).filter(
            Account.company_id == current_user.company_id
        ).first()

        if has_accounts:
            journal_service = JournalPostingService(db, current_user.company_id, current_user.id)
            journal_entry = journal_service.post_petty_cash_transaction(txn, post_immediately=True)
            if journal_entry:
                logger.info(f"Auto-posted journal entry {journal_entry.entry_number} for petty cash transaction {txn.id}")
    except Exception as e:
        logger.warning(f"Failed to auto-post journal entry for petty cash transaction {txn.id}: {e}")
        # Don't fail the approval if journal posting fails

    # Reload with relationships
    txn = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashTransaction.work_order),
        joinedload(PettyCashTransaction.contract),
        joinedload(PettyCashTransaction.approver),
        joinedload(PettyCashTransaction.creator),
        joinedload(PettyCashTransaction.receipts)
    ).filter(PettyCashTransaction.id == txn.id).first()

    return transaction_to_response(txn)


@router.post("/transactions/{transaction_id}/reject")
async def reject_petty_cash_transaction(
    transaction_id: int,
    reject_data: RejectTransactionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reject a pending petty cash transaction"""
    txn = db.query(PettyCashTransaction).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    if txn.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction is not pending"
        )

    txn.status = "rejected"
    txn.approved_by = current_user.id
    txn.approved_at = datetime.now()
    txn.rejection_reason = reject_data.reason

    db.commit()
    db.refresh(txn)

    # Reload with relationships
    txn = db.query(PettyCashTransaction).options(
        joinedload(PettyCashTransaction.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashTransaction.work_order),
        joinedload(PettyCashTransaction.contract),
        joinedload(PettyCashTransaction.approver),
        joinedload(PettyCashTransaction.creator),
        joinedload(PettyCashTransaction.receipts)
    ).filter(PettyCashTransaction.id == txn.id).first()

    return transaction_to_response(txn)


# ============================================================================
# Receipt Endpoints
# ============================================================================

@router.get("/transactions/{transaction_id}/receipts/")
async def get_transaction_receipts(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all receipts for a transaction"""
    txn = db.query(PettyCashTransaction).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    receipts = db.query(PettyCashReceipt).options(
        joinedload(PettyCashReceipt.uploader)
    ).filter(
        PettyCashReceipt.transaction_id == transaction_id
    ).order_by(PettyCashReceipt.uploaded_at).all()

    return [receipt_to_response(r) for r in receipts]


@router.post("/transactions/{transaction_id}/receipts/")
async def upload_transaction_receipt(
    transaction_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a receipt image to a transaction"""
    txn = db.query(PettyCashTransaction).filter(
        PettyCashTransaction.id == transaction_id,
        PettyCashTransaction.company_id == current_user.company_id
    ).first()

    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    # Generate unique filename
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(PETTY_CASH_RECEIPTS_DIR, unique_filename)

    try:
        # Save file
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        file_size = os.path.getsize(file_path)

        # Create receipt record
        receipt = PettyCashReceipt(
            transaction_id=transaction_id,
            company_id=current_user.company_id,
            filename=unique_filename,
            original_filename=file.filename or "receipt.jpg",
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            caption=caption,
            uploaded_by=current_user.id
        )
        db.add(receipt)
        db.commit()
        db.refresh(receipt)

        # Reload with relationships
        receipt = db.query(PettyCashReceipt).options(
            joinedload(PettyCashReceipt.uploader)
        ).filter(PettyCashReceipt.id == receipt.id).first()

        return receipt_to_response(receipt)

    except Exception as e:
        # Clean up file if database operation fails
        if os.path.exists(file_path):
            os.remove(file_path)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload receipt: {str(e)}"
        )


@router.get("/transactions/{transaction_id}/receipts/{receipt_id}/file")
async def get_receipt_file(
    transaction_id: int,
    receipt_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Get receipt file (requires token in query param for img src)"""
    # Verify token
    payload = verify_token_payload(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    company_id = payload.get("company_id")
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    # Get receipt
    receipt = db.query(PettyCashReceipt).filter(
        PettyCashReceipt.id == receipt_id,
        PettyCashReceipt.transaction_id == transaction_id,
        PettyCashReceipt.company_id == company_id
    ).first()

    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found"
        )

    if not os.path.exists(receipt.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt file not found"
        )

    return FileResponse(
        receipt.file_path,
        media_type=receipt.mime_type or "image/jpeg",
        filename=receipt.original_filename
    )


@router.delete("/transactions/{transaction_id}/receipts/{receipt_id}")
async def delete_transaction_receipt(
    transaction_id: int,
    receipt_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a receipt from a transaction"""
    receipt = db.query(PettyCashReceipt).filter(
        PettyCashReceipt.id == receipt_id,
        PettyCashReceipt.transaction_id == transaction_id,
        PettyCashReceipt.company_id == current_user.company_id
    ).first()

    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found"
        )

    # Delete file
    if os.path.exists(receipt.file_path):
        try:
            os.remove(receipt.file_path)
        except:
            pass

    db.delete(receipt)
    db.commit()

    return {"success": True, "message": "Receipt deleted successfully"}


# ============================================================================
# Replenishment Endpoints
# ============================================================================

@router.get("/funds/{fund_id}/replenishments/")
async def get_fund_replenishments(
    fund_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get replenishment history for a fund"""
    fund = db.query(PettyCashFund).filter(
        PettyCashFund.id == fund_id,
        PettyCashFund.company_id == current_user.company_id
    ).first()

    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fund not found"
        )

    replenishments = db.query(PettyCashReplenishment).options(
        joinedload(PettyCashReplenishment.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashReplenishment.processor)
    ).filter(
        PettyCashReplenishment.fund_id == fund_id
    ).order_by(PettyCashReplenishment.replenishment_date.desc()).all()

    return [replenishment_to_response(r) for r in replenishments]


@router.post("/funds/{fund_id}/replenish/")
async def replenish_fund(
    fund_id: int,
    repl_data: ReplenishmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Replenish a petty cash fund"""
    fund = db.query(PettyCashFund).filter(
        PettyCashFund.id == fund_id,
        PettyCashFund.company_id == current_user.company_id
    ).first()

    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fund not found"
        )

    if fund.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot replenish a non-active fund"
        )

    # Validate method if provided
    if repl_data.method and repl_data.method not in VALID_REPLENISHMENT_METHODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid method. Must be one of: {', '.join(VALID_REPLENISHMENT_METHODS)}"
        )

    amount = Decimal(str(repl_data.amount))

    # Check if replenishment would exceed fund limit
    new_balance = fund.current_balance + amount
    if new_balance > fund.fund_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Replenishment would exceed fund limit. Max replenishment: {fund.fund_limit - fund.current_balance}"
        )

    # Generate replenishment number
    replenishment_number = generate_replenishment_number(db, current_user.company_id)

    # Create replenishment record
    repl = PettyCashReplenishment(
        company_id=current_user.company_id,
        fund_id=fund.id,
        replenishment_number=replenishment_number,
        replenishment_date=datetime.now(),
        amount=amount,
        currency=fund.currency,
        method=repl_data.method,
        reference_number=repl_data.reference_number,
        balance_before=fund.current_balance,
        balance_after=new_balance,
        notes=repl_data.notes,
        processed_by=current_user.id
    )

    db.add(repl)

    # Update fund balance
    fund.current_balance = new_balance

    db.commit()
    db.refresh(repl)

    # Auto-post journal entry if accounting is set up
    try:
        has_accounts = db.query(Account).filter(
            Account.company_id == current_user.company_id
        ).first()

        if has_accounts:
            journal_service = JournalPostingService(db, current_user.company_id, current_user.id)
            journal_entry = journal_service.post_petty_cash_replenishment(repl, post_immediately=True)
            if journal_entry:
                logger.info(f"Auto-posted journal entry {journal_entry.entry_number} for petty cash replenishment {repl.id}")
    except Exception as e:
        logger.warning(f"Failed to auto-post journal entry for petty cash replenishment {repl.id}: {e}")
        # Don't fail the replenishment if journal posting fails

    # Reload with relationships
    repl = db.query(PettyCashReplenishment).options(
        joinedload(PettyCashReplenishment.fund).joinedload(PettyCashFund.technician),
        joinedload(PettyCashReplenishment.processor)
    ).filter(PettyCashReplenishment.id == repl.id).first()

    return replenishment_to_response(repl)


# ============================================================================
# Stats Endpoints
# ============================================================================

@router.get("/stats/")
async def get_petty_cash_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get overall petty cash statistics"""
    # Fund stats
    fund_stats = db.query(
        func.count(PettyCashFund.id).label('total_funds'),
        func.sum(case((PettyCashFund.status == 'active', 1), else_=0)).label('active_funds'),
        func.coalesce(func.sum(PettyCashFund.fund_limit), 0).label('total_allocated'),
        func.coalesce(func.sum(PettyCashFund.current_balance), 0).label('total_balance')
    ).filter(
        PettyCashFund.company_id == current_user.company_id
    ).first()

    # Transaction stats
    pending_stats = db.query(
        func.count(PettyCashTransaction.id).label('pending_count'),
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label('pending_amount')
    ).filter(
        PettyCashTransaction.company_id == current_user.company_id,
        PettyCashTransaction.status == 'pending'
    ).first()

    # Month stats
    first_of_month = date.today().replace(day=1)
    month_stats = db.query(
        func.count(PettyCashTransaction.id).label('month_transactions'),
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label('month_spent')
    ).filter(
        PettyCashTransaction.company_id == current_user.company_id,
        PettyCashTransaction.status.in_(['approved', 'reimbursed']),
        func.date(PettyCashTransaction.transaction_date) >= first_of_month
    ).first()

    # By category
    category_stats = db.query(
        PettyCashTransaction.category,
        func.count(PettyCashTransaction.id).label('count'),
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label('amount')
    ).filter(
        PettyCashTransaction.company_id == current_user.company_id,
        PettyCashTransaction.status.in_(['approved', 'reimbursed'])
    ).group_by(PettyCashTransaction.category).all()

    by_category = {
        cat or 'uncategorized': {'count': count, 'amount': float(amount)}
        for cat, count, amount in category_stats
    }

    # By status
    status_stats = db.query(
        PettyCashTransaction.status,
        func.count(PettyCashTransaction.id).label('count'),
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label('amount')
    ).filter(
        PettyCashTransaction.company_id == current_user.company_id
    ).group_by(PettyCashTransaction.status).all()

    by_status = {
        stat: {'count': count, 'amount': float(amount)}
        for stat, count, amount in status_stats
    }

    return {
        "total_funds": fund_stats.total_funds or 0,
        "active_funds": fund_stats.active_funds or 0,
        "total_allocated": float(fund_stats.total_allocated or 0),
        "total_balance": float(fund_stats.total_balance or 0),
        "pending_transactions": pending_stats.pending_count or 0,
        "pending_amount": float(pending_stats.pending_amount or 0),
        "month_spent": float(month_stats.month_spent or 0),
        "month_transactions": month_stats.month_transactions or 0,
        "by_category": by_category,
        "by_status": by_status
    }


@router.get("/my-fund/")
async def get_my_petty_cash_fund(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current user's petty cash fund (for technicians)"""
    # Try to find fund by user's technician association
    # This assumes there's a way to link users to technicians
    # For now, return all active funds for the company
    funds = db.query(PettyCashFund).options(
        joinedload(PettyCashFund.technician),
        joinedload(PettyCashFund.creator),
        joinedload(PettyCashFund.transactions)
    ).filter(
        PettyCashFund.company_id == current_user.company_id,
        PettyCashFund.status == "active"
    ).all()

    if not funds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No petty cash fund found"
        )

    return [fund_to_response(f, db) for f in funds]
