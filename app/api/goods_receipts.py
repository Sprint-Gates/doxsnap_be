"""
Goods Receipt Note (GRN) API endpoints for professional partial PO receiving.

Features:
- Create GRN from PO with warehouse selection
- Partial receiving with multiple GRNs per PO
- Quality inspection workflow
- Lot/serial number tracking
- Multi-location receiving
- Automatic journal entry posting
- Three-way matching (PO vs GRN vs Invoice)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
import logging
import json

from app.database import get_db
from app.models import (
    User, PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine,
    GoodsReceiptExtraCost, ItemMaster, ItemStock, ItemLedger, Warehouse, Account,
    PurchaseOrderInvoice, AddressBook
)
from app.api.auth import get_current_user
from app.services.journal_posting import JournalPostingService
from app.services.landed_cost import LandedCostService, get_effective_unit_cost, get_effective_total_cost

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

class GoodsReceiptLineCreate(BaseModel):
    po_line_id: int
    quantity_received: float
    warehouse_id: Optional[int] = None
    bin_location: Optional[str] = None
    lot_number: Optional[str] = None
    serial_numbers: Optional[str] = None  # JSON array
    expiry_date: Optional[date] = None
    manufacture_date: Optional[date] = None
    notes: Optional[str] = None


class GoodsReceiptCreate(BaseModel):
    purchase_order_id: int
    receipt_date: date
    warehouse_id: Optional[int] = None
    supplier_delivery_note: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    inspection_required: bool = False
    notes: Optional[str] = None
    lines: List[GoodsReceiptLineCreate]


class GoodsReceiptLineUpdate(BaseModel):
    quantity_received: Optional[float] = None
    quantity_accepted: Optional[float] = None
    quantity_rejected: Optional[float] = None
    warehouse_id: Optional[int] = None
    bin_location: Optional[str] = None
    lot_number: Optional[str] = None
    serial_numbers: Optional[str] = None
    expiry_date: Optional[date] = None
    inspection_status: Optional[str] = None
    rejection_reason: Optional[str] = None
    inspection_notes: Optional[str] = None
    notes: Optional[str] = None


class GoodsReceiptUpdate(BaseModel):
    receipt_date: Optional[date] = None
    warehouse_id: Optional[int] = None
    supplier_delivery_note: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    inspection_required: Optional[bool] = None
    notes: Optional[str] = None


class InspectionResult(BaseModel):
    line_id: int
    quantity_accepted: float
    quantity_rejected: float = 0
    rejection_reason: Optional[str] = None
    inspection_notes: Optional[str] = None


class GRNInspectionRequest(BaseModel):
    inspection_notes: Optional[str] = None
    line_results: List[InspectionResult]


class GoodsReceiptLineResponse(BaseModel):
    id: int
    po_line_id: int
    item_id: Optional[int]
    item_code: Optional[str]
    item_description: Optional[str]
    quantity_ordered: float
    quantity_received: float
    quantity_accepted: float
    quantity_rejected: float
    unit: str
    warehouse_id: Optional[int]
    warehouse_name: Optional[str] = None
    bin_location: Optional[str]
    lot_number: Optional[str]
    serial_numbers: Optional[str]
    expiry_date: Optional[date]
    manufacture_date: Optional[date]
    unit_price: float
    total_price: float
    # Landed cost fields
    allocated_extra_cost: float = 0
    landed_unit_cost: Optional[float] = None
    landed_total_cost: Optional[float] = None
    inspection_status: str
    rejection_reason: Optional[str]
    has_variance: bool
    variance_type: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True


class GoodsReceiptExtraCostResponse(BaseModel):
    id: int
    goods_receipt_id: int
    cost_type: str
    cost_description: Optional[str]
    amount: float
    currency: str
    vendor_id: Optional[int]
    vendor_name: Optional[str] = None
    reference_number: Optional[str]
    notes: Optional[str]
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class GoodsReceiptResponse(BaseModel):
    id: int
    grn_number: str
    purchase_order_id: int
    po_number: Optional[str] = None
    vendor_name: Optional[str] = None
    receipt_date: date
    warehouse_id: Optional[int]
    warehouse_name: Optional[str] = None
    supplier_delivery_note: Optional[str]
    carrier: Optional[str]
    tracking_number: Optional[str]
    status: str
    inspection_required: bool
    inspection_status: Optional[str]
    inspected_by_name: Optional[str] = None
    inspected_at: Optional[datetime]
    currency: str
    subtotal: float
    tax_amount: float
    total_amount: float
    # Landed cost fields
    is_import: bool = False
    total_extra_costs: float = 0
    total_landed_cost: float = 0
    journal_entry_id: Optional[int]
    notes: Optional[str]
    created_by_name: Optional[str] = None
    created_at: datetime
    lines: List[GoodsReceiptLineResponse] = []
    extra_costs: List[GoodsReceiptExtraCostResponse] = []

    class Config:
        from_attributes = True


class POReceivingStatus(BaseModel):
    po_id: int
    po_number: str
    total_ordered: float
    total_received: float
    total_pending: float
    percent_received: float
    status: str
    lines: List[dict]


class ThreeWayMatchResult(BaseModel):
    po_id: int
    po_number: str
    po_total: float
    grn_total: float
    invoice_total: float
    is_matched: bool
    variance: float
    variance_percent: float
    details: List[dict]


# Extra cost types for imports
EXTRA_COST_TYPES = [
    ("freight", "Freight/Shipping"),
    ("duty", "Import Duties/Tariffs"),
    ("port_handling", "Port/Handling Charges"),
    ("customs", "Customs Clearance Fees"),
    ("insurance", "Cargo Insurance"),
    ("other", "Other Charges"),
]


class GoodsReceiptExtraCostCreate(BaseModel):
    cost_type: str  # freight, duty, port_handling, customs, insurance, other
    cost_description: Optional[str] = None
    amount: Decimal
    currency: str = "USD"
    vendor_id: Optional[int] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class GoodsReceiptExtraCostUpdate(BaseModel):
    cost_type: Optional[str] = None
    cost_description: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    vendor_id: Optional[int] = None
    reference_number: Optional[str] = None
    notes: Optional[str] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_grn_number(db: Session, company_id: int) -> str:
    """Generate next GRN number for company"""
    year = datetime.now().year
    prefix = f"GRN-{year}-"

    last_grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.company_id == company_id,
        GoodsReceipt.grn_number.like(f"{prefix}%")
    ).order_by(GoodsReceipt.id.desc()).first()

    if last_grn:
        try:
            last_num = int(last_grn.grn_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def grn_to_response(grn: GoodsReceipt, include_lines: bool = True, include_extra_costs: bool = True) -> dict:
    """Convert GoodsReceipt to response dict"""
    response = {
        "id": grn.id,
        "grn_number": grn.grn_number,
        "purchase_order_id": grn.purchase_order_id,
        "po_number": grn.purchase_order.po_number if grn.purchase_order else None,
        "vendor_name": grn.purchase_order.address_book.alpha_name if grn.purchase_order and grn.purchase_order.address_book else None,
        "receipt_date": grn.receipt_date,
        "warehouse_id": grn.warehouse_id,
        "warehouse_name": grn.warehouse.name if grn.warehouse else None,
        "supplier_delivery_note": grn.supplier_delivery_note,
        "carrier": grn.carrier,
        "tracking_number": grn.tracking_number,
        "status": grn.status,
        "inspection_required": grn.inspection_required,
        "inspection_status": grn.inspection_status,
        "inspected_by_name": grn.inspector.name if grn.inspector else None,
        "inspected_at": grn.inspected_at,
        "currency": grn.currency,
        "subtotal": float(grn.subtotal or 0),
        "tax_amount": float(grn.tax_amount or 0),
        "total_amount": float(grn.total_amount or 0),
        # Landed cost fields
        "is_import": grn.is_import or False,
        "total_extra_costs": float(grn.total_extra_costs or 0),
        "total_landed_cost": float(grn.total_landed_cost or 0),
        "journal_entry_id": grn.journal_entry_id,
        "notes": grn.notes,
        "created_by_name": grn.creator.name if grn.creator else None,
        "created_at": grn.created_at,
        "lines": [],
        "extra_costs": []
    }

    if include_lines and grn.lines:
        for line in grn.lines:
            line_data = {
                "id": line.id,
                "po_line_id": line.po_line_id,
                "item_id": line.item_id,
                "item_code": line.item_code,
                "item_description": line.item_description,
                "quantity_ordered": float(line.quantity_ordered or 0),
                "quantity_received": float(line.quantity_received or 0),
                "quantity_accepted": float(line.quantity_accepted or 0),
                "quantity_rejected": float(line.quantity_rejected or 0),
                "unit": line.unit,
                "warehouse_id": line.warehouse_id,
                "warehouse_name": line.warehouse.name if line.warehouse else None,
                "bin_location": line.bin_location,
                "lot_number": line.lot_number,
                "serial_numbers": line.serial_numbers,
                "expiry_date": line.expiry_date,
                "manufacture_date": line.manufacture_date,
                "unit_price": float(line.unit_price or 0),
                "total_price": float(line.total_price or 0),
                # Landed cost fields
                "allocated_extra_cost": float(line.allocated_extra_cost or 0),
                "landed_unit_cost": float(line.landed_unit_cost) if line.landed_unit_cost else None,
                "landed_total_cost": float(line.landed_total_cost) if line.landed_total_cost else None,
                "inspection_status": line.inspection_status,
                "rejection_reason": line.rejection_reason,
                "has_variance": line.has_variance,
                "variance_type": line.variance_type,
                "notes": line.notes
            }
            response["lines"].append(line_data)

    if include_extra_costs and hasattr(grn, 'extra_costs') and grn.extra_costs:
        for cost in grn.extra_costs:
            cost_data = {
                "id": cost.id,
                "goods_receipt_id": cost.goods_receipt_id,
                "cost_type": cost.cost_type,
                "cost_description": cost.cost_description,
                "amount": float(cost.amount or 0),
                "currency": cost.currency,
                "vendor_id": cost.address_book_id,
                "vendor_name": cost.address_book.alpha_name if cost.address_book else None,
                "reference_number": cost.reference_number,
                "notes": cost.notes,
                "created_by": cost.created_by,
                "created_by_name": cost.creator.name if cost.creator else None,
                "created_at": cost.created_at
            }
            response["extra_costs"].append(cost_data)

    return response


def update_po_line_receiving(db: Session, po_line: PurchaseOrderLine, quantity: float):
    """Update PO line cumulative received quantity and status"""
    current_received = float(po_line.quantity_received or 0)
    new_received = current_received + quantity
    po_line.quantity_received = new_received

    ordered = float(po_line.quantity_ordered or 0)
    if new_received >= ordered:
        po_line.receive_status = 'received'
    elif new_received > 0:
        po_line.receive_status = 'partial'
    else:
        po_line.receive_status = 'pending'


def update_po_status(db: Session, po: PurchaseOrder):
    """Update PO status based on line receiving status"""
    if not po.lines:
        return

    all_received = all(line.receive_status == 'received' for line in po.lines)
    any_received = any(line.receive_status in ['received', 'partial'] for line in po.lines)
    none_received = all(line.receive_status == 'pending' for line in po.lines)

    if all_received:
        po.status = 'received'
    elif any_received:
        po.status = 'partial'
    elif none_received and po.status in ['received', 'partial']:
        # If all lines are back to pending (e.g., after GRN reversal), revert to acknowledged
        po.status = 'acknowledged'


def update_inventory(db: Session, grn_line: GoodsReceiptLine, company_id: int, user_id: int):
    """
    Update inventory stock and create ledger entry.
    Uses landed cost (if available) for inventory valuation.
    """
    if not grn_line.item_id:
        logger.warning(f"GRN line {grn_line.id} has no item_id - skipping inventory update. "
                      f"Item code: {grn_line.item_code}, Description: {grn_line.item_description}")
        return None

    warehouse_id = grn_line.warehouse_id or grn_line.goods_receipt.warehouse_id
    if not warehouse_id:
        logger.warning(f"GRN line {grn_line.id} has no warehouse_id - skipping inventory update")
        return None

    # Get or create ItemStock for this warehouse
    item_stock = db.query(ItemStock).filter(
        ItemStock.item_id == grn_line.item_id,
        ItemStock.warehouse_id == warehouse_id
    ).first()

    if not item_stock:
        item_stock = ItemStock(
            company_id=company_id,
            item_id=grn_line.item_id,
            warehouse_id=warehouse_id,
            quantity_on_hand=0,
            quantity_reserved=0,
            quantity_on_order=0
        )
        db.add(item_stock)
        db.flush()

    # Get effective costs (landed cost if available, otherwise invoice price)
    effective_unit_cost = get_effective_unit_cost(grn_line)
    effective_total_cost = get_effective_total_cost(grn_line)

    # Update stock quantities
    quantity = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)
    item_stock.quantity_on_hand = (item_stock.quantity_on_hand or 0) + Decimal(str(quantity))
    item_stock.quantity_on_order = max(0, (item_stock.quantity_on_order or 0) - Decimal(str(quantity)))

    # Update average cost using landed cost (weighted average)
    current_qty = float(item_stock.quantity_on_hand or 0) - quantity
    current_avg_cost = float(item_stock.average_cost or 0)
    new_qty = quantity
    new_cost = float(effective_unit_cost)

    if current_qty + new_qty > 0:
        new_avg_cost = ((current_qty * current_avg_cost) + (new_qty * new_cost)) / (current_qty + new_qty)
        item_stock.average_cost = Decimal(str(round(new_avg_cost, 4)))

    item_stock.last_cost = effective_unit_cost  # Use landed cost as last cost
    item_stock.updated_at = datetime.utcnow()

    # Generate transaction number
    today = datetime.now().strftime("%Y%m%d")
    tx_prefix = f"GRN-{today}-"
    last_tx = db.query(ItemLedger).filter(
        ItemLedger.company_id == company_id,
        ItemLedger.transaction_number.like(f"{tx_prefix}%")
    ).order_by(ItemLedger.id.desc()).first()

    if last_tx:
        try:
            last_num = int(last_tx.transaction_number.split("-")[-1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1

    tx_number = f"{tx_prefix}{next_num:05d}"

    # Create ItemLedger entry with landed cost
    grn = grn_line.goods_receipt

    # Build notes with landed cost info if applicable
    notes = f"Received via GRN {grn.grn_number} from PO {grn.purchase_order.po_number}"
    if grn_line.allocated_extra_cost and float(grn_line.allocated_extra_cost) > 0:
        notes += f" | Landed cost includes allocated extra costs: {float(grn_line.allocated_extra_cost):.2f}"

    # Balance after receipt (stock was already updated above)
    balance_after_receipt = item_stock.quantity_on_hand

    ledger_entry = ItemLedger(
        company_id=company_id,
        item_id=grn_line.item_id,
        transaction_type="RECEIVE_GRN",
        transaction_number=tx_number,
        transaction_date=grn.receipt_date,
        quantity=Decimal(str(quantity)),
        unit=grn_line.unit,
        unit_cost=effective_unit_cost,  # Use landed cost
        total_cost=effective_total_cost,  # Use landed total cost
        to_warehouse_id=warehouse_id,
        balance_after=balance_after_receipt,  # Track running balance
        notes=notes,
        created_by=user_id
    )
    db.add(ledger_entry)
    db.flush()

    # Link ledger to GRN line
    grn_line.item_ledger_id = ledger_entry.id

    return ledger_entry


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.post("/", response_model=dict)
async def create_goods_receipt(
    grn_data: GoodsReceiptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new Goods Receipt Note (GRN) for a Purchase Order.
    Supports partial receiving - multiple GRNs can be created for one PO.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    # Validate PO exists and is receivable
    po = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.item),
        joinedload(PurchaseOrder.address_book)
    ).filter(
        PurchaseOrder.id == grn_data.purchase_order_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    if po.status not in ['sent', 'acknowledged', 'partial']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot receive against PO with status '{po.status}'. Must be sent, acknowledged, or partial."
        )

    # Require at least one linked invoice for three-way matching
    linked_invoice_count = db.query(func.count(PurchaseOrderInvoice.id)).filter(
        PurchaseOrderInvoice.purchase_order_id == po.id
    ).scalar()

    if linked_invoice_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot create GRN - Purchase Order must have at least one linked invoice for three-way matching. Please link an invoice to this PO first."
        )

    # Validate warehouse (REQUIRED)
    if not grn_data.warehouse_id:
        raise HTTPException(
            status_code=400,
            detail="Warehouse is required for goods receipt"
        )

    warehouse = db.query(Warehouse).filter(
        Warehouse.id == grn_data.warehouse_id,
        Warehouse.company_id == current_user.company_id
    ).first()
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    # Create GRN
    grn_number = generate_grn_number(db, current_user.company_id)

    grn = GoodsReceipt(
        company_id=current_user.company_id,
        grn_number=grn_number,
        purchase_order_id=grn_data.purchase_order_id,
        receipt_date=grn_data.receipt_date,
        warehouse_id=grn_data.warehouse_id,
        supplier_delivery_note=grn_data.supplier_delivery_note,
        carrier=grn_data.carrier,
        tracking_number=grn_data.tracking_number,
        status='draft',
        inspection_required=grn_data.inspection_required,
        currency=po.currency,
        notes=grn_data.notes,
        created_by=current_user.id
    )
    db.add(grn)
    db.flush()

    # Create GRN lines
    subtotal = Decimal('0')
    po_lines_map = {line.id: line for line in po.lines}

    for line_data in grn_data.lines:
        po_line = po_lines_map.get(line_data.po_line_id)
        if not po_line:
            raise HTTPException(
                status_code=400,
                detail=f"PO line {line_data.po_line_id} not found in this PO"
            )

        # Validate quantity doesn't exceed remaining
        already_received = float(po_line.quantity_received or 0)
        ordered = float(po_line.quantity_ordered or 0)
        remaining = ordered - already_received

        if line_data.quantity_received > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot receive {line_data.quantity_received} for {po_line.description}. "
                       f"Only {remaining} remaining (ordered: {ordered}, received: {already_received})"
            )

        unit_price = po_line.unit_price
        line_total = Decimal(str(line_data.quantity_received)) * unit_price

        # Auto-resolve item_id if not set on PO line
        resolved_item_id = po_line.item_id
        if not resolved_item_id and po_line.item_number:
            # Try to find ItemMaster by item_number
            item = db.query(ItemMaster).filter(
                ItemMaster.company_id == current_user.company_id,
                func.upper(ItemMaster.item_number) == po_line.item_number.upper().strip()
            ).first()
            if item:
                resolved_item_id = item.id
                # Also update the PO line for consistency
                po_line.item_id = item.id
                logger.info(f"Auto-linked PO line {po_line.id} and GRN line to ItemMaster {item.id} via item_number '{po_line.item_number}'")

        grn_line = GoodsReceiptLine(
            goods_receipt_id=grn.id,
            po_line_id=line_data.po_line_id,
            item_id=resolved_item_id,
            item_code=po_line.item.item_number if po_line.item else po_line.item_number,
            item_description=po_line.description,
            quantity_ordered=po_line.quantity_ordered,
            quantity_received=line_data.quantity_received,
            unit=po_line.unit or 'EA',
            warehouse_id=line_data.warehouse_id or grn_data.warehouse_id,
            bin_location=line_data.bin_location,
            lot_number=line_data.lot_number,
            serial_numbers=line_data.serial_numbers,
            expiry_date=line_data.expiry_date,
            manufacture_date=line_data.manufacture_date,
            unit_price=unit_price,
            total_price=line_total,
            inspection_status='pending' if grn_data.inspection_required else 'passed',
            notes=line_data.notes
        )

        # If no inspection required, quantity_accepted = quantity_received
        if not grn_data.inspection_required:
            grn_line.quantity_accepted = line_data.quantity_received

        db.add(grn_line)
        subtotal += line_total

    # Calculate totals
    tax_rate = float(po.tax_amount or 0) / float(po.subtotal) if po.subtotal else 0
    tax_amount = subtotal * Decimal(str(tax_rate))

    grn.subtotal = subtotal
    grn.tax_amount = tax_amount
    grn.total_amount = subtotal + tax_amount

    db.commit()
    db.refresh(grn)

    # Reload with relationships
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.warehouse),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.id == grn.id).first()

    return grn_to_response(grn)

@router.get("/", response_model=dict)
async def list_goods_receipts(
    purchase_order_id: Optional[int] = None,
    status: Optional[str] = None,
    warehouse_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List Goods Receipt Notes with optional filters and pagination"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    query = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.company_id == current_user.company_id)

    if purchase_order_id:
        query = query.filter(GoodsReceipt.purchase_order_id == purchase_order_id)
    if status:
        query = query.filter(GoodsReceipt.status == status)
    if warehouse_id:
        query = query.filter(GoodsReceipt.warehouse_id == warehouse_id)
    if from_date:
        query = query.filter(GoodsReceipt.receipt_date >= from_date)
    if to_date:
        query = query.filter(GoodsReceipt.receipt_date <= to_date)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (GoodsReceipt.grn_number.ilike(search_term)) |
            (GoodsReceipt.supplier_delivery_note.ilike(search_term))
        )

    # Get total count before pagination
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    grns = query.order_by(GoodsReceipt.created_at.desc()).offset(offset).limit(page_size).all()

    return {
        "items": [grn_to_response(grn, include_lines=False) for grn in grns],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{grn_id}", response_model=dict)
async def get_goods_receipt(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific Goods Receipt Note with all details"""
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.warehouse),
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.item),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator),
        joinedload(GoodsReceipt.inspector)
    ).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    return grn_to_response(grn)


