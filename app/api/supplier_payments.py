"""
Supplier Payment API - Payment processing for supplier invoices.

Features:
- Create payments against one or more invoices
- Partial payment support
- Multiple payment methods (check, wire, ACH, etc.)
- Early payment discount handling
- Payment approval workflow
- Journal entry posting (DR: AP, CR: Cash/Bank)
- Void payments
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
import logging

from app.database import get_db
from app.models import (
    User, Company, SupplierInvoice, SupplierPayment, SupplierPaymentAllocation,
    AddressBook, JournalEntry, JournalEntryLine, DefaultAccountMapping, FiscalPeriod
)
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class PaymentAllocationCreate(BaseModel):
    invoice_id: int
    allocated_amount: float
    discount_amount: float = 0


class SupplierPaymentCreate(BaseModel):
    address_book_id: int
    payment_date: date
    payment_method: str  # check, bank_transfer, wire, ach, card, cash
    bank_account: Optional[str] = None
    check_number: Optional[str] = None
    reference_number: Optional[str] = None
    currency: str = 'USD'
    exchange_rate: float = 1.0
    notes: Optional[str] = None
    allocations: List[PaymentAllocationCreate]


class PaymentApprovalRequest(BaseModel):
    action: str  # approve, reject
    reason: Optional[str] = None


class VoidPaymentRequest(BaseModel):
    reason: str


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_payment_number(db: Session, company_id: int) -> str:
    """Generate unique payment number: PAY-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"PAY-{year}-"

    last_payment = db.query(SupplierPayment).filter(
        SupplierPayment.company_id == company_id,
        SupplierPayment.payment_number.like(f"{prefix}%")
    ).order_by(SupplierPayment.payment_number.desc()).first()

    if last_payment:
        last_num = int(last_payment.payment_number.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{prefix}{new_num:05d}"


def update_invoice_payment_status(db: Session, invoice: SupplierInvoice):
    """Update invoice status based on payment allocations"""
    # Calculate total paid from all allocations
    total_paid = db.query(func.sum(SupplierPaymentAllocation.allocated_amount)).join(
        SupplierPayment
    ).filter(
        SupplierPaymentAllocation.invoice_id == invoice.id,
        SupplierPayment.status == 'posted'
    ).scalar() or 0

    total_discount = db.query(func.sum(SupplierPaymentAllocation.discount_amount)).join(
        SupplierPayment
    ).filter(
        SupplierPaymentAllocation.invoice_id == invoice.id,
        SupplierPayment.status == 'posted'
    ).scalar() or 0

    invoice.amount_paid = Decimal(str(total_paid))
    invoice.amount_remaining = invoice.total_amount - invoice.amount_paid - Decimal(str(total_discount))

    if invoice.amount_remaining <= 0:
        invoice.status = 'paid'
    elif float(invoice.amount_paid) > 0:
        invoice.status = 'partially_paid'


# =============================================================================
# JOURNAL POSTING SERVICE FOR PAYMENTS
# =============================================================================

class PaymentPostingService:
    """
    Service to create journal entries for supplier payments.

    Journal Entry:
    DR: Accounts Payable (2100) - Reduces liability
    CR: Cash/Bank (1000/1010) - Reduces asset
    DR: Purchase Discount (if early payment) - Reduces expense
    """

    def __init__(self, db: Session, company_id: int, user_id: int):
        self.db = db
        self.company_id = company_id
        self.user_id = user_id

    def _get_mapping(self, transaction_type: str) -> Optional[DefaultAccountMapping]:
        """Get account mapping for transaction type"""
        return self.db.query(DefaultAccountMapping).filter(
            DefaultAccountMapping.company_id == self.company_id,
            DefaultAccountMapping.transaction_type == transaction_type,
            DefaultAccountMapping.is_active == True
        ).first()

    def _get_fiscal_period(self, entry_date: date) -> Optional[FiscalPeriod]:
        """Get fiscal period for a date"""
        return self.db.query(FiscalPeriod).filter(
            FiscalPeriod.company_id == self.company_id,
            FiscalPeriod.start_date <= entry_date,
            FiscalPeriod.end_date >= entry_date
        ).first()

    def _generate_entry_number(self) -> str:
        """Generate unique journal entry number"""
        year = datetime.now().year
        prefix = f"JE-{year}-"

        last_entry = self.db.query(JournalEntry).filter(
            JournalEntry.company_id == self.company_id,
            JournalEntry.entry_number.like(f"{prefix}%")
        ).order_by(JournalEntry.entry_number.desc()).first()

        if last_entry:
            last_num = int(last_entry.entry_number.split('-')[-1])
            new_num = last_num + 1
        else:
            new_num = 1

        return f"{prefix}{new_num:06d}"

    def post_payment(self, payment: SupplierPayment) -> Optional[JournalEntry]:
        """
        Create journal entry for supplier payment.

        DR: Accounts Payable (reduces liability)
        CR: Cash/Bank (reduces asset)
        CR: Purchase Discount (if discount taken)
        """
        # Get account mappings
        ap_mapping = self._get_mapping("accounts_payable")
        cash_mapping = self._get_mapping("cash")
        discount_mapping = self._get_mapping("purchase_discount")

        if not ap_mapping or not cash_mapping:
            logger.warning(f"Missing account mappings for payment. AP: {ap_mapping}, Cash: {cash_mapping}")
            return None

        ap_account_id = ap_mapping.credit_account_id  # Normally credited, so we debit to reduce
        cash_account_id = cash_mapping.debit_account_id  # Normally debited, so we credit to reduce

        if not ap_account_id or not cash_account_id:
            logger.warning("AP or Cash account not configured")
            return None

        entry_date = payment.payment_date or date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        vendor_name = payment.address_book.alpha_name if payment.address_book else "Unknown"

        # Try to get site_id/contract_id from linked invoices via allocations
        site_id = None
        contract_id = None
        work_order_id = None
        # Supplier payments are typically not site-specific, but we try to trace back if possible
        # This would require traversing: allocation → invoice → GRN → PO → work_order
        # For simplicity, we leave these as None for general vendor payments

        # Create journal entry
        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"Supplier Payment {payment.payment_number} to {vendor_name}",
            reference=payment.payment_number,
            source_type="supplier_payment",
            source_id=payment.id,
            source_number=payment.payment_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # Calculate totals
        total_allocated = sum(float(a.allocated_amount) for a in payment.allocations)
        total_discount = sum(float(a.discount_amount) for a in payment.allocations)

        # DR: Accounts Payable (for total allocated + discount)
        ap_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=ap_account_id,
            debit=Decimal(str(round(total_allocated + total_discount, 2))),
            credit=Decimal('0'),
            description=f"AP reduction for payment {payment.payment_number}",
            line_number=line_number,
            address_book_id=payment.address_book_id,
            site_id=site_id,
            contract_id=contract_id,
            work_order_id=work_order_id
        )
        self.db.add(ap_line)
        lines.append(ap_line)
        line_number += 1

        # CR: Cash/Bank (for actual payment amount)
        cash_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=cash_account_id,
            debit=Decimal('0'),
            credit=Decimal(str(round(float(payment.total_amount), 2))),
            description=f"Payment via {payment.payment_method}",
            line_number=line_number,
            address_book_id=payment.address_book_id,
            site_id=site_id,
            contract_id=contract_id,
            work_order_id=work_order_id
        )
        self.db.add(cash_line)
        lines.append(cash_line)
        line_number += 1

        # CR: Purchase Discount (if discount taken)
        if total_discount > 0 and discount_mapping and discount_mapping.credit_account_id:
            discount_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=discount_mapping.credit_account_id,
                debit=Decimal('0'),
                credit=Decimal(str(round(total_discount, 2))),
                description=f"Early payment discount",
                line_number=line_number,
                address_book_id=payment.address_book_id,
                site_id=site_id,
                contract_id=contract_id,
                work_order_id=work_order_id
            )
            self.db.add(discount_line)
            lines.append(discount_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        # Post immediately
        entry.status = "posted"
        entry.posted_at = datetime.utcnow()
        entry.posted_by = self.user_id

        self.db.commit()
        logger.info(f"Created payment journal entry {entry.entry_number} for payment {payment.payment_number}")

        return entry

    def reverse_payment(self, payment: SupplierPayment, reason: str) -> Optional[JournalEntry]:
        """
        Create reversal journal entry when payment is voided.
        Swaps debits and credits from original entry.
        """
        if not payment.journal_entry_id:
            return None

        original_entry = self.db.query(JournalEntry).get(payment.journal_entry_id)
        if not original_entry:
            return None

        entry_date = date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        # Create reversal entry
        reversal = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"VOID: {original_entry.description} - {reason}",
            reference=f"VOID-{payment.payment_number}",
            source_type="supplier_payment_void",
            source_id=payment.id,
            source_number=payment.payment_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="posted",
            is_auto_generated=True,
            created_by=self.user_id,
            posted_at=datetime.utcnow(),
            posted_by=self.user_id
        )
        self.db.add(reversal)
        self.db.flush()

        # Copy lines with swapped debits/credits
        original_lines = self.db.query(JournalEntryLine).filter(
            JournalEntryLine.journal_entry_id == original_entry.id
        ).all()

        for idx, orig_line in enumerate(original_lines, 1):
            rev_line = JournalEntryLine(
                journal_entry_id=reversal.id,
                account_id=orig_line.account_id,
                debit=orig_line.credit,  # Swap
                credit=orig_line.debit,  # Swap
                description=f"Reversal: {orig_line.description}",
                line_number=idx,
                address_book_id=orig_line.address_book_id,
                business_unit_id=orig_line.business_unit_id
            )
            self.db.add(rev_line)

        reversal.total_debit = original_entry.total_credit
        reversal.total_credit = original_entry.total_debit

        # Mark original as reversed
        original_entry.status = "reversed"

        self.db.commit()
        logger.info(f"Created reversal entry {reversal.entry_number} for voided payment {payment.payment_number}")

        return reversal


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_supplier_payment(
    data: SupplierPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new supplier payment.
    Can pay multiple invoices in a single payment.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    if not data.allocations:
        raise HTTPException(status_code=400, detail="At least one invoice allocation is required")

    # Validate vendor
    vendor = db.query(AddressBook).filter(
        AddressBook.id == data.address_book_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == 'V'
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Validate payment method
    valid_methods = ['check', 'bank_transfer', 'wire', 'ach', 'card', 'cash']
    if data.payment_method not in valid_methods:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid payment method. Must be one of: {', '.join(valid_methods)}"
        )

    # Validate all invoices and calculate total
    total_amount = Decimal('0')
    total_discount = Decimal('0')

    for alloc in data.allocations:
        invoice = db.query(SupplierInvoice).filter(
            SupplierInvoice.id == alloc.invoice_id,
            SupplierInvoice.company_id == current_user.company_id,
            SupplierInvoice.address_book_id == data.address_book_id  # Must be same vendor
        ).first()

        if not invoice:
            raise HTTPException(
                status_code=404,
                detail=f"Invoice {alloc.invoice_id} not found or belongs to different vendor"
            )

        if invoice.status not in ['approved', 'partially_paid']:
            raise HTTPException(
                status_code=400,
                detail=f"Invoice {invoice.invoice_number} is not approved for payment (status: {invoice.status})"
            )

        if invoice.is_on_hold:
            raise HTTPException(
                status_code=400,
                detail=f"Invoice {invoice.invoice_number} is on payment hold"
            )

        # Check allocation doesn't exceed remaining
        if Decimal(str(alloc.allocated_amount)) > invoice.amount_remaining:
            raise HTTPException(
                status_code=400,
                detail=f"Allocation {alloc.allocated_amount} exceeds remaining amount {invoice.amount_remaining} on invoice {invoice.invoice_number}"
            )

        total_amount += Decimal(str(alloc.allocated_amount))
        total_discount += Decimal(str(alloc.discount_amount))

    # Calculate base currency amount
    exchange_rate = Decimal(str(data.exchange_rate))
    total_amount_base = total_amount * exchange_rate

    # Create payment
    payment = SupplierPayment(
        company_id=current_user.company_id,
        payment_number=generate_payment_number(db, current_user.company_id),
        address_book_id=data.address_book_id,
        payment_date=data.payment_date,
        payment_method=data.payment_method,
        bank_account=data.bank_account,
        check_number=data.check_number,
        reference_number=data.reference_number,
        currency=data.currency,
        exchange_rate=exchange_rate,
        total_amount=total_amount,
        total_amount_base=total_amount_base,
        discount_taken=total_discount,
        status='draft',
        notes=data.notes,
        created_by=current_user.id
    )
    db.add(payment)
    db.flush()

    # Create allocations
    for alloc in data.allocations:
        allocation = SupplierPaymentAllocation(
            payment_id=payment.id,
            invoice_id=alloc.invoice_id,
            allocated_amount=alloc.allocated_amount,
            discount_amount=alloc.discount_amount
        )
        db.add(allocation)

    db.commit()
    db.refresh(payment)

    return {
        "message": "Payment created successfully",
        "payment_id": payment.id,
        "payment_number": payment.payment_number,
        "total_amount": float(payment.total_amount),
        "discount_taken": float(payment.discount_taken),
        "status": payment.status
    }


@router.get("/")
def list_supplier_payments(
    status: Optional[str] = None,
    vendor_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    payment_method: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List supplier payments with filters"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    query = db.query(SupplierPayment).filter(
        SupplierPayment.company_id == current_user.company_id
    ).options(
        joinedload(SupplierPayment.address_book),
        joinedload(SupplierPayment.allocations).joinedload(SupplierPaymentAllocation.invoice)
    )

    if status:
        query = query.filter(SupplierPayment.status == status)
    if vendor_id:
        query = query.filter(SupplierPayment.address_book_id == vendor_id)
    if from_date:
        query = query.filter(SupplierPayment.payment_date >= from_date)
    if to_date:
        query = query.filter(SupplierPayment.payment_date <= to_date)
    if payment_method:
        query = query.filter(SupplierPayment.payment_method == payment_method)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                SupplierPayment.payment_number.ilike(search_pattern),
                SupplierPayment.reference_number.ilike(search_pattern),
                SupplierPayment.check_number.ilike(search_pattern)
            )
        )

    total = query.count()
    skip = (page - 1) * page_size
    payments = query.order_by(SupplierPayment.payment_date.desc()).offset(skip).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": pay.id,
                "payment_number": pay.payment_number,
                "vendor_name": pay.address_book.alpha_name if pay.address_book else None,
                "vendor": {
                    "id": pay.address_book.id,
                    "name": pay.address_book.alpha_name
                } if pay.address_book else None,
                "payment_date": str(pay.payment_date),
                "payment_method": pay.payment_method,
                "total_amount": float(pay.total_amount),
                "discount_taken": float(pay.discount_taken),
                "currency": pay.currency,
                "status": pay.status,
                "reference_number": pay.reference_number,
                "check_number": pay.check_number,
                "invoices_count": len(pay.allocations),
                "invoice_numbers": [a.invoice.invoice_number for a in pay.allocations if a.invoice]
            }
            for pay in payments
        ]
    }


