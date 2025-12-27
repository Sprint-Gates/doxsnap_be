from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import and_, func
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from app.database import get_db
from app.models import (
    PurchaseOrder, PurchaseOrderLine, PurchaseOrderInvoice, PurchaseRequest,
    User, AddressBook, WorkOrder, Contract, ItemMaster, ProcessedImage,
    ItemStock, ItemLedger, GoodsReceipt
)
from app.utils.security import verify_token
from app.services.journal_posting import JournalPostingService
from app.schemas import (
    PurchaseOrderCreate, PurchaseOrderUpdate, PurchaseOrder as POSchema,
    PurchaseOrderList, PurchaseOrderLineCreate, PurchaseOrderLineUpdate,
    PurchaseOrderLine as POLineSchema, PurchaseOrderLineReceive,
    POInvoiceLink, PurchaseOrderInvoice as POInvoiceSchema
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def resolve_item_id(db: Session, company_id: int, item_id: Optional[int], item_number: Optional[str]) -> Optional[int]:
    """
    Resolve item_id from item_number if not provided.
    This ensures inventory tracking works even when users enter item_number manually.
    """
    if item_id:
        return item_id

    if not item_number:
        return None

    # Try to find ItemMaster by item_number (case-insensitive)
    item = db.query(ItemMaster).filter(
        ItemMaster.company_id == company_id,
        func.upper(ItemMaster.item_number) == item_number.upper().strip()
    ).first()

    if item:
        logger.info(f"Auto-linked item_number '{item_number}' to ItemMaster ID {item.id}")
        return item.id

    return None


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


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def generate_po_number(db: Session, company_id: int) -> str:
    """Generate next PO number: PO-YYYY-NNNNN (globally unique)"""
    year = datetime.now().year
    prefix = f"PO-{year}-"

    # Find the highest PO number globally (unique constraint is global)
    last_po = db.query(PurchaseOrder).filter(
        PurchaseOrder.po_number.like(f"{prefix}%")
    ).order_by(PurchaseOrder.po_number.desc()).first()

    if last_po:
        try:
            last_num = int(last_po.po_number.replace(prefix, ""))
            next_num = last_num + 1
        except ValueError:
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def calculate_po_totals(lines: list) -> tuple:
    """Calculate subtotal and total from PO lines"""
    subtotal = Decimal(0)
    for line in lines:
        if hasattr(line, 'total_price') and line.total_price:
            subtotal += Decimal(str(line.total_price))
    return subtotal, subtotal  # Tax can be added later


def update_po_line_receive_status(line: PurchaseOrderLine):
    """Update receive status based on quantities"""
    if line.quantity_received == 0:
        line.receive_status = 'pending'
    elif line.quantity_received < line.quantity_ordered:
        line.receive_status = 'partial'
    else:
        line.receive_status = 'received'


def update_po_status(po: PurchaseOrder):
    """Update PO status based on line receive statuses"""
    if not po.lines:
        return

    all_received = all(line.receive_status == 'received' for line in po.lines)
    any_partial = any(line.receive_status in ['partial', 'received'] for line in po.lines)

    if all_received:
        po.status = 'received'
    elif any_partial:
        po.status = 'partial'


# ============================================================================
# Purchase Order CRUD
# ============================================================================

@router.get("/", response_model=List[PurchaseOrderList])
async def list_purchase_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    address_book_id: Optional[int] = Query(None, description="Filter by Address Book vendor ID"),
    work_order_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all purchase orders for the company"""
    query = db.query(PurchaseOrder).filter(
        PurchaseOrder.company_id == current_user.company_id
    ).options(
        joinedload(PurchaseOrder.address_book),
        joinedload(PurchaseOrder.work_order),
        joinedload(PurchaseOrder.contract),
        joinedload(PurchaseOrder.creator),
        joinedload(PurchaseOrder.purchase_request),
        joinedload(PurchaseOrder.lines),
        joinedload(PurchaseOrder.linked_invoices)
    )

    if status_filter:
        query = query.filter(PurchaseOrder.status == status_filter)
    if address_book_id:
        query = query.filter(PurchaseOrder.address_book_id == address_book_id)
    if work_order_id:
        query = query.filter(PurchaseOrder.work_order_id == work_order_id)
    if contract_id:
        query = query.filter(PurchaseOrder.contract_id == contract_id)
    if search:
        query = query.filter(
            (PurchaseOrder.po_number.ilike(f"%{search}%"))
        )

    pos = query.order_by(PurchaseOrder.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for po in pos:
        # Get vendor name from Address Book
        vendor_name = po.address_book.alpha_name if po.address_book else "Unknown"

        result.append(PurchaseOrderList(
            id=po.id,
            po_number=po.po_number,
            pr_number=po.purchase_request.pr_number if po.purchase_request else None,
            status=po.status,
            vendor_name=vendor_name,
            total_amount=float(po.total_amount or 0),
            currency=po.currency,
            order_date=po.order_date,
            expected_date=po.expected_date,
            work_order_number=po.work_order.wo_number if po.work_order else None,
            contract_number=po.contract.contract_number if po.contract else None,
            created_by_name=po.creator.name if po.creator else "Unknown",
            created_at=po.created_at,
            line_count=len(po.lines),
            invoices_linked=len(po.linked_invoices)
        ))

    return result


@router.post("/", response_model=POSchema, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    po_data: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new purchase order directly (without PR)"""
    # Generate PO number
    po_number = generate_po_number(db, current_user.company_id)

    # Validate vendor from Address Book (search_type='V')
    # Support both address_book_id (preferred) and legacy vendor_id
    address_book_id = getattr(po_data, 'address_book_id', None) or getattr(po_data, 'vendor_id', None)

    if not address_book_id:
        raise HTTPException(status_code=400, detail="Vendor (address_book_id) is required")

    vendor = db.query(AddressBook).filter(
        AddressBook.id == address_book_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == 'V',
        AddressBook.is_active == True
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found in Address Book")

    # Validate optional references
    if po_data.work_order_id:
        wo = db.query(WorkOrder).filter(
            WorkOrder.id == po_data.work_order_id,
            WorkOrder.company_id == current_user.company_id
        ).first()
        if not wo:
            raise HTTPException(status_code=404, detail="Work order not found")

    if po_data.contract_id:
        contract = db.query(Contract).filter(
            Contract.id == po_data.contract_id,
            Contract.company_id == current_user.company_id
        ).first()
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

    # Create PO with Address Book vendor
    po = PurchaseOrder(
        company_id=current_user.company_id,
        po_number=po_number,
        purchase_request_id=po_data.purchase_request_id,
        address_book_id=address_book_id,  # Address Book vendor
        work_order_id=po_data.work_order_id,
        contract_id=po_data.contract_id,
        order_date=po_data.order_date,
        expected_date=po_data.expected_date,
        payment_terms=po_data.payment_terms,
        shipping_address=po_data.shipping_address,
        currency=po_data.currency,
        notes=po_data.notes,
        created_by=current_user.id,
        status='draft'
    )

    db.add(po)
    db.flush()

    # Add line items if provided
    subtotal = Decimal(0)
    if po_data.lines:
        for line_data in po_data.lines:
            total_price = Decimal(str(line_data.unit_price)) * Decimal(str(line_data.quantity_ordered))
            subtotal += total_price

            # Auto-resolve item_id from item_number if not provided
            resolved_item_id = resolve_item_id(
                db, current_user.company_id,
                line_data.item_id, line_data.item_number
            )

            line = PurchaseOrderLine(
                purchase_order_id=po.id,
                pr_line_id=line_data.pr_line_id,
                item_id=resolved_item_id,
                item_number=line_data.item_number,
                description=line_data.description,
                quantity_ordered=line_data.quantity_ordered,
                unit=line_data.unit,
                unit_price=line_data.unit_price,
                total_price=total_price,
                notes=line_data.notes
            )
            db.add(line)

    po.subtotal = subtotal
    po.total_amount = subtotal

    db.commit()
    db.refresh(po)

    logger.info(f"Purchase order created: {po.po_number} by user {current_user.id}")
    return po


@router.get("/{po_id}", response_model=POSchema)
async def get_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a purchase order by ID"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).options(
        joinedload(PurchaseOrder.lines),
        joinedload(PurchaseOrder.address_book),
        joinedload(PurchaseOrder.work_order),
        joinedload(PurchaseOrder.contract),
        joinedload(PurchaseOrder.purchase_request)
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()

    # Add has_grn attribute to PO object for serialization
    po.has_grn = grn_count > 0

    return po


@router.put("/{po_id}", response_model=POSchema)
async def update_purchase_order(
    po_id: int,
    po_data: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a purchase order (only if draft)"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only update draft purchase orders")

    # Update fields
    update_data = po_data.model_dump(exclude_unset=True)

    # Map vendor_id to address_book_id (schema uses vendor_id, model uses address_book_id)
    if 'vendor_id' in update_data:
        update_data['address_book_id'] = update_data.pop('vendor_id')

    for key, value in update_data.items():
        setattr(po, key, value)

    db.commit()
    db.refresh(po)

    logger.info(f"Purchase order updated: {po.po_number}")
    return po


@router.delete("/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a purchase order (only if draft)"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only delete draft purchase orders")

    db.delete(po)
    db.commit()

    logger.info(f"Purchase order deleted: {po.po_number}")


# ============================================================================
# PO Line Items
# ============================================================================

@router.post("/{po_id}/lines", response_model=POLineSchema, status_code=status.HTTP_201_CREATED)
async def add_po_line(
    po_id: int,
    line_data: PurchaseOrderLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add a line item to a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only add lines to draft purchase orders")

    total_price = Decimal(str(line_data.unit_price)) * Decimal(str(line_data.quantity_ordered))

    # Auto-resolve item_id from item_number if not provided
    resolved_item_id = resolve_item_id(
        db, current_user.company_id,
        line_data.item_id, line_data.item_number
    )

    line = PurchaseOrderLine(
        purchase_order_id=po.id,
        pr_line_id=line_data.pr_line_id,
        item_id=resolved_item_id,
        item_number=line_data.item_number,
        description=line_data.description,
        quantity_ordered=line_data.quantity_ordered,
        unit=line_data.unit,
        unit_price=line_data.unit_price,
        total_price=total_price,
        notes=line_data.notes
    )

    db.add(line)
    db.commit()

    # Recalculate PO totals
    db.refresh(po)
    subtotal, total = calculate_po_totals(po.lines)
    po.subtotal = subtotal
    po.total_amount = total
    db.commit()
    db.refresh(line)

    return line


@router.put("/{po_id}/lines/{line_id}", response_model=POLineSchema)
async def update_po_line(
    po_id: int,
    line_id: int,
    line_data: PurchaseOrderLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a line item in a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    # Allow editing for draft, sent, acknowledged, and partial statuses
    # Block editing for received and cancelled POs
    if po.status in ['received', 'cancelled']:
        raise HTTPException(status_code=400, detail="Cannot update lines in received or cancelled purchase orders")

    # Also block if PO has a GRN attached
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot update lines - purchase order has goods receipts")

    line = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.id == line_id,
        PurchaseOrderLine.purchase_order_id == po_id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    # Update fields
    update_data = line_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(line, key, value)

    # Auto-resolve item_id from item_number if item_number was updated and item_id is not set
    if 'item_number' in update_data and not line.item_id:
        resolved_item_id = resolve_item_id(
            db, current_user.company_id,
            None, line.item_number
        )
        if resolved_item_id:
            line.item_id = resolved_item_id

    # Recalculate line total
    line.total_price = Decimal(str(line.unit_price)) * Decimal(str(line.quantity_ordered))

    db.commit()

    # Recalculate PO totals
    db.refresh(po)
    subtotal, total = calculate_po_totals(po.lines)
    po.subtotal = subtotal
    po.total_amount = total
    db.commit()
    db.refresh(line)

    return line


@router.delete("/{po_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_po_line(
    po_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a line item from a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only delete lines from draft purchase orders")

    line = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.id == line_id,
        PurchaseOrderLine.purchase_order_id == po_id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    db.delete(line)
    db.commit()

    # Recalculate PO totals
    db.refresh(po)
    subtotal, total = calculate_po_totals(po.lines)
    po.subtotal = subtotal
    po.total_amount = total
    db.commit()


# ============================================================================
# PO Workflow Actions
# ============================================================================

@router.post("/{po_id}/send", response_model=POSchema)
async def send_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Mark a purchase order as sent to vendor"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).options(joinedload(PurchaseOrder.lines)).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only send draft purchase orders")

    if not po.lines:
        raise HTTPException(status_code=400, detail="Cannot send a purchase order without line items")

    po.status = 'sent'
    if not po.order_date:
        po.order_date = datetime.utcnow().date()

    db.commit()
    db.refresh(po)

    logger.info(f"Purchase order sent: {po.po_number}")
    return po


@router.post("/{po_id}/acknowledge", response_model=POSchema)
async def acknowledge_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Mark a purchase order as acknowledged by vendor"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status != 'sent':
        raise HTTPException(status_code=400, detail="Can only acknowledge sent purchase orders")

    po.status = 'acknowledged'

    db.commit()
    db.refresh(po)

    logger.info(f"Purchase order acknowledged: {po.po_number}")
    return po


@router.post("/{po_id}/lines/{line_id}/receive", response_model=POLineSchema)
async def receive_po_line(
    po_id: int,
    line_id: int,
    receive_data: PurchaseOrderLineReceive,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Receive items for a PO line (updates inventory if item is linked)"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).options(joinedload(PurchaseOrder.lines)).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status not in ['sent', 'acknowledged', 'partial']:
        raise HTTPException(status_code=400, detail="Can only receive items for sent/acknowledged/partial POs")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes - receiving should be done through GRN
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot receive items directly on PO that has Goods Receipt Notes. Use the GRN module to receive goods.")

    line = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.id == line_id,
        PurchaseOrderLine.purchase_order_id == po_id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    # Validate quantity
    total_will_be = float(line.quantity_received or 0) + receive_data.quantity_received
    if total_will_be > float(line.quantity_ordered):
        raise HTTPException(
            status_code=400,
            detail=f"Total received ({total_will_be}) cannot exceed ordered ({line.quantity_ordered})"
        )

    # Update line quantity
    old_qty = float(line.quantity_received or 0)
    line.quantity_received = Decimal(str(total_will_be))
    update_po_line_receive_status(line)

    # Update inventory if item is linked
    if line.item_id:
        item_stock = db.query(ItemStock).filter(
            ItemStock.item_id == line.item_id
        ).first()

        if item_stock:
            # Update on-hand quantity
            item_stock.quantity_on_hand = (item_stock.quantity_on_hand or 0) + Decimal(str(receive_data.quantity_received))
            # Decrease on-order quantity if tracked
            if item_stock.quantity_on_order:
                item_stock.quantity_on_order = max(0, item_stock.quantity_on_order - Decimal(str(receive_data.quantity_received)))

            # Generate transaction number for ledger entry
            today = datetime.now().strftime("%Y%m%d")
            tx_prefix = f"POR-{today}-"
            last_tx = db.query(ItemLedger).filter(
                ItemLedger.company_id == current_user.company_id,
                ItemLedger.transaction_number.like(f"{tx_prefix}%")
            ).order_by(ItemLedger.id.desc()).first()

            if last_tx:
                try:
                    last_num = int(last_tx.transaction_number.split("-")[-1])
                    next_num = last_num + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1
            tx_number = f"{tx_prefix}{next_num:05d}"

            # Create ledger entry (receiving goes TO warehouse, so use to_warehouse_id)
            ledger_entry = ItemLedger(
                company_id=current_user.company_id,
                item_id=line.item_id,
                transaction_number=tx_number,
                transaction_type='RECEIVE_PO',
                quantity=Decimal(str(receive_data.quantity_received)),
                unit=line.unit,
                unit_cost=line.unit_price,
                total_cost=Decimal(str(receive_data.quantity_received)) * (line.unit_price or Decimal('0')),
                to_warehouse_id=item_stock.warehouse_id,
                notes=f"Received from PO {po.po_number}",
                created_by=current_user.id
            )
            db.add(ledger_entry)
            db.flush()  # Flush to get ledger_entry.id

            # Auto-post journal entry for inventory receiving
            try:
                journal_service = JournalPostingService(db, current_user.company_id, current_user.id)
                journal_entry = journal_service.post_po_receiving(
                    po, line, Decimal(str(receive_data.quantity_received)), ledger_entry
                )
                if journal_entry:
                    logger.info(f"Auto-posted journal entry {journal_entry.entry_number} for PO receive")
            except Exception as e:
                logger.warning(f"Failed to auto-post journal entry for PO receive: {e}")

    db.commit()

    # Update PO status
    db.refresh(po)
    update_po_status(po)
    db.commit()
    db.refresh(line)

    logger.info(f"PO {po.po_number} line {line_id} received: {receive_data.quantity_received}")
    return line


@router.put("/{po_id}/lines/{line_id}/received", response_model=POLineSchema)
async def update_received_quantity(
    po_id: int,
    line_id: int,
    receive_data: PurchaseOrderLineReceive,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Update/correct the received quantity for a PO line.
    This is for correcting mistakes - it sets the quantity directly rather than adding to it.
    Will adjust inventory accordingly if item is linked.
    """
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).options(joinedload(PurchaseOrder.lines)).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status in ['cancelled']:
        raise HTTPException(status_code=400, detail="Cannot update received quantity for cancelled POs")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes - editing should be done through GRN
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot edit received quantities on PO that has Goods Receipt Notes. Use the GRN module to manage received goods.")

    line = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.id == line_id,
        PurchaseOrderLine.purchase_order_id == po_id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    new_quantity = Decimal(str(receive_data.quantity_received))

    # Validate new quantity doesn't exceed ordered
    if new_quantity > line.quantity_ordered:
        raise HTTPException(
            status_code=400,
            detail=f"Received quantity ({new_quantity}) cannot exceed ordered ({line.quantity_ordered})"
        )

    if new_quantity < 0:
        raise HTTPException(status_code=400, detail="Received quantity cannot be negative")

    old_quantity = Decimal(str(line.quantity_received or 0))
    quantity_diff = new_quantity - old_quantity

    # Update line quantity
    line.quantity_received = new_quantity
    update_po_line_receive_status(line)

    # Adjust inventory if item is linked and there's a difference
    if line.item_id and quantity_diff != 0:
        item_stock = db.query(ItemStock).filter(
            ItemStock.item_id == line.item_id
        ).first()

        if item_stock:
            # Adjust on-hand quantity by the difference
            item_stock.quantity_on_hand = (item_stock.quantity_on_hand or 0) + quantity_diff

            # Generate transaction number for adjustment ledger entry
            today = datetime.now().strftime("%Y%m%d")
            tx_prefix = f"POR-ADJ-{today}-"
            last_tx = db.query(ItemLedger).filter(
                ItemLedger.company_id == current_user.company_id,
                ItemLedger.transaction_number.like(f"{tx_prefix}%")
            ).order_by(ItemLedger.id.desc()).first()

            if last_tx:
                try:
                    last_num = int(last_tx.transaction_number.split("-")[-1])
                    next_num = last_num + 1
                except (ValueError, IndexError):
                    next_num = 1
            else:
                next_num = 1
            tx_number = f"{tx_prefix}{next_num:05d}"

            # Create adjustment ledger entry
            ledger_entry = ItemLedger(
                company_id=current_user.company_id,
                item_id=line.item_id,
                transaction_number=tx_number,
                transaction_type='RECEIVE_PO_ADJ',
                quantity=quantity_diff,  # Can be negative for corrections
                unit=line.unit,
                unit_cost=line.unit_price,
                total_cost=abs(quantity_diff) * (line.unit_price or Decimal('0')),
                to_warehouse_id=item_stock.warehouse_id if quantity_diff > 0 else None,
                from_warehouse_id=item_stock.warehouse_id if quantity_diff < 0 else None,
                notes=f"Received quantity adjustment for PO {po.po_number} (was {old_quantity}, now {new_quantity})",
                created_by=current_user.id
            )
            db.add(ledger_entry)

    db.commit()

    # Update PO status
    db.refresh(po)
    update_po_status(po)
    db.commit()
    db.refresh(line)

    logger.info(f"PO {po.po_number} line {line_id} received qty updated: {old_quantity} -> {new_quantity}")
    return line


@router.post("/{po_id}/cancel", response_model=POSchema)
async def cancel_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Cancel a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status in ['received', 'cancelled']:
        raise HTTPException(status_code=400, detail=f"Cannot cancel a {po.status} purchase order")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot cancel a purchase order that has Goods Receipt Notes. Please reverse the GRN first.")

    po.status = 'cancelled'

    # If PO originated from a Purchase Request, update PR status and add audit note
    pr_number = None
    if po.purchase_request_id:
        pr = db.query(PurchaseRequest).filter(
            PurchaseRequest.id == po.purchase_request_id
        ).first()
        if pr:
            pr_number = pr.pr_number
            # Revert PR status back to 'approved' so it can be re-ordered if needed
            pr.status = 'approved'
            # Add audit note to PR
            cancel_note = f"\n\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] PO {po.po_number} was cancelled by {current_user.name or current_user.email}. PR status reverted to 'approved'."
            pr.notes = (pr.notes or '') + cancel_note
            logger.info(f"Purchase request {pr.pr_number} status reverted to 'approved' after PO cancellation")

    # If PO is linked to a Work Order, add audit note to WO
    wo_number = None
    if po.work_order_id:
        wo = db.query(WorkOrder).filter(
            WorkOrder.id == po.work_order_id
        ).first()
        if wo:
            wo_number = wo.wo_number
            # Add audit note to Work Order
            wo_cancel_note = f"\n\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] PO {po.po_number} was cancelled by {current_user.name or current_user.email}."
            if pr_number:
                wo_cancel_note += f" Linked PR: {pr_number}."
            wo.notes = (wo.notes or '') + wo_cancel_note
            logger.info(f"Work order {wo.wo_number} updated with PO cancellation audit note")

    db.commit()
    db.refresh(po)

    log_msg = f"Purchase order cancelled: {po.po_number}"
    if pr_number:
        log_msg += f" | PR {pr_number} reverted to approved"
    if wo_number:
        log_msg += f" | WO {wo_number} audit note added"
    logger.info(log_msg)
    return po


@router.get("/{po_id}/reversal-preview")
async def get_reversal_preview(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Get a preview of what will happen when reversing a PO.
    Returns details about linked invoices and inventory impact.
    """
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    # Query lines directly to avoid any relationship loading issues
    po_lines = db.query(PurchaseOrderLine).filter(
        PurchaseOrderLine.purchase_order_id == po_id
    ).all()
    logger.info(f"Reversal preview for PO {po.po_number}: found {len(po_lines)} lines")

    # Query linked invoices directly
    invoice_links = db.query(PurchaseOrderInvoice).filter(
        PurchaseOrderInvoice.purchase_order_id == po_id
    ).all()

    # Get linked invoices with details
    linked_invoices = []
    for link in invoice_links:
        invoice = db.query(ProcessedImage).filter(
            ProcessedImage.id == link.invoice_id
        ).first()
        if invoice:
            # Extract invoice number from structured data if available
            invoice_number = "Unknown"
            if invoice.structured_data:
                try:
                    import json
                    data = json.loads(invoice.structured_data)
                    invoice_number = data.get('invoice_number', invoice.original_filename)
                except:
                    invoice_number = invoice.original_filename
            else:
                invoice_number = invoice.original_filename

            linked_invoices.append({
                "id": invoice.id,
                "invoice_number": invoice_number,
                "filename": invoice.original_filename,
                "linked_at": link.linked_at.isoformat() if link.linked_at else None,
                "notes": link.notes
            })

    # Calculate inventory impact - show all lines, indicate which have received quantities
    inventory_impact = []
    total_value_to_reverse = Decimal('0')
    has_received_items = False

    for line in po_lines:
        qty_received = line.quantity_received or Decimal('0')
        qty_ordered = line.quantity_ordered or Decimal('0')

        # Calculate value based on received quantity (what will actually be reversed)
        line_value = qty_received * (line.unit_price or Decimal('0'))
        if qty_received > 0:
            total_value_to_reverse += line_value
            has_received_items = True

        item_name = line.description
        if line.item_id:
            item = db.query(ItemMaster).filter(ItemMaster.id == line.item_id).first()
            if item:
                item_name = f"{item.item_number} - {item.description}"

        inventory_impact.append({
            "description": item_name,
            "quantity_ordered": float(qty_ordered),
            "quantity_to_reverse": float(qty_received),
            "unit": line.unit,
            "unit_price": float(line.unit_price or 0),
            "total_value": float(line_value),
            "receive_status": line.receive_status or "pending"
        })

    # Check if PO originated from a Purchase Request
    linked_pr = None
    if po.purchase_request_id:
        pr = db.query(PurchaseRequest).filter(
            PurchaseRequest.id == po.purchase_request_id
        ).first()
        if pr:
            linked_pr = {
                "id": pr.id,
                "pr_number": pr.pr_number,
                "title": pr.title,
                "current_status": pr.status,
                "will_revert_to": "approved"
            }

    # Check if PO is linked to a Work Order
    linked_wo = None
    if po.work_order_id:
        wo = db.query(WorkOrder).filter(
            WorkOrder.id == po.work_order_id
        ).first()
        if wo:
            linked_wo = {
                "id": wo.id,
                "wo_number": wo.wo_number,
                "title": wo.title,
                "status": wo.status
            }

    # Build warnings list
    warnings = []
    if linked_invoices:
        warnings.append(f"{len(linked_invoices)} invoice(s) will be unlinked from this PO")
    if linked_pr:
        warnings.append(f"Purchase Request {linked_pr['pr_number']} will revert to 'approved' status")
    if linked_wo:
        warnings.append(f"Work Order {linked_wo['wo_number']} will have audit note added")

    return {
        "po_id": po.id,
        "po_number": po.po_number,
        "status": po.status,
        "can_reverse": po.status not in ['cancelled', 'draft'],
        "has_received_items": has_received_items,
        "linked_invoices": linked_invoices,
        "linked_invoice_count": len(linked_invoices),
        "linked_pr": linked_pr,
        "linked_wo": linked_wo,
        "inventory_impact": inventory_impact,
        "total_value_to_reverse": float(total_value_to_reverse),
        "warnings": warnings
    }


@router.post("/{po_id}/reverse", response_model=POSchema)
async def reverse_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Reverse a received purchase order.
    This will:
    1. Unlink any associated invoices (preserving the invoices themselves)
    2. Reverse all inventory entries (subtract received quantities from stock)
    3. Create reversal ledger entries for audit trail
    4. Mark the PO as cancelled

    Note: Invoices are only unlinked, not deleted. They remain in the system
    for accounting purposes and can be linked to a new/corrected PO if needed.
    """
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).options(
        selectinload(PurchaseOrder.lines),
        selectinload(PurchaseOrder.linked_invoices)
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if po.status == 'cancelled':
        raise HTTPException(status_code=400, detail="Purchase order is already cancelled")

    if po.status == 'draft':
        raise HTTPException(status_code=400, detail="Draft POs should be deleted, not reversed")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot reverse a purchase order that has Goods Receipt Notes. Please reverse the GRN first.")

    # Step 1: Unlink any associated invoices
    unlinked_invoices = []
    for link in po.linked_invoices:
        invoice = db.query(ProcessedImage).filter(
            ProcessedImage.id == link.invoice_id
        ).first()
        if invoice:
            invoice_info = invoice.original_filename
            unlinked_invoices.append(invoice_info)
        db.delete(link)

    if unlinked_invoices:
        logger.info(f"Unlinked {len(unlinked_invoices)} invoice(s) from PO {po.po_number}: {', '.join(unlinked_invoices)}")

    # Step 2: Process each line that has received items - reverse inventory
    for line in po.lines:
        if line.quantity_received and line.quantity_received > 0:
            # Reverse inventory if item is linked
            if line.item_id:
                item_stock = db.query(ItemStock).filter(
                    ItemStock.item_id == line.item_id
                ).first()

                if item_stock:
                    # Subtract the received quantity from on-hand
                    item_stock.quantity_on_hand = (item_stock.quantity_on_hand or 0) - line.quantity_received

                    # Generate transaction number for reversal ledger entry
                    today = datetime.now().strftime("%Y%m%d")
                    tx_prefix = f"POR-REV-{today}-"
                    last_tx = db.query(ItemLedger).filter(
                        ItemLedger.company_id == current_user.company_id,
                        ItemLedger.transaction_number.like(f"{tx_prefix}%")
                    ).order_by(ItemLedger.id.desc()).first()

                    if last_tx:
                        try:
                            last_num = int(last_tx.transaction_number.split("-")[-1])
                            next_num = last_num + 1
                        except (ValueError, IndexError):
                            next_num = 1
                    else:
                        next_num = 1
                    tx_number = f"{tx_prefix}{next_num:05d}"

                    # Create reversal ledger entry (negative quantity out of warehouse)
                    ledger_entry = ItemLedger(
                        company_id=current_user.company_id,
                        item_id=line.item_id,
                        transaction_number=tx_number,
                        transaction_type='RECEIVE_PO_REVERSE',
                        quantity=-line.quantity_received,  # Negative to reverse
                        unit=line.unit,
                        unit_cost=line.unit_price,
                        total_cost=line.quantity_received * (line.unit_price or Decimal('0')),
                        from_warehouse_id=item_stock.warehouse_id,
                        notes=f"Reversal of PO {po.po_number} - Line: {line.description}" +
                              (f" | Unlinked invoices: {', '.join(unlinked_invoices)}" if unlinked_invoices else ""),
                        created_by=current_user.id
                    )
                    db.add(ledger_entry)

            # Reset the line's received quantity
            line.quantity_received = Decimal('0')
            line.receive_status = 'cancelled'

    # Step 3: Mark PO as cancelled
    po.status = 'cancelled'

    # Step 4: If PO originated from a Purchase Request, update PR status and add audit note
    pr_number = None
    if po.purchase_request_id:
        pr = db.query(PurchaseRequest).filter(
            PurchaseRequest.id == po.purchase_request_id
        ).first()
        if pr:
            pr_number = pr.pr_number
            # Revert PR status back to 'approved' so it can be re-ordered if needed
            pr.status = 'approved'
            # Add audit note to PR
            reversal_note = f"\n\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] PO {po.po_number} was reversed and cancelled by {current_user.name or current_user.email}."
            if unlinked_invoices:
                reversal_note += f" Unlinked invoices: {', '.join(unlinked_invoices)}."
            reversal_note += " PR status reverted to 'approved'."
            pr.notes = (pr.notes or '') + reversal_note
            logger.info(f"Purchase request {pr.pr_number} status reverted to 'approved' after PO reversal")

    # Step 5: If PO is linked to a Work Order, add audit note to WO
    wo_number = None
    if po.work_order_id:
        wo = db.query(WorkOrder).filter(
            WorkOrder.id == po.work_order_id
        ).first()
        if wo:
            wo_number = wo.wo_number
            # Add audit note to Work Order
            wo_reversal_note = f"\n\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] PO {po.po_number} was reversed and cancelled by {current_user.name or current_user.email}."
            if unlinked_invoices:
                wo_reversal_note += f" Unlinked invoices: {', '.join(unlinked_invoices)}."
            if pr_number:
                wo_reversal_note += f" Linked PR: {pr_number}."
            wo.notes = (wo.notes or '') + wo_reversal_note
            logger.info(f"Work order {wo.wo_number} updated with PO reversal audit note")

    db.commit()
    db.refresh(po)

    log_msg = f"Purchase order reversed and cancelled: {po.po_number}"
    if pr_number:
        log_msg += f" | PR {pr_number} reverted to approved"
    if wo_number:
        log_msg += f" | WO {wo_number} audit note added"
    if unlinked_invoices:
        log_msg += f" | {len(unlinked_invoices)} invoice(s) unlinked"
    logger.info(log_msg)
    return po


# ============================================================================
# Invoice Linking
# ============================================================================

@router.post("/{po_id}/link-invoice", response_model=POInvoiceSchema)
async def link_invoice_to_po(
    po_id: int,
    link_data: POInvoiceLink,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Link an invoice to a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot link invoices to a purchase order that has Goods Receipt Notes. Invoice matching should be done through the GRN.")

    # Verify invoice exists and belongs to same company (via user relationship)
    invoice = db.query(ProcessedImage).join(
        User, ProcessedImage.user_id == User.id
    ).filter(
        ProcessedImage.id == link_data.invoice_id,
        User.company_id == current_user.company_id
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Check if already linked
    existing_link = db.query(PurchaseOrderInvoice).filter(
        PurchaseOrderInvoice.purchase_order_id == po_id,
        PurchaseOrderInvoice.invoice_id == link_data.invoice_id
    ).first()

    if existing_link:
        raise HTTPException(status_code=400, detail="Invoice already linked to this PO")

    # Create link
    link = PurchaseOrderInvoice(
        purchase_order_id=po_id,
        invoice_id=link_data.invoice_id,
        linked_by=current_user.id,
        notes=link_data.notes
    )

    db.add(link)
    db.commit()
    db.refresh(link)

    logger.info(f"Invoice {link_data.invoice_id} linked to PO {po.po_number}")

    # Extract invoice data from structured_data JSON
    invoice_number = None
    vendor_name = None
    total_amount = None
    if invoice.structured_data:
        import json
        try:
            data = json.loads(invoice.structured_data)
            invoice_number = data.get('document_info', {}).get('invoice_number')
            vendor_name = data.get('supplier', {}).get('company_name')
            total_amount = data.get('financial', {}).get('total_amount')
        except (json.JSONDecodeError, TypeError):
            pass

    # Return with invoice details
    return POInvoiceSchema(
        id=link.id,
        purchase_order_id=link.purchase_order_id,
        invoice_id=link.invoice_id,
        linked_by=link.linked_by,
        linked_at=link.linked_at,
        notes=link.notes,
        invoice_number=invoice_number,
        invoice_vendor_name=vendor_name,
        invoice_total=float(total_amount) if total_amount else None
    )


@router.get("/{po_id}/invoices", response_model=List[POInvoiceSchema])
async def get_po_invoices(
    po_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all invoices linked to a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    links = db.query(PurchaseOrderInvoice).filter(
        PurchaseOrderInvoice.purchase_order_id == po_id
    ).options(joinedload(PurchaseOrderInvoice.invoice)).all()

    result = []
    for link in links:
        invoice = link.invoice
        # Extract invoice data from structured_data JSON
        invoice_number = None
        vendor_name = None
        total_amount = None
        if invoice and invoice.structured_data:
            import json
            try:
                data = json.loads(invoice.structured_data)
                invoice_number = data.get('document_info', {}).get('invoice_number')
                vendor_name = data.get('supplier', {}).get('company_name')
                # Get total from financial_details.total_after_tax (primary location)
                total_amount = data.get('financial_details', {}).get('total_after_tax')
            except (json.JSONDecodeError, TypeError):
                pass

        result.append(POInvoiceSchema(
            id=link.id,
            purchase_order_id=link.purchase_order_id,
            invoice_id=link.invoice_id,
            linked_by=link.linked_by,
            linked_at=link.linked_at,
            notes=link.notes,
            invoice_number=invoice_number,
            invoice_vendor_name=vendor_name,
            invoice_total=float(total_amount) if total_amount else None
        ))

    return result


@router.delete("/{po_id}/invoices/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_invoice_from_po(
    po_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Remove an invoice link from a purchase order"""
    po = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == po_id,
        PurchaseOrder.company_id == current_user.company_id
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    # Check if PO has any active (non-cancelled) Goods Receipt Notes
    grn_count = db.query(func.count(GoodsReceipt.id)).filter(
        GoodsReceipt.purchase_order_id == po_id,
        GoodsReceipt.status != 'cancelled'
    ).scalar()
    if grn_count > 0:
        raise HTTPException(status_code=400, detail="Cannot unlink invoices from a purchase order that has Goods Receipt Notes.")

    link = db.query(PurchaseOrderInvoice).filter(
        PurchaseOrderInvoice.id == link_id,
        PurchaseOrderInvoice.purchase_order_id == po_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Invoice link not found")

    db.delete(link)
    db.commit()

    logger.info(f"Invoice unlinked from PO {po.po_number}")