@router.put("/{grn_id}", response_model=dict)
async def update_goods_receipt(
    grn_id: int,
    grn_data: GoodsReceiptUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a Goods Receipt Note (only draft status)"""
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status != 'draft':
        raise HTTPException(
            status_code=400,
            detail="Can only update GRN in draft status"
        )

    # Update fields
    if grn_data.receipt_date is not None:
        grn.receipt_date = grn_data.receipt_date
    if grn_data.warehouse_id is not None:
        grn.warehouse_id = grn_data.warehouse_id
    if grn_data.supplier_delivery_note is not None:
        grn.supplier_delivery_note = grn_data.supplier_delivery_note
    if grn_data.carrier is not None:
        grn.carrier = grn_data.carrier
    if grn_data.tracking_number is not None:
        grn.tracking_number = grn_data.tracking_number
    if grn_data.inspection_required is not None:
        grn.inspection_required = grn_data.inspection_required
    if grn_data.notes is not None:
        grn.notes = grn_data.notes

    db.commit()
    db.refresh(grn)

    return grn_to_response(grn)


@router.post("/{grn_id}/post", response_model=dict)
async def post_goods_receipt(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Post a Goods Receipt Note.
    This will:
    1. Update PO line received quantities
    2. Update inventory stock levels
    3. Create item ledger entries
    4. Create accounting journal entry
    5. Update PO status
    """
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.po_line),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.lines),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book)
    ).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status not in ['draft', 'pending_inspection']:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot post GRN with status '{grn.status}'"
        )

    # If inspection required, check all lines are inspected
    if grn.inspection_required:
        uninspected = [l for l in grn.lines if l.inspection_status == 'pending']
        if uninspected:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot post: {len(uninspected)} lines pending inspection"
            )

    # STRICT VALIDATION: Block posting if any line has no item_id
    # This ensures 100% inventory tracking - no silent failures
    lines_without_item = []
    for line in grn.lines:
        if not line.item_id:
            # Try to auto-resolve one more time from item_code
            if line.item_code:
                item = db.query(ItemMaster).filter(
                    ItemMaster.company_id == current_user.company_id,
                    func.upper(ItemMaster.item_number) == line.item_code.upper().strip()
                ).first()
                if item:
                    line.item_id = item.id
                    logger.info(f"Auto-linked GRN line {line.id} to ItemMaster {item.id} during post validation")
                    continue
            # Could not resolve - add to error list
            lines_without_item.append({
                "line_id": line.id,
                "item_code": line.item_code,
                "description": line.item_description
            })

    if lines_without_item:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Cannot post GRN - some lines are not linked to Item Master",
                "unlinked_lines": lines_without_item,
                "action": "Please link these items to Item Master records before posting"
            }
        )

    try:
        po = grn.purchase_order
        po_lines_map = {line.id: line for line in po.lines}

        # Process each GRN line
        for grn_line in grn.lines:
            po_line = po_lines_map.get(grn_line.po_line_id)
            if not po_line:
                continue

            # Use accepted quantity if inspected, otherwise received quantity
            qty_to_receive = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)

            if qty_to_receive > 0:
                # Update PO line
                update_po_line_receiving(db, po_line, qty_to_receive)

                # Update inventory
                update_inventory(db, grn_line, current_user.company_id, current_user.id)

        # Update PO status
        update_po_status(db, po)

        # Create journal entry
        try:
            journal_service = JournalPostingService(db, current_user.company_id, current_user.id)
            journal_entry = journal_service.post_goods_receipt(grn)
            if journal_entry:
                grn.journal_entry_id = journal_entry.id
                logger.info(f"Created journal entry {journal_entry.entry_number} for GRN {grn.grn_number}")
        except Exception as e:
            logger.warning(f"Failed to create journal entry for GRN {grn.grn_number}: {e}")
            # Continue without journal entry

        # Update GRN status
        grn.status = 'accepted'
        grn.posted_by = current_user.id
        grn.posted_at = datetime.utcnow()

        db.commit()
        db.refresh(grn)

        return {
            "message": "Goods Receipt posted successfully",
            "grn_number": grn.grn_number,
            "status": grn.status,
            "journal_entry_id": grn.journal_entry_id
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error posting GRN {grn_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error posting GRN: {str(e)}")


@router.post("/{grn_id}/inspect", response_model=dict)
async def inspect_goods_receipt(
    grn_id: int,
    inspection: GRNInspectionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Record inspection results for a Goods Receipt.
    Set accepted and rejected quantities for each line.
    """
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines)
    ).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status not in ['draft', 'pending_inspection']:
        raise HTTPException(
            status_code=400,
            detail="GRN must be in draft or pending_inspection status for inspection"
        )

    if not grn.inspection_required:
        raise HTTPException(
            status_code=400,
            detail="This GRN does not require inspection"
        )

    # Map line IDs to lines
    lines_map = {line.id: line for line in grn.lines}

    all_passed = True
    any_rejected = False

    for result in inspection.line_results:
        line = lines_map.get(result.line_id)
        if not line:
            raise HTTPException(status_code=400, detail=f"Line {result.line_id} not found in this GRN")

        # Validate quantities
        total_inspected = result.quantity_accepted + result.quantity_rejected
        if total_inspected > float(line.quantity_received):
            raise HTTPException(
                status_code=400,
                detail=f"Inspected quantity ({total_inspected}) exceeds received quantity ({line.quantity_received})"
            )

        line.quantity_accepted = result.quantity_accepted
        line.quantity_rejected = result.quantity_rejected
        line.rejection_reason = result.rejection_reason
        line.inspection_notes = result.inspection_notes

        if result.quantity_rejected > 0:
            line.inspection_status = 'failed' if result.quantity_accepted == 0 else 'partial'
            any_rejected = True
            if result.quantity_accepted == 0:
                all_passed = False
        else:
            line.inspection_status = 'passed'

        # Check for variance
        if result.quantity_rejected > 0:
            line.has_variance = True
            line.variance_type = 'rejected'
            line.variance_notes = result.rejection_reason

    # Update GRN inspection status
    grn.inspected_by = current_user.id
    grn.inspected_at = datetime.utcnow()
    grn.inspection_notes = inspection.inspection_notes

    if all_passed:
        grn.inspection_status = 'passed'
    elif any_rejected and all_passed:
        grn.inspection_status = 'partial'
    else:
        grn.inspection_status = 'failed' if not any(l.quantity_accepted > 0 for l in grn.lines) else 'partial'

    grn.status = 'pending_inspection'  # Ready for posting

    db.commit()

    return {
        "message": "Inspection recorded successfully",
        "grn_number": grn.grn_number,
        "inspection_status": grn.inspection_status
    }


@router.delete("/{grn_id}")
async def delete_goods_receipt(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a Goods Receipt Note (only draft status)"""
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status != 'draft':
        raise HTTPException(
            status_code=400,
            detail="Can only delete GRN in draft status"
        )

    db.delete(grn)
    db.commit()

    return {"message": "Goods Receipt deleted successfully"}


@router.post("/{grn_id}/reverse", response_model=dict)
async def reverse_goods_receipt(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reverse a posted Goods Receipt Note.
    This will:
    1. Reverse inventory stock levels (decrease stock)
    2. Create reversal item ledger entries
    3. Decrease PO line received quantities
    4. Update PO status
    5. Delete the journal entry if exists
    6. Set GRN status to 'cancelled'
    """
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.po_line),
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.item),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.lines),
        joinedload(GoodsReceipt.journal_entry)
    ).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status != 'accepted':
        raise HTTPException(
            status_code=400,
            detail=f"Can only reverse posted GRNs. Current status: {grn.status}"
        )

    # =========================================================================
    # STOCK VALIDATION - Check if sufficient stock exists before reversal
    # =========================================================================
    insufficient_stock_items = []
    for grn_line in grn.lines:
        if not grn_line.item_id:
            continue

        warehouse_id = grn_line.warehouse_id or grn.warehouse_id
        if not warehouse_id:
            continue

        qty_to_reverse = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)
        if qty_to_reverse <= 0:
            continue

        # Get current stock level
        item_stock = db.query(ItemStock).filter(
            ItemStock.item_id == grn_line.item_id,
            ItemStock.warehouse_id == warehouse_id
        ).first()

        current_qty = float(item_stock.quantity_on_hand or 0) if item_stock else 0

        if current_qty < qty_to_reverse:
            item = grn_line.item
            item_desc = item.description if item else f"Item #{grn_line.item_id}"
            item_number = item.item_number if item else "N/A"
            insufficient_stock_items.append({
                "item_number": item_number,
                "description": item_desc,
                "qty_to_reverse": qty_to_reverse,
                "current_stock": current_qty,
                "shortage": qty_to_reverse - current_qty
            })

    if insufficient_stock_items:
        # Build detailed error message
        error_details = []
        for item in insufficient_stock_items:
            error_details.append(
                f"• {item['item_number']} ({item['description']}): "
                f"Need {item['qty_to_reverse']}, only {item['current_stock']} in stock "
                f"(short by {item['shortage']})"
            )
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reverse GRN - insufficient stock for the following items:\n" + "\n".join(error_details)
        )

    try:
        po = grn.purchase_order
        po_lines_map = {line.id: line for line in po.lines}

        # Process each GRN line - reverse inventory and PO receiving
        for grn_line in grn.lines:
            po_line = po_lines_map.get(grn_line.po_line_id)

            # Get quantity that was received
            qty_to_reverse = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)

            if qty_to_reverse > 0:
                # Reverse PO line received quantity
                if po_line:
                    reverse_po_line_receiving(db, po_line, qty_to_reverse)

                # Reverse inventory
                reverse_inventory(db, grn_line, current_user.company_id, current_user.id)

        # Update PO status
        update_po_status(db, po)

        # Create reversal journal entry if original exists
        if grn.journal_entry_id:
            from app.models import JournalEntry, JournalEntryLine
            from datetime import date

            # Get the original journal entry
            original_je = db.query(JournalEntry).filter(
                JournalEntry.id == grn.journal_entry_id
            ).first()

            if original_je:
                # Generate reversal entry number
                today = date.today()
                year = today.year

                # Get next sequence number for this year
                last_entry = db.query(JournalEntry).filter(
                    JournalEntry.company_id == current_user.company_id,
                    JournalEntry.entry_number.like(f'JE-{year}-%')
                ).order_by(JournalEntry.entry_number.desc()).first()

                if last_entry:
                    try:
                        last_seq = int(last_entry.entry_number.split('-')[-1])
                        next_seq = last_seq + 1
                    except ValueError:
                        next_seq = 1
                else:
                    next_seq = 1

                reversal_entry_number = f"JE-{year}-{next_seq:06d}"

                # Create reversal journal entry
                reversal_je = JournalEntry(
                    company_id=current_user.company_id,
                    entry_number=reversal_entry_number,
                    entry_date=today,
                    description=f"Reversal of {original_je.entry_number} - GRN {grn.grn_number} reversed",
                    reference=f"REV-{original_je.entry_number}",
                    source_type="grn_reversal",
                    source_id=grn.id,
                    source_number=grn.grn_number,
                    status="posted",
                    is_auto_generated=True,
                    total_debit=original_je.total_credit,  # Swap debit/credit
                    total_credit=original_je.total_debit,
                    created_by=current_user.id
                )
                db.add(reversal_je)
                db.flush()  # Get the ID

                # Get original lines and create reversed lines
                original_lines = db.query(JournalEntryLine).filter(
                    JournalEntryLine.journal_entry_id == original_je.id
                ).all()

                for orig_line in original_lines:
                    # Swap debits and credits for reversal
                    reversal_line = JournalEntryLine(
                        journal_entry_id=reversal_je.id,
                        account_id=orig_line.account_id,
                        debit=orig_line.credit,  # Swap
                        credit=orig_line.debit,  # Swap
                        description=f"Reversal: {orig_line.description or ''}",
                        business_unit_id=orig_line.business_unit_id,
                        site_id=orig_line.site_id,
                        contract_id=orig_line.contract_id,
                        work_order_id=orig_line.work_order_id,
                        address_book_id=orig_line.address_book_id
                    )
                    db.add(reversal_line)

                # Mark original entry as reversed
                original_je.status = "reversed"

                # Link the reversal entry to the GRN (optional - for audit)
                grn.reversal_journal_entry_id = reversal_je.id

                logger.info(f"Created reversal journal entry {reversal_entry_number} for GRN {grn.grn_number}")

        # Update GRN status to cancelled
        grn.status = 'cancelled'

        db.commit()
        db.refresh(grn)

        logger.info(f"GRN {grn.grn_number} reversed by user {current_user.id}")

        return {
            "message": "Goods Receipt reversed successfully",
            "grn_number": grn.grn_number,
            "status": grn.status
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error reversing GRN {grn_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reversing GRN: {str(e)}")


def reverse_po_line_receiving(db: Session, po_line: PurchaseOrderLine, quantity: float):
    """Reverse PO line cumulative received quantity and status"""
    current_received = float(po_line.quantity_received or 0)
    new_received = max(0, current_received - quantity)
    po_line.quantity_received = new_received

    ordered = float(po_line.quantity_ordered or 0)
    if new_received >= ordered:
        po_line.receive_status = 'received'
    elif new_received > 0:
        po_line.receive_status = 'partial'
    else:
        po_line.receive_status = 'pending'


def reverse_inventory(db: Session, grn_line: GoodsReceiptLine, company_id: int, user_id: int):
    """
    Reverse inventory stock and create reversal ledger entry.

    This function:
    1. Validates sufficient stock exists
    2. Decreases stock quantity in ItemStock
    3. Creates a reversal entry in ItemLedger (negative quantity)

    Raises:
        ValueError: If insufficient stock to reverse
    """
    if not grn_line.item_id:
        logger.warning(f"GRN line {grn_line.id} has no item_id - skipping inventory reversal. "
                      f"Item code: {grn_line.item_code}, Description: {grn_line.item_description}")
        return None

    warehouse_id = grn_line.warehouse_id or grn_line.goods_receipt.warehouse_id
    if not warehouse_id:
        logger.warning(f"GRN line {grn_line.id} has no warehouse_id - skipping inventory reversal")
        return None

    # Get ItemStock for this warehouse
    item_stock = db.query(ItemStock).filter(
        ItemStock.item_id == grn_line.item_id,
        ItemStock.warehouse_id == warehouse_id
    ).first()

    if not item_stock:
        logger.warning(f"GRN line {grn_line.id} has no ItemStock record for warehouse {warehouse_id} - skipping inventory reversal")
        return None

    # Get quantity to reverse
    quantity = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)
    current_qty = float(item_stock.quantity_on_hand or 0)

    # CRITICAL: Validate sufficient stock before reversing
    if current_qty < quantity:
        item = grn_line.item
        item_desc = item.description if item else f"Item #{grn_line.item_id}"
        raise ValueError(
            f"Insufficient stock for {item_desc}: "
            f"Need {quantity} to reverse, only {current_qty} available"
        )

    # Decrease stock quantities (validated above, so this is safe)
    item_stock.quantity_on_hand = Decimal(str(current_qty)) - Decimal(str(quantity))
    item_stock.updated_at = datetime.utcnow()

    # Generate transaction number for reversal
    today = datetime.now().strftime("%Y%m%d")
    tx_prefix = f"GRN-REV-{today}-"
    last_tx = db.query(ItemLedger).filter(
        ItemLedger.company_id == company_id,
        ItemLedger.transaction_number.like(f"{tx_prefix}%")
    ).order_by(ItemLedger.id.desc()).first()

    if last_tx:
        try:
            last_num = int(last_tx.transaction_number.split("-")[-1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1

    tx_number = f"{tx_prefix}{next_num:05d}"

    grn = grn_line.goods_receipt

    # Get effective costs
    effective_unit_cost = get_effective_unit_cost(grn_line)
    effective_total_cost = get_effective_total_cost(grn_line)

    # Calculate balance after reversal (current stock minus reversed quantity)
    new_balance = Decimal(str(current_qty)) - Decimal(str(quantity))

    # Create reversal ItemLedger entry (negative quantity)
    ledger_entry = ItemLedger(
        company_id=company_id,
        item_id=grn_line.item_id,
        transaction_type="GRN_REVERSAL",
        transaction_number=tx_number,
        transaction_date=datetime.now().date(),
        quantity=-Decimal(str(quantity)),  # Negative for reversal
        unit=grn_line.unit,
        unit_cost=effective_unit_cost,
        total_cost=-Decimal(str(float(effective_total_cost))),  # Negative for reversal
        from_warehouse_id=warehouse_id,
        balance_after=new_balance,  # Track running balance
        notes=f"Reversal of GRN {grn.grn_number}",
        created_by=user_id
    )
    db.add(ledger_entry)
    db.flush()

    return ledger_entry


# =============================================================================
# PO RECEIVING STATUS ENDPOINTS
# =============================================================================

@router.get("/po/{po_id}/receiving-status", response_model=dict)
async def get_po_receiving_status(
    po_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed receiving status for a Purchase Order.
    Shows ordered, received, and pending quantities per line.
    """
    po = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.item),
        joinedload(PurchaseOrder.goods_receipts).joinedload(GoodsReceipt.lines)
    ).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    total_ordered = 0
    total_received = 0
    lines_status = []

    for line in po.lines:
        ordered = float(line.quantity_ordered or 0)
        received = float(line.quantity_received or 0)
        pending = ordered - received

        total_ordered += ordered
        total_received += received

        lines_status.append({
            "line_id": line.id,
            "item_id": line.item_id,
            "item_code": line.item.item_number if line.item else line.item_number,
            "item_number": line.item_number,
            "description": line.description,
            "quantity_ordered": ordered,
            "quantity_received": received,
            "quantity_pending": pending,
            "receive_status": line.receive_status,
            "unit": line.unit
        })

    total_pending = total_ordered - total_received
    percent_received = (total_received / total_ordered * 100) if total_ordered > 0 else 0

    return {
        "po_id": po.id,
        "po_number": po.po_number,
        "total_ordered": total_ordered,
        "total_received": total_received,
        "total_pending": total_pending,
        "percent_received": round(percent_received, 2),
        "status": po.status,
        "lines": lines_status,
        "grn_count": len(po.goods_receipts)
    }


# =============================================================================
# THREE-WAY MATCHING
# =============================================================================

@router.get("/po/{po_id}/three-way-match", response_model=dict)
async def three_way_match(
    po_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform three-way matching for a Purchase Order.
    Compares PO net amounts vs GRN received amounts vs Invoice net amounts.
    VAT/Tax is shown separately and not included in the matching comparison.

    Best practice: Match net amounts (excluding VAT) since:
    - PO and GRN are typically net amounts
    - Invoice includes VAT which is recoverable input tax
    - The variance should only flag actual price/quantity discrepancies
    """
    po = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.lines),
        joinedload(PurchaseOrder.goods_receipts).joinedload(GoodsReceipt.lines),
        joinedload(PurchaseOrder.linked_invoices).joinedload(PurchaseOrderInvoice.invoice)
    ).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    # Calculate PO totals (net and tax)
    po_subtotal = float(po.subtotal or 0)  # Net amount
    po_tax = float(po.tax_amount or 0)
    po_total = float(po.total_amount or 0)

    # Calculate GRN totals (net and tax)
    grn_subtotal = sum(
        float(grn.subtotal or 0)
        for grn in po.goods_receipts
        if grn.status == 'accepted'
    )
    grn_tax = sum(
        float(grn.tax_amount or 0)
        for grn in po.goods_receipts
        if grn.status == 'accepted'
    )
    grn_total = grn_subtotal + grn_tax

    # Calculate Invoice totals (net and tax from structured_data JSON)
    invoice_subtotal = 0.0
    invoice_tax = 0.0
    invoice_total = 0.0
    for link in po.linked_invoices:
        if link.invoice and link.invoice.structured_data:
            try:
                data = json.loads(link.invoice.structured_data)
                financial = data.get('financial_details', {})

                # Get subtotal (net amount before tax)
                subtotal = financial.get('subtotal') or financial.get('total_before_tax')
                if subtotal:
                    invoice_subtotal += float(subtotal)

                # Get tax amount
                tax = financial.get('tax_amount') or financial.get('vat_amount') or financial.get('total_tax')
                if tax:
                    invoice_tax += float(tax)

                # Get total (with tax)
                total = financial.get('total_after_tax') or financial.get('total_amount')
                if total:
                    invoice_total += float(total)
                elif subtotal:
                    # If no total, calculate from subtotal + tax
                    invoice_total += float(subtotal) + float(tax or 0)

            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    # If we couldn't extract subtotal from invoice, estimate it from total - tax
    if invoice_total > 0 and invoice_subtotal == 0:
        invoice_subtotal = invoice_total - invoice_tax

    # Determine match status based on NET amounts (excluding VAT)
    # This is the proper three-way match: PO net ≈ GRN net ≈ Invoice net
    net_variance_po_grn = abs(po_subtotal - grn_subtotal)
    net_variance_grn_inv = abs(grn_subtotal - invoice_subtotal)
    net_variance = net_variance_po_grn + net_variance_grn_inv

    # Calculate variance percentage based on PO subtotal
    variance_percent = (net_variance / po_subtotal * 100) if po_subtotal > 0 else 0

    # Match is OK if net amounts are within tolerance (allow for small rounding)
    tolerance = 0.01  # $0.01 tolerance
    is_matched = net_variance < tolerance

    # Build detailed comparison for each line
    details = []
    for line in po.lines:
        ordered = float(line.quantity_ordered or 0)
        received = float(line.quantity_received or 0)
        line_po_amount = float(line.total_price or 0)
        line_grn_amount = sum(
            float(grn_line.total_price or 0)
            for grn in po.goods_receipts
            for grn_line in grn.lines
            if grn_line.po_line_id == line.id and grn.status == 'accepted'
        )

        line_variance = abs(line_po_amount - line_grn_amount)

        details.append({
            "line_id": line.id,
            "description": line.description,
            "quantity_ordered": ordered,
            "quantity_received": received,
            "po_amount": line_po_amount,
            "grn_amount": line_grn_amount,
            "invoice_amount": None,  # Line-level invoice matching not available
            "variance": line_variance,
            "is_matched": line_variance < tolerance
        })

    return {
        "po_id": po.id,
        "po_number": po.po_number,
        # Net amounts (for matching)
        "po_subtotal": po_subtotal,
        "grn_subtotal": grn_subtotal,
        "invoice_subtotal": invoice_subtotal,
        # Tax amounts (shown separately)
        "po_tax": po_tax,
        "grn_tax": grn_tax,
        "invoice_tax": invoice_tax,
        # Gross totals (for reference)
        "po_total": po_total,
        "grn_total": grn_total,
        "invoice_total": invoice_total,
        # Match status (based on NET amounts)
        "is_matched": is_matched,
        "net_variance": round(net_variance, 2),
        "variance_percent": round(variance_percent, 2),
        # Counts
        "grn_count": len([g for g in po.goods_receipts if g.status == 'accepted']),
        "invoice_count": len(po.linked_invoices),
        "details": details
    }


# =============================================================================
# EXTRA COSTS / LANDED COST ENDPOINTS
# =============================================================================

@router.get("/{grn_id}/extra-costs", response_model=List[dict])
async def list_extra_costs(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all extra costs for a Goods Receipt"""
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    costs = db.query(GoodsReceiptExtraCost).filter(
        GoodsReceiptExtraCost.goods_receipt_id == grn_id
    ).all()

    return [
        {
            "id": cost.id,
            "goods_receipt_id": cost.goods_receipt_id,
            "cost_type": cost.cost_type,
            "cost_description": cost.cost_description,
            "amount": float(cost.amount or 0),
            "currency": cost.currency,
            "vendor_id": cost.address_book_id,
            "vendor_name": cost.address_book.alpha_name if cost.address_book else None,
            "reference_number": cost.reference_number,
            "notes": cost.notes,
            "created_by": cost.created_by,
            "created_by_name": cost.creator.name if cost.creator else None,
            "created_at": cost.created_at
        }
        for cost in costs
    ]


@router.post("/{grn_id}/extra-costs", response_model=dict)
async def add_extra_cost(
    grn_id: int,
    cost_data: GoodsReceiptExtraCostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Add an extra cost to a Goods Receipt (freight, duty, port handling, etc.).
    This will automatically recalculate landed costs for all lines.
    """
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status == 'accepted':
        raise HTTPException(
            status_code=400,
            detail="Cannot add extra costs to a posted GRN. Please reverse the posting first."
        )

    # Validate cost type
    valid_types = [t[0] for t in EXTRA_COST_TYPES]
    if cost_data.cost_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cost type. Valid types: {', '.join(valid_types)}"
        )

    # Validate vendor if provided (from Address Book)
    if cost_data.vendor_id:
        vendor = db.query(AddressBook).filter(
            AddressBook.id == cost_data.vendor_id,
            AddressBook.company_id == current_user.company_id,
            AddressBook.search_type == 'V'
        ).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found in Address Book")

    # Create extra cost
    extra_cost = GoodsReceiptExtraCost(
        goods_receipt_id=grn_id,
        cost_type=cost_data.cost_type,
        cost_description=cost_data.cost_description,
        amount=cost_data.amount,
        currency=cost_data.currency,
        address_book_id=cost_data.vendor_id,
        reference_number=cost_data.reference_number,
        notes=cost_data.notes,
        created_by=current_user.id
    )
    db.add(extra_cost)
    db.flush()

    # Recalculate landed costs
    landed_cost_service = LandedCostService(db, current_user.company_id, current_user.id)
    grn = landed_cost_service.allocate_extra_costs(grn_id)

    db.commit()

    # Reload GRN with all relationships
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.warehouse),
        joinedload(GoodsReceipt.extra_costs).joinedload(GoodsReceiptExtraCost.address_book),
        joinedload(GoodsReceipt.extra_costs).joinedload(GoodsReceiptExtraCost.creator),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.id == grn_id).first()

    return grn_to_response(grn)


@router.put("/{grn_id}/extra-costs/{cost_id}", response_model=dict)
async def update_extra_cost(
    grn_id: int,
    cost_id: int,
    cost_data: GoodsReceiptExtraCostUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update an extra cost on a Goods Receipt.
    This will automatically recalculate landed costs for all lines.
    """
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status == 'accepted':
        raise HTTPException(
            status_code=400,
            detail="Cannot modify extra costs on a posted GRN"
        )

    extra_cost = db.query(GoodsReceiptExtraCost).filter(
        GoodsReceiptExtraCost.id == cost_id,
        GoodsReceiptExtraCost.goods_receipt_id == grn_id
    ).first()

    if not extra_cost:
        raise HTTPException(status_code=404, detail="Extra cost not found")

    # Update fields
    if cost_data.cost_type is not None:
        valid_types = [t[0] for t in EXTRA_COST_TYPES]
        if cost_data.cost_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid cost type. Valid types: {', '.join(valid_types)}"
            )
        extra_cost.cost_type = cost_data.cost_type

    if cost_data.cost_description is not None:
        extra_cost.cost_description = cost_data.cost_description
    if cost_data.amount is not None:
        extra_cost.amount = cost_data.amount
    if cost_data.currency is not None:
        extra_cost.currency = cost_data.currency
    if cost_data.vendor_id is not None:
        if cost_data.vendor_id:
            vendor = db.query(AddressBook).filter(
                AddressBook.id == cost_data.vendor_id,
                AddressBook.company_id == current_user.company_id,
                AddressBook.search_type == 'V'
            ).first()
            if not vendor:
                raise HTTPException(status_code=404, detail="Vendor not found in Address Book")
        extra_cost.address_book_id = cost_data.vendor_id
    if cost_data.reference_number is not None:
        extra_cost.reference_number = cost_data.reference_number
    if cost_data.notes is not None:
        extra_cost.notes = cost_data.notes

    db.flush()

    # Recalculate landed costs
    landed_cost_service = LandedCostService(db, current_user.company_id, current_user.id)
    grn = landed_cost_service.allocate_extra_costs(grn_id)

    db.commit()

    # Reload GRN with all relationships
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.warehouse),
        joinedload(GoodsReceipt.extra_costs).joinedload(GoodsReceiptExtraCost.address_book),
        joinedload(GoodsReceipt.extra_costs).joinedload(GoodsReceiptExtraCost.creator),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.id == grn_id).first()

    return grn_to_response(grn)


@router.delete("/{grn_id}/extra-costs/{cost_id}", response_model=dict)
async def delete_extra_cost(
    grn_id: int,
    cost_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete an extra cost from a Goods Receipt.
    This will automatically recalculate landed costs for all lines.
    """
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status == 'accepted':
        raise HTTPException(
            status_code=400,
            detail="Cannot delete extra costs from a posted GRN"
        )

    extra_cost = db.query(GoodsReceiptExtraCost).filter(
        GoodsReceiptExtraCost.id == cost_id,
        GoodsReceiptExtraCost.goods_receipt_id == grn_id
    ).first()

    if not extra_cost:
        raise HTTPException(status_code=404, detail="Extra cost not found")

    db.delete(extra_cost)
    db.flush()

    # Recalculate landed costs
    landed_cost_service = LandedCostService(db, current_user.company_id, current_user.id)
    grn = landed_cost_service.allocate_extra_costs(grn_id)

    db.commit()

    return {"message": "Extra cost deleted successfully", "grn_id": grn_id}


@router.post("/{grn_id}/recalculate-landed-costs", response_model=dict)
async def recalculate_landed_costs(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually recalculate landed costs for a Goods Receipt.
    Use this if allocations seem incorrect or after bulk updates.
    """
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status == 'accepted':
        raise HTTPException(
            status_code=400,
            detail="Cannot recalculate costs on a posted GRN"
        )

    landed_cost_service = LandedCostService(db, current_user.company_id, current_user.id)
    grn = landed_cost_service.allocate_extra_costs(grn_id)

    db.commit()

    # Reload with relationships
    grn = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.lines).joinedload(GoodsReceiptLine.warehouse),
        joinedload(GoodsReceipt.extra_costs).joinedload(GoodsReceiptExtraCost.address_book),
        joinedload(GoodsReceipt.extra_costs).joinedload(GoodsReceiptExtraCost.creator),
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.address_book),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.id == grn_id).first()

    return grn_to_response(grn)


