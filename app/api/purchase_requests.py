from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from app.database import get_db
from app.models import (
    PurchaseRequest, PurchaseRequestLine, PurchaseOrder, PurchaseOrderLine,
    User, Vendor, WorkOrder, Contract, ItemMaster, Company
)
from app.utils.security import verify_token
from app.schemas import (
    PurchaseRequestCreate, PurchaseRequestUpdate, PurchaseRequest as PRSchema,
    PurchaseRequestList, PurchaseRequestLineCreate, PurchaseRequestLineUpdate,
    PurchaseRequestLine as PRLineSchema, PurchaseRequestApproval,
    PurchaseRequestRejection, ConvertToPORequest
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


def generate_pr_number(db: Session, company_id: int) -> str:
    """Generate next PR number: PR-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"PR-{year}-"

    # Find the highest PR number for this company and year
    last_pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.company_id == company_id,
        PurchaseRequest.pr_number.like(f"{prefix}%")
    ).order_by(PurchaseRequest.pr_number.desc()).first()

    if last_pr:
        # Extract the number part and increment
        try:
            last_num = int(last_pr.pr_number.replace(prefix, ""))
            next_num = last_num + 1
        except ValueError:
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def calculate_pr_total(lines: list) -> Decimal:
    """Calculate total estimated cost from PR lines"""
    total = Decimal(0)
    for line in lines:
        if hasattr(line, 'estimated_total') and line.estimated_total:
            total += Decimal(str(line.estimated_total))
        elif hasattr(line, 'estimated_unit_cost') and line.estimated_unit_cost and hasattr(line, 'quantity_requested'):
            total += Decimal(str(line.estimated_unit_cost)) * Decimal(str(line.quantity_requested))
    return total


# ============================================================================
# Purchase Request CRUD
# ============================================================================

@router.get("/", response_model=List[PurchaseRequestList])
async def list_purchase_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    vendor_id: Optional[int] = None,
    work_order_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all purchase requests for the company"""
    query = db.query(PurchaseRequest).filter(
        PurchaseRequest.company_id == current_user.company_id
    ).options(
        joinedload(PurchaseRequest.vendor),
        joinedload(PurchaseRequest.work_order),
        joinedload(PurchaseRequest.contract),
        joinedload(PurchaseRequest.creator),
        joinedload(PurchaseRequest.lines)
    )

    if status_filter:
        query = query.filter(PurchaseRequest.status == status_filter)
    if priority:
        query = query.filter(PurchaseRequest.priority == priority)
    if vendor_id:
        query = query.filter(PurchaseRequest.vendor_id == vendor_id)
    if work_order_id:
        query = query.filter(PurchaseRequest.work_order_id == work_order_id)
    if contract_id:
        query = query.filter(PurchaseRequest.contract_id == contract_id)
    if search:
        query = query.filter(
            (PurchaseRequest.pr_number.ilike(f"%{search}%")) |
            (PurchaseRequest.title.ilike(f"%{search}%"))
        )

    prs = query.order_by(PurchaseRequest.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for pr in prs:
        result.append(PurchaseRequestList(
            id=pr.id,
            pr_number=pr.pr_number,
            status=pr.status,
            title=pr.title,
            priority=pr.priority,
            estimated_total=float(pr.estimated_total or 0),
            currency=pr.currency,
            required_date=pr.required_date,
            vendor_name=pr.vendor.name if pr.vendor else None,
            work_order_number=pr.work_order.wo_number if pr.work_order else None,
            contract_number=pr.contract.contract_number if pr.contract else None,
            created_by_name=pr.creator.name if pr.creator else "Unknown",
            created_at=pr.created_at,
            line_count=len(pr.lines)
        ))

    return result


@router.post("/", response_model=PRSchema, status_code=status.HTTP_201_CREATED)
async def create_purchase_request(
    pr_data: PurchaseRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new purchase request (admin only)"""
    # Generate PR number
    pr_number = generate_pr_number(db, current_user.company_id)

    # Validate references
    if pr_data.vendor_id:
        vendor = db.query(Vendor).filter(
            Vendor.id == pr_data.vendor_id,
            Vendor.company_id == current_user.company_id
        ).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

    if pr_data.work_order_id:
        wo = db.query(WorkOrder).filter(
            WorkOrder.id == pr_data.work_order_id,
            WorkOrder.company_id == current_user.company_id
        ).first()
        if not wo:
            raise HTTPException(status_code=404, detail="Work order not found")

    if pr_data.contract_id:
        contract = db.query(Contract).filter(
            Contract.id == pr_data.contract_id,
            Contract.company_id == current_user.company_id
        ).first()
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

    # Create PR
    pr = PurchaseRequest(
        company_id=current_user.company_id,
        pr_number=pr_number,
        title=pr_data.title,
        description=pr_data.description,
        vendor_id=pr_data.vendor_id,
        work_order_id=pr_data.work_order_id,
        contract_id=pr_data.contract_id,
        required_date=pr_data.required_date,
        priority=pr_data.priority,
        currency=pr_data.currency,
        notes=pr_data.notes,
        created_by=current_user.id,
        status='draft'
    )

    db.add(pr)
    db.flush()  # Get the PR id

    # Add line items if provided
    if pr_data.lines:
        for line_data in pr_data.lines:
            estimated_total = None
            if line_data.estimated_unit_cost and line_data.quantity_requested:
                estimated_total = float(line_data.estimated_unit_cost) * float(line_data.quantity_requested)

            line = PurchaseRequestLine(
                purchase_request_id=pr.id,
                item_id=line_data.item_id,
                item_number=line_data.item_number,
                description=line_data.description,
                quantity_requested=line_data.quantity_requested,
                unit=line_data.unit,
                estimated_unit_cost=line_data.estimated_unit_cost,
                estimated_total=estimated_total,
                notes=line_data.notes
            )
            db.add(line)

    db.commit()

    # Recalculate total
    db.refresh(pr)
    pr.estimated_total = calculate_pr_total(pr.lines)
    db.commit()
    db.refresh(pr)

    logger.info(f"Purchase request created: {pr.pr_number} by user {current_user.id}")
    return pr


@router.get("/{pr_id}", response_model=PRSchema)
async def get_purchase_request(
    pr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a purchase request by ID"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).options(
        joinedload(PurchaseRequest.lines),
        joinedload(PurchaseRequest.vendor),
        joinedload(PurchaseRequest.work_order),
        joinedload(PurchaseRequest.contract)
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    return pr


@router.put("/{pr_id}", response_model=PRSchema)
async def update_purchase_request(
    pr_id: int,
    pr_data: PurchaseRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a purchase request (only if draft)"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only update draft purchase requests")

    # Update fields
    update_data = pr_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(pr, key, value)

    db.commit()
    db.refresh(pr)

    logger.info(f"Purchase request updated: {pr.pr_number}")
    return pr


@router.delete("/{pr_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase_request(
    pr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a purchase request (only if draft)"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only delete draft purchase requests")

    db.delete(pr)
    db.commit()

    logger.info(f"Purchase request deleted: {pr.pr_number}")


# ============================================================================
# PR Line Items
# ============================================================================

@router.post("/{pr_id}/lines", response_model=PRLineSchema, status_code=status.HTTP_201_CREATED)
async def add_pr_line(
    pr_id: int,
    line_data: PurchaseRequestLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add a line item to a purchase request"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only add lines to draft purchase requests")

    # Calculate estimated total
    estimated_total = None
    if line_data.estimated_unit_cost and line_data.quantity_requested:
        estimated_total = float(line_data.estimated_unit_cost) * float(line_data.quantity_requested)

    line = PurchaseRequestLine(
        purchase_request_id=pr.id,
        item_id=line_data.item_id,
        item_number=line_data.item_number,
        description=line_data.description,
        quantity_requested=line_data.quantity_requested,
        unit=line_data.unit,
        estimated_unit_cost=line_data.estimated_unit_cost,
        estimated_total=estimated_total,
        notes=line_data.notes
    )

    db.add(line)
    db.commit()

    # Update PR total
    db.refresh(pr)
    pr.estimated_total = calculate_pr_total(pr.lines)
    db.commit()
    db.refresh(line)

    return line


@router.put("/{pr_id}/lines/{line_id}", response_model=PRLineSchema)
async def update_pr_line(
    pr_id: int,
    line_id: int,
    line_data: PurchaseRequestLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a line item in a purchase request"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only update lines in draft purchase requests")

    line = db.query(PurchaseRequestLine).filter(
        PurchaseRequestLine.id == line_id,
        PurchaseRequestLine.purchase_request_id == pr_id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    # Update fields
    update_data = line_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(line, key, value)

    # Recalculate line total
    if line.estimated_unit_cost and line.quantity_requested:
        line.estimated_total = float(line.estimated_unit_cost) * float(line.quantity_requested)

    db.commit()

    # Update PR total
    db.refresh(pr)
    pr.estimated_total = calculate_pr_total(pr.lines)
    db.commit()
    db.refresh(line)

    return line


@router.delete("/{pr_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pr_line(
    pr_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a line item from a purchase request"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only delete lines from draft purchase requests")

    line = db.query(PurchaseRequestLine).filter(
        PurchaseRequestLine.id == line_id,
        PurchaseRequestLine.purchase_request_id == pr_id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Line item not found")

    db.delete(line)
    db.commit()

    # Update PR total
    db.refresh(pr)
    pr.estimated_total = calculate_pr_total(pr.lines)
    db.commit()


# ============================================================================
# PR Workflow Actions
# ============================================================================

@router.post("/{pr_id}/submit", response_model=PRSchema)
async def submit_purchase_request(
    pr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Submit a purchase request for approval"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).options(joinedload(PurchaseRequest.lines)).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'draft':
        raise HTTPException(status_code=400, detail="Can only submit draft purchase requests")

    if not pr.lines:
        raise HTTPException(status_code=400, detail="Cannot submit a purchase request without line items")

    pr.status = 'submitted'
    pr.submitted_at = datetime.utcnow()
    pr.submitted_by = current_user.id

    db.commit()
    db.refresh(pr)

    logger.info(f"Purchase request submitted: {pr.pr_number}")
    return pr


@router.post("/{pr_id}/approve", response_model=PRSchema)
async def approve_purchase_request(
    pr_id: int,
    approval_data: PurchaseRequestApproval,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Approve a purchase request"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).options(joinedload(PurchaseRequest.lines)).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'submitted':
        raise HTTPException(status_code=400, detail="Can only approve submitted purchase requests")

    # Apply line approvals if provided
    if approval_data.line_approvals:
        for line_id, approved_qty in approval_data.line_approvals.items():
            line = db.query(PurchaseRequestLine).filter(
                PurchaseRequestLine.id == int(line_id),
                PurchaseRequestLine.purchase_request_id == pr_id
            ).first()
            if line:
                line.quantity_approved = approved_qty
    else:
        # Default: approve all requested quantities
        for line in pr.lines:
            line.quantity_approved = line.quantity_requested

    pr.status = 'approved'
    pr.approved_at = datetime.utcnow()
    pr.approved_by = current_user.id

    if approval_data.notes:
        pr.notes = (pr.notes or "") + f"\nApproval notes: {approval_data.notes}"

    db.commit()
    db.refresh(pr)

    logger.info(f"Purchase request approved: {pr.pr_number}")
    return pr


@router.post("/{pr_id}/reject", response_model=PRSchema)
async def reject_purchase_request(
    pr_id: int,
    rejection_data: PurchaseRequestRejection,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Reject a purchase request"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'submitted':
        raise HTTPException(status_code=400, detail="Can only reject submitted purchase requests")

    pr.status = 'rejected'
    pr.rejected_at = datetime.utcnow()
    pr.rejected_by = current_user.id
    pr.rejection_reason = rejection_data.reason

    db.commit()
    db.refresh(pr)

    logger.info(f"Purchase request rejected: {pr.pr_number}")
    return pr


@router.post("/{pr_id}/convert-to-po")
async def convert_pr_to_po(
    pr_id: int,
    convert_data: ConvertToPORequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Convert an approved purchase request to a purchase order"""
    from app.api.purchase_orders import generate_po_number

    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).options(joinedload(PurchaseRequest.lines)).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status != 'approved':
        raise HTTPException(status_code=400, detail="Can only convert approved purchase requests to PO")

    # Validate vendor
    vendor = db.query(Vendor).filter(
        Vendor.id == convert_data.vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Generate PO number
    po_number = generate_po_number(db, current_user.company_id)

    # Create PO
    po = PurchaseOrder(
        company_id=current_user.company_id,
        po_number=po_number,
        purchase_request_id=pr.id,
        vendor_id=convert_data.vendor_id,
        work_order_id=pr.work_order_id,
        contract_id=pr.contract_id,
        order_date=convert_data.order_date,
        expected_date=convert_data.expected_date,
        payment_terms=convert_data.payment_terms,
        shipping_address=convert_data.shipping_address,
        currency=pr.currency,
        created_by=current_user.id,
        status='draft'
    )

    db.add(po)
    db.flush()

    # Create PO lines from PR lines
    subtotal = Decimal(0)
    for pr_line in pr.lines:
        # Get unit price from request or use estimated cost
        unit_price = Decimal(0)
        if convert_data.line_prices and str(pr_line.id) in convert_data.line_prices:
            unit_price = Decimal(str(convert_data.line_prices[str(pr_line.id)]))
        elif pr_line.estimated_unit_cost:
            unit_price = Decimal(str(pr_line.estimated_unit_cost))

        qty = pr_line.quantity_approved or pr_line.quantity_requested
        total_price = unit_price * Decimal(str(qty))
        subtotal += total_price

        po_line = PurchaseOrderLine(
            purchase_order_id=po.id,
            pr_line_id=pr_line.id,
            item_id=pr_line.item_id,
            item_number=pr_line.item_number,
            description=pr_line.description,
            quantity_ordered=qty,
            unit=pr_line.unit,
            unit_price=unit_price,
            total_price=total_price
        )
        db.add(po_line)

    po.subtotal = subtotal
    po.total_amount = subtotal  # Tax can be added later

    # Update PR status
    pr.status = 'ordered'

    db.commit()
    db.refresh(po)

    logger.info(f"Purchase request {pr.pr_number} converted to PO {po.po_number}")

    return {
        "success": True,
        "message": f"Purchase order {po.po_number} created from {pr.pr_number}",
        "po_id": po.id,
        "po_number": po.po_number
    }


@router.post("/{pr_id}/cancel", response_model=PRSchema)
async def cancel_purchase_request(
    pr_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Cancel a purchase request"""
    pr = db.query(PurchaseRequest).filter(
        PurchaseRequest.id == pr_id,
        PurchaseRequest.company_id == current_user.company_id
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Purchase request not found")

    if pr.status in ['ordered', 'cancelled']:
        raise HTTPException(status_code=400, detail=f"Cannot cancel a {pr.status} purchase request")

    pr.status = 'cancelled'

    db.commit()
    db.refresh(pr)

    logger.info(f"Purchase request cancelled: {pr.pr_number}")
    return pr