@router.get("/{payment_id}")
def get_supplier_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get supplier payment details"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    payment = db.query(SupplierPayment).filter(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == current_user.company_id
    ).options(
        joinedload(SupplierPayment.address_book),
        joinedload(SupplierPayment.allocations).joinedload(SupplierPaymentAllocation.invoice),
        joinedload(SupplierPayment.journal_entry)
    ).first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    return {
        "id": payment.id,
        "payment_number": payment.payment_number,
        "address_book_id": payment.address_book_id,
        "vendor_name": payment.address_book.alpha_name if payment.address_book else None,
        "vendor": {
            "id": payment.address_book.id,
            "name": payment.address_book.alpha_name,
            "address_number": payment.address_book.address_number
        } if payment.address_book else None,
        "payment_date": str(payment.payment_date),
        "payment_method": payment.payment_method,
        "bank_account": payment.bank_account,
        "check_number": payment.check_number,
        "reference_number": payment.reference_number,
        "currency": payment.currency,
        "exchange_rate": float(payment.exchange_rate),
        "total_amount": float(payment.total_amount),
        "total_amount_base": float(payment.total_amount_base),
        "discount_taken": float(payment.discount_taken),
        "status": payment.status,
        "allocations": [
            {
                "invoice_id": alloc.invoice_id,
                "invoice_number": alloc.invoice.invoice_number if alloc.invoice else None,
                "supplier_invoice_number": alloc.invoice.supplier_invoice_number if alloc.invoice else None,
                "allocated_amount": float(alloc.allocated_amount),
                "discount_amount": float(alloc.discount_amount)
            }
            for alloc in payment.allocations
        ],
        "journal_entry_id": payment.journal_entry.id if payment.journal_entry else None,
        "journal_entry": {
            "id": payment.journal_entry.id,
            "entry_number": payment.journal_entry.entry_number
        } if payment.journal_entry else None,
        "notes": payment.notes,
        "created_at": str(payment.created_at)
    }


