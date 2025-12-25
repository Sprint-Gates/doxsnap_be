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

from app.database import get_db
from app.models import (
    User, PurchaseOrder, PurchaseOrderLine, GoodsReceipt, GoodsReceiptLine,
    ItemMaster, ItemStock, ItemLedger, Warehouse, Account, PurchaseOrderInvoice
)
from app.api.auth import get_current_user
from app.services.journal_posting import JournalPostingService

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
    inspection_status: str
    rejection_reason: Optional[str]
    has_variance: bool
    variance_type: Optional[str]
    notes: Optional[str]

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
    journal_entry_id: Optional[int]
    notes: Optional[str]
    created_by_name: Optional[str] = None
    created_at: datetime
    lines: List[GoodsReceiptLineResponse] = []

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


def grn_to_response(grn: GoodsReceipt, include_lines: bool = True) -> dict:
    """Convert GoodsReceipt to response dict"""
    response = {
        "id": grn.id,
        "grn_number": grn.grn_number,
        "purchase_order_id": grn.purchase_order_id,
        "po_number": grn.purchase_order.po_number if grn.purchase_order else None,
        "vendor_name": grn.purchase_order.vendor.name if grn.purchase_order and grn.purchase_order.vendor else None,
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
        "journal_entry_id": grn.journal_entry_id,
        "notes": grn.notes,
        "created_by_name": grn.creator.name if grn.creator else None,
        "created_at": grn.created_at,
        "lines": []
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
                "inspection_status": line.inspection_status,
                "rejection_reason": line.rejection_reason,
                "has_variance": line.has_variance,
                "variance_type": line.variance_type,
                "notes": line.notes
            }
            response["lines"].append(line_data)

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

    if all_received:
        po.status = 'received'
    elif any_received:
        po.status = 'partial'


def update_inventory(db: Session, grn_line: GoodsReceiptLine, company_id: int, user_id: int):
    """Update inventory stock and create ledger entry"""
    if not grn_line.item_id:
        return None

    warehouse_id = grn_line.warehouse_id or grn_line.goods_receipt.warehouse_id
    if not warehouse_id:
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

    # Update stock quantities
    quantity = float(grn_line.quantity_accepted or grn_line.quantity_received or 0)
    item_stock.quantity_on_hand = (item_stock.quantity_on_hand or 0) + Decimal(str(quantity))
    item_stock.quantity_on_order = max(0, (item_stock.quantity_on_order or 0) - Decimal(str(quantity)))
    item_stock.last_cost = grn_line.unit_price
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

    # Create ItemLedger entry
    grn = grn_line.goods_receipt
    ledger_entry = ItemLedger(
        company_id=company_id,
        item_id=grn_line.item_id,
        transaction_type="RECEIVE_GRN",
        transaction_number=tx_number,
        transaction_date=grn.receipt_date,
        quantity=Decimal(str(quantity)),
        unit=grn_line.unit,
        unit_cost=grn_line.unit_price,
        total_cost=grn_line.total_price,
        to_warehouse_id=warehouse_id,
        notes=f"Received via GRN {grn.grn_number} from PO {grn.purchase_order.po_number}",
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
        joinedload(PurchaseOrder.vendor)
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

    # Validate warehouse if provided
    if grn_data.warehouse_id:
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

        grn_line = GoodsReceiptLine(
            goods_receipt_id=grn.id,
            po_line_id=line_data.po_line_id,
            item_id=po_line.item_id,
            item_code=po_line.item.item_number if po_line.item else None,
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
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.vendor),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.id == grn.id).first()

    return grn_to_response(grn)


@router.get("/", response_model=List[dict])
async def list_goods_receipts(
    purchase_order_id: Optional[int] = None,
    status: Optional[str] = None,
    warehouse_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List Goods Receipt Notes with optional filters"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    query = db.query(GoodsReceipt).options(
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.vendor),
        joinedload(GoodsReceipt.warehouse),
        joinedload(GoodsReceipt.creator)
    ).filter(GoodsReceipt.company_id == current_user.company_id)

    if purchase_order_id:
        query = query.filter(GoodsReceipt.purchase_order_id == purchase_order_id)
    if status:
        query = query.filter(GoodsReceipt.status == status)
    if warehouse_id:
        query = query.filter(GoodsReceipt.warehouse_id == warehouse_id)
    if start_date:
        query = query.filter(GoodsReceipt.receipt_date >= start_date)
    if end_date:
        query = query.filter(GoodsReceipt.receipt_date <= end_date)

    grns = query.order_by(GoodsReceipt.created_at.desc()).offset(offset).limit(limit).all()

    return [grn_to_response(grn, include_lines=False) for grn in grns]


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
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.vendor),
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
        joinedload(GoodsReceipt.purchase_order).joinedload(PurchaseOrder.vendor)
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
            "item_code": line.item.item_number if line.item else None,
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
    Compares PO amounts vs GRN received amounts vs Invoice amounts.
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

    # Calculate PO total
    po_total = float(po.total_amount or 0)

    # Calculate GRN total (sum of all posted GRNs)
    grn_total = sum(
        float(grn.total_amount or 0)
        for grn in po.goods_receipts
        if grn.status == 'accepted'
    )

    # Calculate Invoice total
    invoice_total = sum(
        float(link.invoice.total_amount or 0)
        for link in po.linked_invoices
        if link.invoice
    )

    # Determine match status
    variance = abs(po_total - grn_total) + abs(grn_total - invoice_total)
    variance_percent = (variance / po_total * 100) if po_total > 0 else 0
    is_matched = variance < 0.01  # Allow for rounding

    # Build detailed comparison
    details = []

    for line in po.lines:
        ordered = float(line.quantity_ordered or 0)
        received = float(line.quantity_received or 0)
        line_po_total = float(line.total_price or 0)
        line_grn_total = sum(
            float(grn_line.total_price or 0)
            for grn in po.goods_receipts
            for grn_line in grn.lines
            if grn_line.po_line_id == line.id and grn.status == 'accepted'
        )

        details.append({
            "line_id": line.id,
            "description": line.description,
            "quantity_ordered": ordered,
            "quantity_received": received,
            "po_amount": line_po_total,
            "grn_amount": line_grn_total,
            "variance": abs(line_po_total - line_grn_total),
            "is_matched": abs(line_po_total - line_grn_total) < 0.01
        })

    return {
        "po_id": po.id,
        "po_number": po.po_number,
        "po_total": po_total,
        "grn_total": grn_total,
        "invoice_total": invoice_total,
        "is_matched": is_matched,
        "variance": variance,
        "variance_percent": round(variance_percent, 2),
        "grn_count": len([g for g in po.goods_receipts if g.status == 'accepted']),
        "invoice_count": len(po.linked_invoices),
        "details": details
    }
