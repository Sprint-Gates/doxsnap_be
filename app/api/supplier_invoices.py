"""
Supplier Invoice API - Complete invoice management with three-way matching and GRNI clearing.

Features:
- Create supplier invoices from PO/GRN
- Three-way matching (PO vs GRN vs Invoice)
- GRNI clearing when invoice is matched
- Invoice approval workflow
- Payment hold/release
- Variance tracking
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import logging
import json

from app.database import get_db
from app.models import (
    User, Company, PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine,
    SupplierInvoice, SupplierInvoiceLine, AddressBook, ItemMaster, ProcessedImage,
    JournalEntry, JournalEntryLine, DefaultAccountMapping, FiscalPeriod, Account
)
from app.api.auth import get_current_user
from app.services.journal_posting import JournalPostingService

router = APIRouter()
logger = logging.getLogger(__name__)

# Variance tolerance (configurable per company in production)
VARIANCE_TOLERANCE_PERCENT = Decimal('0.02')  # 2%
VARIANCE_TOLERANCE_AMOUNT = Decimal('0.50')  # $0.50


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class SupplierInvoiceLineCreate(BaseModel):
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    description: str
    quantity: float
    unit: str = 'EA'
    unit_price: float
    tax_amount: float = 0
    po_line_id: Optional[int] = None
    grn_line_id: Optional[int] = None
    account_id: Optional[int] = None
    notes: Optional[str] = None


class SupplierInvoiceCreate(BaseModel):
    address_book_id: int
    supplier_invoice_number: Optional[str] = None
    invoice_date: date
    received_date: Optional[date] = None
    payment_terms: Optional[str] = None
    payment_terms_days: int = 30
    early_payment_discount_percent: float = 0
    early_payment_discount_days: Optional[int] = None
    purchase_order_id: Optional[int] = None
    goods_receipt_id: Optional[int] = None
    processed_image_id: Optional[int] = None
    currency: str = 'USD'
    exchange_rate: float = 1.0
    tax_amount: float = 0
    notes: Optional[str] = None
    lines: List[SupplierInvoiceLineCreate]


class SupplierInvoiceUpdate(BaseModel):
    supplier_invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    received_date: Optional[date] = None
    due_date: Optional[date] = None
    payment_terms: Optional[str] = None
    payment_terms_days: Optional[int] = None
    purchase_order_id: Optional[int] = None
    goods_receipt_id: Optional[int] = None
    tax_amount: Optional[float] = None
    notes: Optional[str] = None


class InvoiceApprovalRequest(BaseModel):
    action: str  # approve, reject
    reason: Optional[str] = None


class InvoiceHoldRequest(BaseModel):
    action: str  # hold, release
    reason: Optional[str] = None


class ThreeWayMatchResult(BaseModel):
    po_amount: float
    grn_amount: float
    invoice_amount: float
    po_variance: float
    grn_variance: float
    is_matched: bool
    variance_details: List[dict]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_invoice_number(db: Session, company_id: int) -> str:
    """Generate unique supplier invoice number: SI-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"SI-{year}-"

    last_invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.company_id == company_id,
        SupplierInvoice.invoice_number.like(f"{prefix}%")
    ).order_by(SupplierInvoice.invoice_number.desc()).first()

    if last_invoice:
        last_num = int(last_invoice.invoice_number.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"{prefix}{new_num:05d}"


def calculate_due_date(invoice_date: date, payment_terms_days: int) -> date:
    """Calculate payment due date from invoice date and terms"""
    return invoice_date + timedelta(days=payment_terms_days)


def perform_three_way_match(
    db: Session,
    invoice: SupplierInvoice,
    po: Optional[PurchaseOrder],
    grn: Optional[GoodsReceipt]
) -> dict:
    """
    Perform three-way matching between PO, GRN, and Invoice.
    Returns match result with variances.
    """
    result = {
        "po_amount": 0,
        "grn_amount": 0,
        "invoice_amount": float(invoice.subtotal or 0),
        "po_variance": 0,
        "grn_variance": 0,
        "is_matched": False,
        "variance_details": []
    }

    # Get PO amount
    if po:
        result["po_amount"] = float(po.subtotal or 0)
        result["po_variance"] = result["invoice_amount"] - result["po_amount"]

    # Get GRN amount (sum of all GRNs for this PO if multiple)
    if grn:
        result["grn_amount"] = float(grn.subtotal or 0)
        result["grn_variance"] = result["invoice_amount"] - result["grn_amount"]
    elif po:
        # Sum all accepted GRNs for this PO
        grn_total = db.query(func.sum(GoodsReceipt.subtotal)).filter(
            GoodsReceipt.purchase_order_id == po.id,
            GoodsReceipt.status == 'accepted'
        ).scalar() or 0
        result["grn_amount"] = float(grn_total)
        result["grn_variance"] = result["invoice_amount"] - result["grn_amount"]

    # Check if within tolerance
    invoice_amt = Decimal(str(result["invoice_amount"]))

    po_within_tolerance = True
    grn_within_tolerance = True

    if result["po_amount"] > 0:
        po_variance_pct = abs(Decimal(str(result["po_variance"])) / Decimal(str(result["po_amount"])))
        po_within_tolerance = (
            po_variance_pct <= VARIANCE_TOLERANCE_PERCENT or
            abs(Decimal(str(result["po_variance"]))) <= VARIANCE_TOLERANCE_AMOUNT
        )

    if result["grn_amount"] > 0:
        grn_variance_pct = abs(Decimal(str(result["grn_variance"])) / Decimal(str(result["grn_amount"])))
        grn_within_tolerance = (
            grn_variance_pct <= VARIANCE_TOLERANCE_PERCENT or
            abs(Decimal(str(result["grn_variance"]))) <= VARIANCE_TOLERANCE_AMOUNT
        )

    result["is_matched"] = po_within_tolerance and grn_within_tolerance

    # Line-level variance details
    for inv_line in invoice.lines:
        line_detail = {
            "invoice_line_id": inv_line.id,
            "description": inv_line.description,
            "invoice_qty": float(inv_line.quantity),
            "invoice_price": float(inv_line.unit_price),
            "invoice_total": float(inv_line.total_price),
            "po_qty": None,
            "po_price": None,
            "grn_qty": None,
            "qty_variance": 0,
            "price_variance": 0
        }

        if inv_line.po_line_id:
            po_line = db.query(PurchaseOrderLine).get(inv_line.po_line_id)
            if po_line:
                line_detail["po_qty"] = float(po_line.quantity_ordered)
                line_detail["po_price"] = float(po_line.unit_price)
                line_detail["qty_variance"] = line_detail["invoice_qty"] - line_detail["po_qty"]
                line_detail["price_variance"] = line_detail["invoice_price"] - line_detail["po_price"]

        if inv_line.grn_line_id:
            grn_line = db.query(GoodsReceiptLine).get(inv_line.grn_line_id)
            if grn_line:
                line_detail["grn_qty"] = float(grn_line.quantity_accepted or grn_line.quantity_received)

        result["variance_details"].append(line_detail)

    return result


# =============================================================================
# GRNI CLEARING SERVICE
# =============================================================================

class GRNIClearingService:
    """
    Service to clear GRNI (Goods Received Not Invoiced) when invoice is matched.

    Creates journal entry:
    DR: GRNI (Liability decreases) - GRN subtotal (cost only)
    DR: VAT Payable (Input VAT) - Invoice tax amount
    CR: Accounts Payable (Liability created for actual invoice) - Invoice total
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

    def _get_account_by_code(self, code: str) -> Optional[Account]:
        """Get account by code for this company"""
        return self.db.query(Account).filter(
            Account.company_id == self.company_id,
            Account.code == code
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

    def clear_grni(self, invoice: SupplierInvoice, grn: GoodsReceipt) -> Optional[JournalEntry]:
        """
        Create GRNI clearing entry when invoice is matched to GRN.

        Journal Entry (balanced):
        DR: GRNI (2115) - GRN subtotal (clears the cost accrual from GRN posting)
        DR: VAT Payable (2141) - Invoice tax amount (recognize input VAT)
        CR: Accounts Payable (2111) - Invoice total (creates formal AP including VAT)

        If there's a price variance between GRN subtotal and invoice subtotal:
        DR/CR: Purchase Price Variance account (5510)
        """
        # Get account mappings
        grni_mapping = self._get_mapping("grni")
        ap_mapping = self._get_mapping("accounts_payable")

        if not grni_mapping or not ap_mapping:
            logger.warning(f"Missing account mappings for GRNI clearing. GRNI: {grni_mapping}, AP: {ap_mapping}")
            return None

        # Get GRNI and AP account IDs
        grni_account_id = grni_mapping.credit_account_id  # GRNI is normally credited, so we debit to clear
        ap_account_id = ap_mapping.credit_account_id

        if not grni_account_id or not ap_account_id:
            logger.warning("GRNI or AP account not configured")
            return None

        # Get VAT Payable account (2141)
        vat_account = self._get_account_by_code("2141")
        vat_account_id = vat_account.id if vat_account else None

        # Calculate amounts
        # GRNI was recorded at cost (subtotal only, no VAT) when GRN was received
        grn_subtotal = float(grn.subtotal or 0)

        # Invoice amounts
        invoice_subtotal = float(invoice.subtotal or 0)
        invoice_tax = float(invoice.tax_amount or 0)
        invoice_total = invoice_subtotal + invoice_tax

        # Price variance is between subtotals (cost only, not including VAT)
        price_variance = invoice_subtotal - grn_subtotal

        entry_date = invoice.invoice_date or date.today()
        fiscal_period = self._get_fiscal_period(entry_date)

        vendor_name = invoice.address_book.alpha_name if invoice.address_book else "Unknown"

        # Create journal entry
        entry = JournalEntry(
            company_id=self.company_id,
            entry_number=self._generate_entry_number(),
            entry_date=entry_date,
            description=f"GRNI Clearing - Invoice {invoice.invoice_number} for GRN {grn.grn_number} from {vendor_name}",
            reference=invoice.invoice_number,
            source_type="supplier_invoice_grni_clearing",
            source_id=invoice.id,
            source_number=invoice.invoice_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="draft",
            is_auto_generated=True,
            created_by=self.user_id
        )
        self.db.add(entry)
        self.db.flush()

        lines = []
        line_number = 1

        # DR: GRNI (Clear the cost accrual from GRN) - subtotal only
        grni_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=grni_account_id,
            debit=Decimal(str(round(grn_subtotal, 2))),
            credit=Decimal('0'),
            description=f"Clear GRNI for GRN {grn.grn_number}",
            line_number=line_number,
            address_book_id=invoice.address_book_id
        )
        self.db.add(grni_line)
        lines.append(grni_line)
        line_number += 1

        # DR: VAT Payable (Recognize input VAT from invoice)
        if invoice_tax > 0 and vat_account_id:
            vat_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=vat_account_id,
                debit=Decimal(str(round(invoice_tax, 2))),
                credit=Decimal('0'),
                description=f"Input VAT for Invoice {invoice.supplier_invoice_number or invoice.invoice_number}",
                line_number=line_number,
                address_book_id=invoice.address_book_id
            )
            self.db.add(vat_line)
            lines.append(vat_line)
            line_number += 1
        elif invoice_tax > 0:
            logger.warning(f"VAT account (2141) not found. VAT of {invoice_tax} will not be recorded separately.")

        # Handle price variance if any (based on subtotals, not totals)
        if abs(price_variance) > 0.01:
            variance_mapping = self._get_mapping("purchase_price_variance")
            if variance_mapping:
                variance_account_id = variance_mapping.debit_account_id if price_variance > 0 else variance_mapping.credit_account_id
                if variance_account_id:
                    variance_line = JournalEntryLine(
                        journal_entry_id=entry.id,
                        account_id=variance_account_id,
                        debit=Decimal(str(abs(round(price_variance, 2)))) if price_variance > 0 else Decimal('0'),
                        credit=Decimal('0') if price_variance > 0 else Decimal(str(abs(round(price_variance, 2)))),
                        description=f"Price variance - Invoice vs GRN ({price_variance:+.2f})",
                        line_number=line_number,
                        address_book_id=invoice.address_book_id
                    )
                    self.db.add(variance_line)
                    lines.append(variance_line)
                    line_number += 1

        # CR: Accounts Payable (Create formal liability for full invoice including VAT)
        ap_line = JournalEntryLine(
            journal_entry_id=entry.id,
            account_id=ap_account_id,
            debit=Decimal('0'),
            credit=Decimal(str(round(invoice_total, 2))),
            description=f"AP for Invoice {invoice.supplier_invoice_number or invoice.invoice_number}",
            line_number=line_number,
            address_book_id=invoice.address_book_id
        )
        self.db.add(ap_line)
        lines.append(ap_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        # Post immediately
        entry.status = "posted"
        entry.posted_at = datetime.utcnow()
        entry.posted_by = self.user_id

        self.db.commit()
        logger.info(f"Created GRNI clearing entry {entry.entry_number} for invoice {invoice.invoice_number}")

        return entry


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_supplier_invoice(
    data: SupplierInvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new supplier invoice.
    Optionally links to PO and GRN for three-way matching.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    # Validate vendor
    vendor = db.query(AddressBook).filter(
        AddressBook.id == data.address_book_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == 'V'
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Check for duplicate supplier invoice number
    if data.supplier_invoice_number:
        existing = db.query(SupplierInvoice).filter(
            SupplierInvoice.company_id == current_user.company_id,
            SupplierInvoice.address_book_id == data.address_book_id,
            SupplierInvoice.supplier_invoice_number == data.supplier_invoice_number
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Invoice {data.supplier_invoice_number} from this vendor already exists"
            )

    # Validate PO if provided
    po = None
    if data.purchase_order_id:
        po = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == data.purchase_order_id,
            PurchaseOrder.company_id == current_user.company_id
        ).first()
        if not po:
            raise HTTPException(status_code=404, detail="Purchase Order not found")

    # Validate GRN if provided, or auto-find GRN from PO
    grn = None
    goods_receipt_id = data.goods_receipt_id

    if goods_receipt_id:
        # Explicit GRN provided
        grn = db.query(GoodsReceipt).filter(
            GoodsReceipt.id == goods_receipt_id,
            GoodsReceipt.company_id == current_user.company_id,
            GoodsReceipt.status == 'accepted'
        ).first()
        if not grn:
            raise HTTPException(status_code=404, detail="Goods Receipt not found or not accepted")
    elif data.purchase_order_id:
        # Auto-find GRN for the PO (get the most recent accepted GRN)
        grn = db.query(GoodsReceipt).filter(
            GoodsReceipt.purchase_order_id == data.purchase_order_id,
            GoodsReceipt.company_id == current_user.company_id,
            GoodsReceipt.status == 'accepted'
        ).order_by(GoodsReceipt.created_at.desc()).first()
        if grn:
            goods_receipt_id = grn.id

    # Calculate due date
    due_date = calculate_due_date(data.invoice_date, data.payment_terms_days)

    # Calculate totals from lines
    subtotal = sum(line.quantity * line.unit_price for line in data.lines)
    tax_amount = data.tax_amount or sum(line.tax_amount for line in data.lines)
    total_amount = subtotal + tax_amount

    # Convert to base currency
    exchange_rate = Decimal(str(data.exchange_rate))
    subtotal_base = Decimal(str(subtotal)) * exchange_rate
    tax_amount_base = Decimal(str(tax_amount)) * exchange_rate
    total_amount_base = Decimal(str(total_amount)) * exchange_rate

    # Create invoice
    invoice = SupplierInvoice(
        company_id=current_user.company_id,
        invoice_number=generate_invoice_number(db, current_user.company_id),
        address_book_id=data.address_book_id,
        supplier_invoice_number=data.supplier_invoice_number,
        invoice_date=data.invoice_date,
        received_date=data.received_date or date.today(),
        due_date=due_date,
        payment_terms=data.payment_terms,
        payment_terms_days=data.payment_terms_days,
        early_payment_discount_percent=data.early_payment_discount_percent,
        early_payment_discount_days=data.early_payment_discount_days,
        purchase_order_id=data.purchase_order_id,
        goods_receipt_id=goods_receipt_id,  # May be auto-populated from PO
        processed_image_id=data.processed_image_id,
        currency=data.currency,
        exchange_rate=exchange_rate,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        subtotal_base=subtotal_base,
        tax_amount_base=tax_amount_base,
        total_amount_base=total_amount_base,
        amount_remaining=total_amount,
        status='draft',
        notes=data.notes,
        created_by=current_user.id
    )
    db.add(invoice)
    db.flush()

    # Create invoice lines
    for idx, line_data in enumerate(data.lines, 1):
        total_price = Decimal(str(line_data.quantity)) * Decimal(str(line_data.unit_price))

        line = SupplierInvoiceLine(
            supplier_invoice_id=invoice.id,
            line_number=idx,
            item_id=line_data.item_id,
            item_code=line_data.item_code,
            description=line_data.description,
            quantity=line_data.quantity,
            unit=line_data.unit,
            unit_price=line_data.unit_price,
            total_price=total_price,
            tax_amount=line_data.tax_amount,
            po_line_id=line_data.po_line_id,
            grn_line_id=line_data.grn_line_id,
            account_id=line_data.account_id,
            notes=line_data.notes
        )
        db.add(line)

    db.commit()
    db.refresh(invoice)

    return {
        "message": "Supplier invoice created successfully",
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "total_amount": float(invoice.total_amount),
        "due_date": str(invoice.due_date)
    }


@router.get("/")
def list_supplier_invoices(
    status: Optional[str] = None,
    vendor_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    overdue_only: bool = False,
    on_hold: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List supplier invoices with filters"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    query = db.query(SupplierInvoice).filter(
        SupplierInvoice.company_id == current_user.company_id
    ).options(
        joinedload(SupplierInvoice.address_book),
        joinedload(SupplierInvoice.purchase_order),
        joinedload(SupplierInvoice.goods_receipt)
    )

    if status:
        query = query.filter(SupplierInvoice.status == status)
    if vendor_id:
        query = query.filter(SupplierInvoice.address_book_id == vendor_id)
    if from_date:
        query = query.filter(SupplierInvoice.invoice_date >= from_date)
    if to_date:
        query = query.filter(SupplierInvoice.invoice_date <= to_date)
    if overdue_only:
        query = query.filter(
            SupplierInvoice.due_date < date.today(),
            SupplierInvoice.status.in_(['draft', 'pending_approval', 'approved', 'partially_paid'])
        )
    if on_hold is not None:
        query = query.filter(SupplierInvoice.is_on_hold == on_hold)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                SupplierInvoice.invoice_number.ilike(search_pattern),
                SupplierInvoice.supplier_invoice_number.ilike(search_pattern)
            )
        )

    total = query.count()
    skip = (page - 1) * page_size
    invoices = query.order_by(SupplierInvoice.invoice_date.desc()).offset(skip).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "supplier_invoice_number": inv.supplier_invoice_number,
                "vendor_name": inv.address_book.alpha_name if inv.address_book else None,
                "vendor": {
                    "id": inv.address_book.id,
                    "name": inv.address_book.alpha_name
                } if inv.address_book else None,
                "invoice_date": str(inv.invoice_date),
                "due_date": str(inv.due_date) if inv.due_date else None,
                "total_amount": float(inv.total_amount),
                "amount_paid": float(inv.amount_paid),
                "amount_remaining": float(inv.amount_remaining),
                "currency": inv.currency,
                "status": inv.status,
                "is_matched": inv.match_status == 'matched',
                "match_status": inv.match_status,
                "on_hold": inv.is_on_hold,
                "is_on_hold": inv.is_on_hold,
                "is_overdue": inv.due_date and inv.due_date < date.today() and inv.status not in ['paid', 'cancelled'],
                "po_number": inv.purchase_order.po_number if inv.purchase_order else None,
                "grn_number": inv.goods_receipt.grn_number if inv.goods_receipt else None
            }
            for inv in invoices
        ]
    }


@router.get("/{invoice_id}")
def get_supplier_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get supplier invoice details"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).options(
        joinedload(SupplierInvoice.address_book),
        joinedload(SupplierInvoice.purchase_order),
        joinedload(SupplierInvoice.goods_receipt),
        joinedload(SupplierInvoice.lines),
        joinedload(SupplierInvoice.payments)
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "supplier_invoice_number": invoice.supplier_invoice_number,
        "address_book_id": invoice.address_book_id,
        "vendor_name": invoice.address_book.alpha_name if invoice.address_book else None,
        "vendor": {
            "id": invoice.address_book.id,
            "name": invoice.address_book.alpha_name,
            "address_number": invoice.address_book.address_number
        } if invoice.address_book else None,
        "invoice_date": str(invoice.invoice_date),
        "received_date": str(invoice.received_date) if invoice.received_date else None,
        "due_date": str(invoice.due_date) if invoice.due_date else None,
        "payment_terms": invoice.payment_terms,
        "payment_terms_days": invoice.payment_terms_days,
        "currency": invoice.currency,
        "exchange_rate": float(invoice.exchange_rate),
        "subtotal": float(invoice.subtotal),
        "tax_amount": float(invoice.tax_amount),
        "total_amount": float(invoice.total_amount),
        "amount_paid": float(invoice.amount_paid),
        "amount_remaining": float(invoice.amount_remaining),
        "status": invoice.status,
        "is_matched": invoice.match_status == 'matched',
        "match_status": invoice.match_status,
        "match_variance": float(invoice.po_variance_amount or 0) + float(invoice.grn_variance_amount or 0),
        "po_variance_amount": float(invoice.po_variance_amount) if invoice.po_variance_amount else 0,
        "grn_variance_amount": float(invoice.grn_variance_amount) if invoice.grn_variance_amount else 0,
        "variance_explanation": invoice.variance_explanation,
        "approval_status": invoice.approval_status,
        "is_on_hold": invoice.is_on_hold,
        "is_grni_cleared": invoice.is_grni_cleared if hasattr(invoice, 'is_grni_cleared') else False,
        "grni_journal_entry_id": invoice.grni_clearing_entry_id,
        "hold_reason": invoice.hold_reason,
        "purchase_order_id": invoice.purchase_order_id,
        "po_number": invoice.purchase_order.po_number if invoice.purchase_order else None,
        "purchase_order": {
            "id": invoice.purchase_order.id,
            "po_number": invoice.purchase_order.po_number
        } if invoice.purchase_order else None,
        "goods_receipt_id": invoice.goods_receipt_id,
        "grn_number": invoice.goods_receipt.grn_number if invoice.goods_receipt else None,
        "goods_receipt": {
            "id": invoice.goods_receipt.id,
            "grn_number": invoice.goods_receipt.grn_number
        } if invoice.goods_receipt else None,
        "lines": [
            {
                "id": line.id,
                "line_number": line.line_number,
                "item_code": line.item_code,
                "description": line.description,
                "quantity": float(line.quantity),
                "unit": line.unit,
                "unit_price": float(line.unit_price),
                "total_price": float(line.total_price),
                "tax_amount": float(line.tax_amount),
                "has_variance": line.has_variance,
                "quantity_variance": float(line.quantity_variance) if line.quantity_variance else 0,
                "price_variance": float(line.price_variance) if line.price_variance else 0,
                "po_line_id": line.po_line_id,
                "grn_line_id": line.grn_line_id
            }
            for line in invoice.lines
        ],
        "notes": invoice.notes,
        "created_at": str(invoice.created_at)
    }


@router.delete("/{invoice_id}")
def delete_supplier_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a supplier invoice (only if in draft status)"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status != 'draft':
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice with status '{invoice.status}'. Only draft invoices can be deleted."
        )

    if invoice.amount_paid > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete invoice with payments applied"
        )

    # Delete invoice lines first
    db.query(SupplierInvoiceLine).filter(
        SupplierInvoiceLine.supplier_invoice_id == invoice_id
    ).delete()

    # Delete the invoice
    db.delete(invoice)
    db.commit()

    return {"message": f"Invoice {invoice.invoice_number} deleted successfully"}


@router.post("/{invoice_id}/match")
def perform_invoice_matching(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Perform three-way matching for an invoice.
    Compares invoice amounts against PO and GRN.
    If matched successfully, creates GRNI clearing entry.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).options(
        joinedload(SupplierInvoice.lines),
        joinedload(SupplierInvoice.address_book)
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status not in ['draft', 'pending_approval']:
        raise HTTPException(status_code=400, detail="Invoice cannot be matched in current status")

    # Get PO and GRN
    po = None
    grn = None

    if invoice.purchase_order_id:
        po = db.query(PurchaseOrder).get(invoice.purchase_order_id)
    if invoice.goods_receipt_id:
        grn = db.query(GoodsReceipt).get(invoice.goods_receipt_id)

    if not po and not grn:
        raise HTTPException(
            status_code=400,
            detail="Invoice must be linked to a PO or GRN for three-way matching"
        )

    # Perform matching
    match_result = perform_three_way_match(db, invoice, po, grn)

    # Update invoice with match results
    invoice.match_status = 'matched' if match_result["is_matched"] else 'variance'
    invoice.po_variance_amount = match_result["po_variance"]
    invoice.grn_variance_amount = match_result["grn_variance"]

    # Update line-level variances
    for line in invoice.lines:
        for detail in match_result["variance_details"]:
            if detail["invoice_line_id"] == line.id:
                line.quantity_variance = detail.get("qty_variance", 0)
                line.price_variance = detail.get("price_variance", 0)
                line.has_variance = abs(detail.get("qty_variance", 0)) > 0.001 or abs(detail.get("price_variance", 0)) > 0.001

    # If matched and GRN exists, create GRNI clearing entry
    grni_entry = None
    if match_result["is_matched"] and grn:
        clearing_service = GRNIClearingService(db, current_user.company_id, current_user.id)
        grni_entry = clearing_service.clear_grni(invoice, grn)
        if grni_entry:
            invoice.grni_clearing_entry_id = grni_entry.id
            invoice.status = 'pending_approval'

    db.commit()

    return {
        "message": "Three-way matching completed",
        "match_result": match_result,
        "invoice_status": invoice.status,
        "match_status": invoice.match_status,
        "grni_cleared": grni_entry is not None,
        "grni_entry_number": grni_entry.entry_number if grni_entry else None
    }


@router.post("/{invoice_id}/approve")
def approve_invoice(
    invoice_id: int,
    request: InvoiceApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Approve or reject a supplier invoice"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status not in ['draft', 'pending_approval']:
        raise HTTPException(status_code=400, detail="Invoice cannot be approved in current status")

    if request.action == 'approve':
        invoice.approval_status = 'approved'
        invoice.status = 'approved'
        invoice.approved_by = current_user.id
        invoice.approved_at = datetime.utcnow()
    elif request.action == 'reject':
        if not request.reason:
            raise HTTPException(status_code=400, detail="Rejection reason is required")
        invoice.approval_status = 'rejected'
        invoice.status = 'cancelled'
        invoice.rejection_reason = request.reason
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'approve' or 'reject'")

    db.commit()

    # Reload invoice with all relations for full response
    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).options(
        joinedload(SupplierInvoice.address_book),
        joinedload(SupplierInvoice.purchase_order),
        joinedload(SupplierInvoice.goods_receipt),
        joinedload(SupplierInvoice.lines),
        joinedload(SupplierInvoice.payments)
    ).first()

    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "supplier_invoice_number": invoice.supplier_invoice_number,
        "address_book_id": invoice.address_book_id,
        "vendor_name": invoice.address_book.alpha_name if invoice.address_book else None,
        "vendor": {
            "id": invoice.address_book.id,
            "name": invoice.address_book.alpha_name,
            "address_number": invoice.address_book.address_number
        } if invoice.address_book else None,
        "invoice_date": str(invoice.invoice_date),
        "received_date": str(invoice.received_date) if invoice.received_date else None,
        "due_date": str(invoice.due_date) if invoice.due_date else None,
        "payment_terms": invoice.payment_terms,
        "payment_terms_days": invoice.payment_terms_days,
        "currency": invoice.currency,
        "exchange_rate": float(invoice.exchange_rate),
        "subtotal": float(invoice.subtotal),
        "tax_amount": float(invoice.tax_amount),
        "total_amount": float(invoice.total_amount),
        "amount_paid": float(invoice.amount_paid),
        "amount_remaining": float(invoice.amount_remaining),
        "status": invoice.status,
        "is_matched": invoice.match_status == 'matched',
        "match_status": invoice.match_status,
        "match_variance": float(invoice.po_variance_amount or 0) + float(invoice.grn_variance_amount or 0),
        "po_variance_amount": float(invoice.po_variance_amount) if invoice.po_variance_amount else 0,
        "grn_variance_amount": float(invoice.grn_variance_amount) if invoice.grn_variance_amount else 0,
        "variance_explanation": invoice.variance_explanation,
        "approval_status": invoice.approval_status,
        "is_on_hold": invoice.is_on_hold,
        "is_grni_cleared": invoice.is_grni_cleared if hasattr(invoice, 'is_grni_cleared') else False,
        "grni_journal_entry_id": invoice.grni_clearing_entry_id,
        "hold_reason": invoice.hold_reason,
        "purchase_order_id": invoice.purchase_order_id,
        "po_number": invoice.purchase_order.po_number if invoice.purchase_order else None,
        "purchase_order": {
            "id": invoice.purchase_order.id,
            "po_number": invoice.purchase_order.po_number
        } if invoice.purchase_order else None,
        "goods_receipt_id": invoice.goods_receipt_id,
        "grn_number": invoice.goods_receipt.grn_number if invoice.goods_receipt else None,
        "goods_receipt": {
            "id": invoice.goods_receipt.id,
            "grn_number": invoice.goods_receipt.grn_number
        } if invoice.goods_receipt else None,
        "lines": [
            {
                "id": line.id,
                "line_number": line.line_number,
                "item_code": line.item_code,
                "description": line.description,
                "quantity": float(line.quantity),
                "unit": line.unit,
                "unit_price": float(line.unit_price),
                "total_price": float(line.total_price),
                "tax_amount": float(line.tax_amount),
                "has_variance": line.has_variance,
                "quantity_variance": float(line.quantity_variance) if line.quantity_variance else 0,
                "price_variance": float(line.price_variance) if line.price_variance else 0,
                "po_line_id": line.po_line_id,
                "grn_line_id": line.grn_line_id
            }
            for line in invoice.lines
        ],
        "notes": invoice.notes,
        "created_at": str(invoice.created_at)
    }


@router.post("/{invoice_id}/submit")
def submit_invoice_for_approval(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Submit a draft invoice for approval"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status != 'draft':
        raise HTTPException(
            status_code=400,
            detail=f"Only draft invoices can be submitted. Current status: {invoice.status}"
        )

    # Check that invoice has lines
    if not invoice.lines or len(invoice.lines) == 0:
        raise HTTPException(status_code=400, detail="Invoice must have at least one line item")

    # Update status to pending approval
    invoice.status = 'pending_approval'
    invoice.approval_status = 'pending'
    db.commit()
    db.refresh(invoice)

    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "status": invoice.status,
        "message": "Invoice submitted for approval"
    }


@router.post("/{invoice_id}/hold")
def hold_invoice(
    invoice_id: int,
    request: InvoiceHoldRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Put invoice on payment hold or release from hold"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if request.action == 'hold':
        if not request.reason:
            raise HTTPException(status_code=400, detail="Hold reason is required")
        invoice.is_on_hold = True
        invoice.hold_reason = request.reason
        invoice.hold_by = current_user.id
        invoice.hold_at = datetime.utcnow()
        message = "Invoice placed on hold"
    elif request.action == 'release':
        invoice.is_on_hold = False
        invoice.hold_reason = None
        invoice.hold_by = None
        invoice.hold_at = None
        message = "Invoice released from hold"
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'hold' or 'release'")

    db.commit()

    return {"message": message, "is_on_hold": invoice.is_on_hold}


@router.get("/{invoice_id}/three-way-match")
def get_three_way_match_details(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed three-way match comparison for an invoice"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).options(joinedload(SupplierInvoice.lines)).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    po = None
    grn = None

    if invoice.purchase_order_id:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.lines)
        ).get(invoice.purchase_order_id)

    if invoice.goods_receipt_id:
        grn = db.query(GoodsReceipt).options(
            joinedload(GoodsReceipt.lines)
        ).get(invoice.goods_receipt_id)

    return {
        "invoice": {
            "number": invoice.invoice_number,
            "subtotal": float(invoice.subtotal),
            "tax": float(invoice.tax_amount),
            "total": float(invoice.total_amount)
        },
        "purchase_order": {
            "number": po.po_number if po else None,
            "subtotal": float(po.subtotal) if po else 0,
            "tax": float(po.tax_amount) if po else 0,
            "total": float(po.total_amount) if po else 0
        } if po else None,
        "goods_receipt": {
            "number": grn.grn_number if grn else None,
            "subtotal": float(grn.subtotal) if grn else 0,
            "tax": float(grn.tax_amount) if grn else 0,
            "total": float(grn.total_amount) if grn else 0
        } if grn else None,
        "match_result": perform_three_way_match(db, invoice, po, grn)
    }


@router.post("/{invoice_id}/three-way-match")
def execute_three_way_match(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Execute three-way matching for an invoice (POST version).
    Returns match result with matched status and variance details.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).options(joinedload(SupplierInvoice.lines)).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    po = None
    grn = None

    if invoice.purchase_order_id:
        po = db.query(PurchaseOrder).options(
            joinedload(PurchaseOrder.lines)
        ).get(invoice.purchase_order_id)

    if invoice.goods_receipt_id:
        grn = db.query(GoodsReceipt).options(
            joinedload(GoodsReceipt.lines)
        ).get(invoice.goods_receipt_id)

    if not po and not grn:
        raise HTTPException(
            status_code=400,
            detail="Invoice must be linked to a PO or GRN for three-way matching"
        )

    # Perform matching
    match_result = perform_three_way_match(db, invoice, po, grn)

    # Update invoice match status
    invoice.match_status = 'matched' if match_result["is_matched"] else 'variance'
    invoice.po_variance_amount = match_result.get("po_variance", 0)
    invoice.grn_variance_amount = match_result.get("grn_variance", 0)
    db.commit()

    return {
        "matched": match_result["is_matched"],
        "variance": match_result.get("total_variance", 0),
        "details": {
            "invoice": {
                "number": invoice.invoice_number,
                "total": float(invoice.total_amount)
            },
            "purchase_order": {
                "number": po.po_number if po else None,
                "total": float(po.total_amount) if po else 0
            } if po else None,
            "goods_receipt": {
                "number": grn.grn_number if grn else None,
                "total": float(grn.total_amount) if grn else 0
            } if grn else None,
            "po_variance": match_result.get("po_variance", 0),
            "grn_variance": match_result.get("grn_variance", 0),
            "is_within_tolerance": match_result.get("is_within_tolerance", False)
        }
    }


@router.post("/{invoice_id}/clear-grni")
def clear_grni_for_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Clear GRNI (Goods Received Not Invoiced) for an approved invoice.

    This creates a journal entry that:
    - Debits GRNI account (clears the accrual from GRN)
    - Credits Accounts Payable (establishes formal payable)
    - Records any variance to Price Variance account
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    invoice = db.query(SupplierInvoice).filter(
        SupplierInvoice.id == invoice_id,
        SupplierInvoice.company_id == current_user.company_id
    ).options(
        joinedload(SupplierInvoice.address_book),
        joinedload(SupplierInvoice.goods_receipt)
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status != 'approved':
        raise HTTPException(
            status_code=400,
            detail=f"GRNI can only be cleared for approved invoices. Current status: {invoice.status}"
        )

    if invoice.match_status != 'matched':
        raise HTTPException(
            status_code=400,
            detail="Invoice must be matched (three-way match) before GRNI can be cleared"
        )

    if invoice.is_grni_cleared:
        raise HTTPException(
            status_code=400,
            detail="GRNI has already been cleared for this invoice"
        )

    if not invoice.goods_receipt_id:
        raise HTTPException(
            status_code=400,
            detail="Invoice must be linked to a GRN for GRNI clearing"
        )

    grn = invoice.goods_receipt
    if not grn:
        grn = db.query(GoodsReceipt).get(invoice.goods_receipt_id)

    if not grn:
        raise HTTPException(
            status_code=400,
            detail="Linked GRN not found"
        )

    # Create GRNI clearing journal entry
    clearing_service = GRNIClearingService(db, current_user.company_id, current_user.id)
    grni_entry = clearing_service.clear_grni(invoice, grn)

    if not grni_entry:
        raise HTTPException(
            status_code=500,
            detail="Failed to create GRNI clearing entry. Please check account mappings (GRNI and AP accounts)."
        )

    # Update invoice
    invoice.is_grni_cleared = True
    invoice.grni_clearing_entry_id = grni_entry.id
    db.commit()

    return {
        "message": "GRNI cleared successfully",
        "journal_entry_id": grni_entry.id,
        "journal_entry_number": grni_entry.entry_number
    }


# =============================================================================
# REPORTING ENDPOINTS
# =============================================================================

@router.get("/reports/aging")
def get_invoice_aging_report(
    as_of_date: Optional[date] = None,
    vendor_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get accounts payable aging report.
    Shows invoices grouped by age buckets: Current, 1-30, 31-60, 61-90, 90+
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    report_date = as_of_date or date.today()

    query = db.query(SupplierInvoice).filter(
        SupplierInvoice.company_id == current_user.company_id,
        SupplierInvoice.status.in_(['approved', 'partially_paid']),
        SupplierInvoice.amount_remaining > 0
    ).options(joinedload(SupplierInvoice.address_book))

    if vendor_id:
        query = query.filter(SupplierInvoice.address_book_id == vendor_id)

    invoices = query.all()

    # Initialize aging buckets
    aging = {
        "current": {"invoices": [], "total": 0},
        "1_30": {"invoices": [], "total": 0},
        "31_60": {"invoices": [], "total": 0},
        "61_90": {"invoices": [], "total": 0},
        "over_90": {"invoices": [], "total": 0}
    }

    for inv in invoices:
        days_outstanding = (report_date - inv.due_date).days if inv.due_date else 0
        remaining = float(inv.amount_remaining)

        inv_data = {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "vendor": inv.address_book.alpha_name if inv.address_book else "Unknown",
            "invoice_date": str(inv.invoice_date),
            "due_date": str(inv.due_date) if inv.due_date else None,
            "days_outstanding": days_outstanding,
            "amount_remaining": remaining
        }

        if days_outstanding <= 0:
            aging["current"]["invoices"].append(inv_data)
            aging["current"]["total"] += remaining
        elif days_outstanding <= 30:
            aging["1_30"]["invoices"].append(inv_data)
            aging["1_30"]["total"] += remaining
        elif days_outstanding <= 60:
            aging["31_60"]["invoices"].append(inv_data)
            aging["31_60"]["total"] += remaining
        elif days_outstanding <= 90:
            aging["61_90"]["invoices"].append(inv_data)
            aging["61_90"]["total"] += remaining
        else:
            aging["over_90"]["invoices"].append(inv_data)
            aging["over_90"]["total"] += remaining

    grand_total = sum(bucket["total"] for bucket in aging.values())

    return {
        "as_of_date": str(report_date),
        "aging": aging,
        "grand_total": grand_total,
        "total_invoices": len(invoices)
    }


@router.get("/reports/grni-aging")
def get_grni_aging_report(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get GRNI (Goods Received Not Invoiced) aging report.
    Shows GRNs that have been posted but don't have matched invoices.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    report_date = as_of_date or date.today()

    # Find GRNs without matched invoices
    # A GRN is considered "open" if there's no supplier invoice linked to it
    grns_with_invoices = db.query(SupplierInvoice.goods_receipt_id).filter(
        SupplierInvoice.company_id == current_user.company_id,
        SupplierInvoice.goods_receipt_id.isnot(None),
        SupplierInvoice.status != 'cancelled'
    ).subquery()

    open_grns = db.query(GoodsReceipt).filter(
        GoodsReceipt.company_id == current_user.company_id,
        GoodsReceipt.status == 'accepted',
        ~GoodsReceipt.id.in_(grns_with_invoices)
    ).options(
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book)
    ).all()

    # Group by age
    aging = {
        "0_30": {"grns": [], "total": 0},
        "31_60": {"grns": [], "total": 0},
        "61_90": {"grns": [], "total": 0},
        "over_90": {"grns": [], "total": 0}
    }

    for grn in open_grns:
        days_outstanding = (report_date - grn.receipt_date).days if grn.receipt_date else 0
        amount = float(grn.subtotal or 0) + float(grn.tax_amount or 0)

        grn_data = {
            "id": grn.id,
            "grn_number": grn.grn_number,
            "receipt_date": str(grn.receipt_date),
            "days_outstanding": days_outstanding,
            "amount": amount,
            "po_number": grn.purchase_order.po_number if grn.purchase_order else None,
            "vendor": grn.purchase_order.address_book.alpha_name if grn.purchase_order and grn.purchase_order.address_book else "Unknown"
        }

        if days_outstanding <= 30:
            aging["0_30"]["grns"].append(grn_data)
            aging["0_30"]["total"] += amount
        elif days_outstanding <= 60:
            aging["31_60"]["grns"].append(grn_data)
            aging["31_60"]["total"] += amount
        elif days_outstanding <= 90:
            aging["61_90"]["grns"].append(grn_data)
            aging["61_90"]["total"] += amount
        else:
            aging["over_90"]["grns"].append(grn_data)
            aging["over_90"]["total"] += amount

    grand_total = sum(bucket["total"] for bucket in aging.values())

    return {
        "as_of_date": str(report_date),
        "aging": aging,
        "grand_total": grand_total,
        "total_grns": len(open_grns),
        "description": "GRNs posted but not yet invoiced - GRNI liability on books"
    }