@router.delete("/{payment_id}")
def delete_supplier_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a supplier payment (only if in draft status)"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    payment = db.query(SupplierPayment).filter(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == current_user.company_id
    ).first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status != 'draft':
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete payment with status '{payment.status}'. Only draft payments can be deleted."
        )

    if payment.journal_entry_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete payment with posted journal entry"
        )

    # Delete payment allocations first
    db.query(SupplierPaymentAllocation).filter(
        SupplierPaymentAllocation.payment_id == payment_id
    ).delete()

    # Delete the payment
    db.delete(payment)
    db.commit()

    return {"message": f"Payment {payment.payment_number} deleted successfully"}


@router.post("/{payment_id}/approve")
def approve_payment(
    payment_id: int,
    request: PaymentApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Approve or reject a supplier payment"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    payment = db.query(SupplierPayment).filter(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == current_user.company_id
    ).options(
        joinedload(SupplierPayment.allocations),
        joinedload(SupplierPayment.address_book)
    ).first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status != 'draft':
        raise HTTPException(status_code=400, detail="Only draft payments can be approved")

    if request.action == 'approve':
        payment.status = 'approved'
        payment.approved_by = current_user.id
        payment.approved_at = datetime.utcnow()
        message = "Payment approved successfully"
    elif request.action == 'reject':
        if not request.reason:
            raise HTTPException(status_code=400, detail="Rejection reason is required")
        payment.status = 'cancelled'
        message = f"Payment rejected: {request.reason}"
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'approve' or 'reject'")

    db.commit()

    return {"message": message, "status": payment.status}


