from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from app.database import get_db
from app.models import (
    PurchaseOrder, PurchaseOrderLine, PurchaseOrderInvoice, PurchaseRequest,
    User, Vendor, WorkOrder, Contract, ItemMaster, ProcessedImage,
    ItemStock, ItemLedger
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
    """Generate next PO number: PO-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"PO-{year}-"

    # Find the highest PO number for this company and year
    last_po = db.query(PurchaseOrder).filter(
        PurchaseOrder.company_id == company_id,
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
    vendor_id: Optional[int] = None,
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
        joinedload(PurchaseOrder.vendor),
        joinedload(PurchaseOrder.work_order),
        joinedload(PurchaseOrder.contract),
        joinedload(PurchaseOrder.creator),
        joinedload(PurchaseOrder.purchase_request),
        joinedload(PurchaseOrder.lines),
        joinedload(PurchaseOrder.linked_invoices)
    )

    if status_filter:
        query = query.filter(PurchaseOrder.status == status_filter)
    if vendor_id:
        query = query.filter(PurchaseOrder.vendor_id == vendor_id)
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
        result.append(PurchaseOrderList(
            id=po.id,
            po_number=po.po_number,
            pr_number=po.purchase_request.pr_number if po.purchase_request else None,
            status=po.status,
            vendor_name=po.vendor.name if po.vendor else "Unknown",
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

    # Validate vendor
    vendor = db.query(Vendor).filter(
        Vendor.id == po_data.vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

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

    # Create PO
    po = PurchaseOrder(
        company_id=current_user.company_id,
        po_number=po_number,
        purchase_request_id=po_data.purchase_request_id,
        vendor_id=po_data.vendor_id,
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

            line = PurchaseOrderLine(
                purchase_order_id=po.id,
                pr_line_id=line_data.pr_line_id,
                item_id=line_data.item_id,
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
        joinedload(PurchaseOrder.vendor),
        joinedload(PurchaseOrder.work_order),
        joinedload(PurchaseOrder.contract),
        joinedload(PurchaseOrder.purchase_request)
    ).first()

    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

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

    line = PurchaseOrderLine(
        purchase_order_id=po.id,
        pr_line_id=line_data.pr_line_id,
        item_id=line_data.item_id,
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

    if po.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only update lines in draft purchase orders")

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

    po.status = 'cancelled'

    db.commit()
    db.refresh(po)

    logger.info(f"Purchase order cancelled: {po.po_number}")
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

    # Verify invoice exists and belongs to same company
    invoice = db.query(ProcessedImage).filter(
        ProcessedImage.id == link_data.invoice_id,
        ProcessedImage.company_id == current_user.company_id
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

    # Return with invoice details
    return POInvoiceSchema(
        id=link.id,
        purchase_order_id=link.purchase_order_id,
        invoice_id=link.invoice_id,
        linked_by=link.linked_by,
        linked_at=link.linked_at,
        notes=link.notes,
        invoice_number=invoice.vendor_invoice_number,
        invoice_vendor_name=invoice.vendor_name,
        invoice_total=float(invoice.total_amount) if invoice.total_amount else None
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
        result.append(POInvoiceSchema(
            id=link.id,
            purchase_order_id=link.purchase_order_id,
            invoice_id=link.invoice_id,
            linked_by=link.linked_by,
            linked_at=link.linked_at,
            notes=link.notes,
            invoice_number=invoice.vendor_invoice_number if invoice else None,
            invoice_vendor_name=invoice.vendor_name if invoice else None,
            invoice_total=float(invoice.total_amount) if invoice and invoice.total_amount else None
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

    link = db.query(PurchaseOrderInvoice).filter(
        PurchaseOrderInvoice.id == link_id,
        PurchaseOrderInvoice.purchase_order_id == po_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Invoice link not found")

    db.delete(link)
    db.commit()

    logger.info(f"Invoice unlinked from PO {po.po_number}")