@router.get("/{grn_id}/landed-cost-summary", response_model=dict)
async def get_landed_cost_summary(
    grn_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a detailed breakdown of landed costs for a Goods Receipt.
    Shows costs by type and allocation per line.
    """
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    landed_cost_service = LandedCostService(db, current_user.company_id, current_user.id)
    return landed_cost_service.get_landed_cost_summary(grn_id)


@router.put("/{grn_id}/mark-as-import", response_model=dict)
async def mark_as_import(
    grn_id: int,
    is_import: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark or unmark a Goods Receipt as an import.
    Import GRNs can have extra costs added.
    """
    grn = db.query(GoodsReceipt).filter(
        GoodsReceipt.id == grn_id,
        GoodsReceipt.company_id == current_user.company_id
    ).first()

    if not grn:
        raise HTTPException(status_code=404, detail="Goods Receipt not found")

    if grn.status == 'accepted':
        raise HTTPException(
            status_code=400,
            detail="Cannot modify a posted GRN"
        )

    grn.is_import = is_import
    db.commit()

    return {
        "message": f"GRN marked as {'import' if is_import else 'non-import'}",
        "grn_id": grn_id,
        "is_import": is_import
    }


@router.get("/extra-cost-types", response_model=List[dict])
async def get_extra_cost_types(
    current_user: User = Depends(get_current_user)
):
    """Get list of available extra cost types"""
    return [
        {"code": code, "label": label}
        for code, label in EXTRA_COST_TYPES
    ]