@router.post("/{payment_id}/post")
def post_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Post an approved payment.
    Creates journal entry and updates invoice payment status.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    payment = db.query(SupplierPayment).filter(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == current_user.company_id
    ).options(
        joinedload(SupplierPayment.allocations).joinedload(SupplierPaymentAllocation.invoice),
        joinedload(SupplierPayment.address_book)
    ).first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status != 'approved':
        raise HTTPException(status_code=400, detail="Only approved payments can be posted")

    # Create journal entry
    posting_service = PaymentPostingService(db, current_user.company_id, current_user.id)
    journal_entry = posting_service.post_payment(payment)

    if journal_entry:
        payment.journal_entry_id = journal_entry.id

    # Update payment status
    payment.status = 'posted'
    payment.posted_by = current_user.id
    payment.posted_at = datetime.utcnow()

    # Update invoice payment statuses
    for alloc in payment.allocations:
        if alloc.invoice:
            update_invoice_payment_status(db, alloc.invoice)

    db.commit()

    return {
        "message": "Payment posted successfully",
        "status": payment.status,
        "journal_entry_number": journal_entry.entry_number if journal_entry else None
    }


@router.post("/{payment_id}/void")
def void_payment(
    payment_id: int,
    request: VoidPaymentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Void a posted payment.
    Creates reversal journal entry and reverts invoice payment status.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    payment = db.query(SupplierPayment).filter(
        SupplierPayment.id == payment_id,
        SupplierPayment.company_id == current_user.company_id
    ).options(
        joinedload(SupplierPayment.allocations).joinedload(SupplierPaymentAllocation.invoice),
        joinedload(SupplierPayment.address_book)
    ).first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status != 'posted':
        raise HTTPException(status_code=400, detail="Only posted payments can be voided")

    # Create reversal journal entry
    posting_service = PaymentPostingService(db, current_user.company_id, current_user.id)
    reversal_entry = posting_service.reverse_payment(payment, request.reason)

    # Update payment status
    payment.status = 'voided'
    payment.voided_by = current_user.id
    payment.voided_at = datetime.utcnow()
    payment.void_reason = request.reason

    # Update invoice payment statuses (recalculate based on remaining valid payments)
    for alloc in payment.allocations:
        if alloc.invoice:
            update_invoice_payment_status(db, alloc.invoice)

    db.commit()

    return {
        "message": "Payment voided successfully",
        "status": payment.status,
        "reversal_entry_number": reversal_entry.entry_number if reversal_entry else None
    }


# =============================================================================
# REPORTING ENDPOINTS
# =============================================================================

@router.get("/reports/summary")
def get_payment_summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get payment summary by method and status"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    query = db.query(SupplierPayment).filter(
        SupplierPayment.company_id == current_user.company_id
    )

    if from_date:
        query = query.filter(SupplierPayment.payment_date >= from_date)
    if to_date:
        query = query.filter(SupplierPayment.payment_date <= to_date)

    payments = query.all()

    # Group by payment method
    by_method = {}
    by_status = {}
    total_paid = 0
    total_discount = 0

    for pay in payments:
        method = pay.payment_method
        status = pay.status

        if method not in by_method:
            by_method[method] = {"count": 0, "total": 0}
        by_method[method]["count"] += 1
        by_method[method]["total"] += float(pay.total_amount)

        if status not in by_status:
            by_status[status] = {"count": 0, "total": 0}
        by_status[status]["count"] += 1
        by_status[status]["total"] += float(pay.total_amount)

        if status == 'posted':
            total_paid += float(pay.total_amount)
            total_discount += float(pay.discount_taken)

    return {
        "period": {
            "from_date": str(from_date) if from_date else None,
            "to_date": str(to_date) if to_date else None
        },
        "by_payment_method": by_method,
        "by_status": by_status,
        "total_payments": len(payments),
        "total_paid": total_paid,
        "total_discount_taken": total_discount
    }


@router.get("/vendor/{vendor_id}/outstanding")
def get_vendor_outstanding_invoices(
    vendor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all outstanding invoices for a vendor ready for payment"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    vendor = db.query(AddressBook).filter(
        AddressBook.id == vendor_id,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    invoices = db.query(SupplierInvoice).filter(
        SupplierInvoice.company_id == current_user.company_id,
        SupplierInvoice.address_book_id == vendor_id,
        SupplierInvoice.status.in_(['approved', 'partially_paid']),
        SupplierInvoice.amount_remaining > 0,
        SupplierInvoice.is_on_hold == False
    ).order_by(SupplierInvoice.due_date).all()

    total_outstanding = sum(float(inv.amount_remaining) for inv in invoices)

    return {
        "vendor": {
            "id": vendor.id,
            "name": vendor.alpha_name,
            "address_number": vendor.address_number
        },
        "total_outstanding": total_outstanding,
        "invoice_count": len(invoices),
        "invoices": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "supplier_invoice_number": inv.supplier_invoice_number,
                "invoice_date": str(inv.invoice_date),
                "due_date": str(inv.due_date) if inv.due_date else None,
                "total_amount": float(inv.total_amount),
                "amount_paid": float(inv.amount_paid),
                "amount_remaining": float(inv.amount_remaining),
                "is_overdue": inv.due_date and inv.due_date < date.today(),
                "days_until_due": (inv.due_date - date.today()).days if inv.due_date else None,
                "early_discount_available": (
                    inv.early_payment_discount_days and
                    inv.early_payment_discount_percent and
                    inv.invoice_date and
                    (date.today() - inv.invoice_date).days <= inv.early_payment_discount_days
                ),
                "early_discount_percent": float(inv.early_payment_discount_percent) if inv.early_payment_discount_percent else 0
            }
            for inv in invoices
        ]
    }
