"""
Disposals API endpoints.

Features:
- Unified disposal document for both tools and inventory items
- Disposal workflow: draft -> approved -> posted
- Proper accounting entries for asset write-offs and inventory losses
- Salvage value tracking with gain/loss calculation
- Full audit trail
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, desc, or_
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
import logging

from app.database import get_db
from app.models import (
    User, Vendor, Site, Technician, Warehouse, Account, AccountType,
    Tool, ToolCategory, ItemMaster, ItemStock, ItemLedger,
    Disposal, DisposalToolLine, DisposalItemLine,
    JournalEntry, JournalEntryLine, FiscalPeriod, BusinessUnit
)
from app.schemas import (
    DisposalCreate, DisposalUpdate, Disposal as DisposalSchema, DisposalList,
    DisposalToolLineCreate, DisposalToolLineUpdate, DisposalToolLine as DisposalToolLineSchema,
    DisposalItemLineCreate, DisposalItemLineUpdate, DisposalItemLine as DisposalItemLineSchema,
    AvailableToolForDisposal, AvailableItemForDisposal
)
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_disposal_number(db: Session, company_id: int) -> str:
    """Generate unique disposal number: DSP-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"DSP-{year}-"

    last_disposal = db.query(Disposal).filter(
        Disposal.company_id == company_id,
        Disposal.disposal_number.like(f"{prefix}%")
    ).order_by(Disposal.id.desc()).first()

    if last_disposal:
        try:
            last_num = int(last_disposal.disposal_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def generate_journal_entry_number(db: Session, company_id: int) -> str:
    """Generate unique journal entry number: JE-YYYY-NNNNNN"""
    year = datetime.now().year
    prefix = f"JE-{year}-"

    last_entry = db.query(JournalEntry).filter(
        JournalEntry.company_id == company_id,
        JournalEntry.entry_number.like(f"{prefix}%")
    ).order_by(JournalEntry.id.desc()).first()

    if last_entry:
        try:
            last_num = int(last_entry.entry_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:06d}"


def get_tool_current_location(tool: Tool) -> Optional[str]:
    """Get tool's current location as string"""
    if tool.assigned_site_id and tool.assigned_site:
        return f"Site: {tool.assigned_site.name}"
    elif tool.assigned_technician_id and tool.assigned_technician:
        return f"Technician: {tool.assigned_technician.name}"
    elif tool.assigned_warehouse_id and tool.assigned_warehouse:
        return f"Warehouse: {tool.assigned_warehouse.name}"
    return None


def get_business_unit_for_disposal(db: Session, company_id: int, warehouse_id: Optional[int] = None) -> Optional[int]:
    """Get business_unit_id from warehouse or default to company's balance sheet BU"""
    # Try to get from warehouse first
    if warehouse_id:
        warehouse = db.query(Warehouse).filter(
            Warehouse.id == warehouse_id,
            Warehouse.company_id == company_id
        ).first()
        if warehouse and warehouse.business_unit_id:
            return warehouse.business_unit_id

    # Fall back to company's default balance sheet BU
    bu = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == company_id,
        BusinessUnit.bu_type == "balance_sheet",
        BusinessUnit.is_active == True,
        BusinessUnit.parent_id == None
    ).first()
    return bu.id if bu else None


def disposal_to_response(disposal: Disposal) -> dict:
    """Convert Disposal to response dict with computed totals"""
    # Calculate totals
    total_tool_value = sum(float(line.original_cost or 0) for line in disposal.tool_lines)
    total_tool_nbv = sum(float(line.net_book_value or 0) for line in disposal.tool_lines)
    total_item_value = sum(float(line.total_cost or 0) for line in disposal.item_lines)
    total_gain_loss = (
        sum(float(line.gain_loss or 0) for line in disposal.tool_lines) +
        sum(float(line.gain_loss or 0) for line in disposal.item_lines)
    )

    return {
        "id": disposal.id,
        "company_id": disposal.company_id,
        "disposal_number": disposal.disposal_number,
        "disposal_date": disposal.disposal_date,
        "reason": disposal.reason,
        "method": disposal.method,
        "salvage_received": float(disposal.salvage_received or 0),
        "salvage_reference": disposal.salvage_reference,
        "status": disposal.status,
        "approved_by": disposal.approved_by,
        "approved_at": disposal.approved_at,
        "posted_by": disposal.posted_by,
        "posted_at": disposal.posted_at,
        "journal_entry_id": disposal.journal_entry_id,
        "journal_entry_number": disposal.journal_entry.entry_number if disposal.journal_entry else None,
        "notes": disposal.notes,
        "created_by": disposal.created_by,
        "created_by_name": disposal.creator.name if disposal.creator else None,
        "created_at": disposal.created_at,
        "updated_at": disposal.updated_at,
        # Lines
        "tool_lines": [tool_line_to_response(line) for line in disposal.tool_lines],
        "item_lines": [item_line_to_response(line) for line in disposal.item_lines],
        # Computed totals
        "total_tool_value": total_tool_value,
        "total_tool_nbv": total_tool_nbv,
        "total_item_value": total_item_value,
        "total_gain_loss": total_gain_loss,
        "tool_count": len(disposal.tool_lines),
        "item_count": len(disposal.item_lines),
    }


def tool_line_to_response(line: DisposalToolLine) -> dict:
    """Convert DisposalToolLine to response dict"""
    return {
        "id": line.id,
        "line_number": line.line_number,
        "tool_id": line.tool_id,
        "tool_number": line.tool.tool_number if line.tool else None,
        "tool_name": line.tool.name if line.tool else None,
        "original_cost": float(line.original_cost or 0),
        "accumulated_depreciation": float(line.accumulated_depreciation or 0),
        "net_book_value": float(line.net_book_value or 0),
        "salvage_value": float(line.salvage_value or 0),
        "gain_loss": float(line.gain_loss or 0),
        "notes": line.notes,
    }


def item_line_to_response(line: DisposalItemLine) -> dict:
    """Convert DisposalItemLine to response dict"""
    return {
        "id": line.id,
        "line_number": line.line_number,
        "item_id": line.item_id,
        "item_number": line.item.item_number if line.item else None,
        "item_name": line.item.description if line.item else None,
        "warehouse_id": line.warehouse_id,
        "warehouse_name": line.warehouse.name if line.warehouse else None,
        "quantity": float(line.quantity or 0),
        "unit_cost": float(line.unit_cost or 0),
        "total_cost": float(line.total_cost or 0),
        "salvage_value": float(line.salvage_value or 0),
        "gain_loss": float(line.gain_loss or 0),
        "notes": line.notes,
    }


# =============================================================================
# DISPOSAL CRUD ENDPOINTS
# =============================================================================

@router.get("/disposals", response_model=List[dict])
async def list_disposals(
    status: Optional[str] = Query(None, description="Filter by status"),
    reason: Optional[str] = Query(None, description="Filter by reason"),
    from_date: Optional[date] = Query(None, description="Filter from date"),
    to_date: Optional[date] = Query(None, description="Filter to date"),
    search: Optional[str] = Query(None, description="Search by disposal number"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all disposals with optional filters"""
    query = db.query(Disposal).filter(
        Disposal.company_id == current_user.company_id
    )

    if status:
        query = query.filter(Disposal.status == status)
    if reason:
        query = query.filter(Disposal.reason == reason)
    if from_date:
        query = query.filter(Disposal.disposal_date >= from_date)
    if to_date:
        query = query.filter(Disposal.disposal_date <= to_date)
    if search:
        query = query.filter(Disposal.disposal_number.ilike(f"%{search}%"))

    disposals = query.options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
    ).order_by(desc(Disposal.disposal_date), desc(Disposal.id)).offset(skip).limit(limit).all()

    result = []
    for disposal in disposals:
        total_value = (
            sum(float(line.net_book_value or 0) for line in disposal.tool_lines) +
            sum(float(line.total_cost or 0) for line in disposal.item_lines)
        )
        total_gain_loss = (
            sum(float(line.gain_loss or 0) for line in disposal.tool_lines) +
            sum(float(line.gain_loss or 0) for line in disposal.item_lines)
        )
        result.append({
            "id": disposal.id,
            "disposal_number": disposal.disposal_number,
            "disposal_date": disposal.disposal_date,
            "reason": disposal.reason,
            "method": disposal.method,
            "status": disposal.status,
            "salvage_received": float(disposal.salvage_received or 0),
            "tool_count": len(disposal.tool_lines),
            "item_count": len(disposal.item_lines),
            "total_value": total_value,
            "total_gain_loss": total_gain_loss,
            "created_by_name": disposal.creator.name if disposal.creator else None,
            "created_at": disposal.created_at,
        })

    return result


@router.post("/disposals", response_model=dict)
async def create_disposal(
    data: DisposalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new disposal document"""
    # Generate disposal number
    disposal_number = generate_disposal_number(db, current_user.company_id)

    # Create disposal header
    disposal = Disposal(
        company_id=current_user.company_id,
        disposal_number=disposal_number,
        disposal_date=data.disposal_date,
        reason=data.reason,
        method=data.method,
        salvage_received=data.salvage_received or 0,
        salvage_reference=data.salvage_reference,
        notes=data.notes,
        status="draft",
        created_by=current_user.id,
    )
    db.add(disposal)
    db.flush()

    # Add tool lines
    for i, tool_line_data in enumerate(data.tool_lines):
        tool = db.query(Tool).filter(
            Tool.id == tool_line_data.tool_id,
            Tool.company_id == current_user.company_id,
            Tool.is_disposed == False,
            Tool.is_active == True
        ).first()

        if not tool:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tool {tool_line_data.tool_id} not found or already disposed"
            )

        # Calculate values
        original_cost = float(tool.purchase_cost or 0)
        accumulated_depreciation = float(tool.accumulated_depreciation or 0)
        net_book_value = original_cost - accumulated_depreciation
        salvage_value = float(tool_line_data.salvage_value or 0)
        gain_loss = salvage_value - net_book_value

        tool_line = DisposalToolLine(
            disposal_id=disposal.id,
            line_number=i + 1,
            tool_id=tool.id,
            original_cost=original_cost,
            accumulated_depreciation=accumulated_depreciation,
            net_book_value=net_book_value,
            salvage_value=salvage_value,
            gain_loss=gain_loss,
            notes=tool_line_data.notes,
        )
        db.add(tool_line)

    # Add item lines
    for i, item_line_data in enumerate(data.item_lines):
        item = db.query(ItemMaster).filter(
            ItemMaster.id == item_line_data.item_id,
            ItemMaster.company_id == current_user.company_id
        ).first()

        if not item:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Item {item_line_data.item_id} not found"
            )

        # Get stock for the warehouse
        stock = db.query(ItemStock).filter(
            ItemStock.item_id == item_line_data.item_id,
            ItemStock.warehouse_id == item_line_data.warehouse_id
        ).first()

        if not stock or float(stock.quantity_on_hand or 0) < item_line_data.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for item {item.item_number} in warehouse"
            )

        # Calculate values
        unit_cost = float(stock.average_cost or item.unit_cost or 0)
        total_cost = item_line_data.quantity * unit_cost
        salvage_value = float(item_line_data.salvage_value or 0)
        gain_loss = salvage_value - total_cost

        item_line = DisposalItemLine(
            disposal_id=disposal.id,
            line_number=i + 1,
            item_id=item.id,
            warehouse_id=item_line_data.warehouse_id,
            quantity=item_line_data.quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            salvage_value=salvage_value,
            gain_loss=gain_loss,
            notes=item_line_data.notes,
        )
        db.add(item_line)

    db.commit()
    db.refresh(disposal)

    # Reload with relationships
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
        joinedload(Disposal.journal_entry),
    ).filter(Disposal.id == disposal.id).first()

    return disposal_to_response(disposal)


# Helper endpoints for getting available assets - MUST be before {disposal_id} routes
@router.get("/disposals/available-tools", response_model=List[dict])
async def get_available_tools(
    search: Optional[str] = Query(None, description="Search by tool number or name"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get tools available for disposal (not already disposed)"""
    query = db.query(Tool).options(
        joinedload(Tool.category),
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse),
    ).filter(
        Tool.company_id == current_user.company_id,
        Tool.is_disposed == False,
        Tool.is_active == True,
        Tool.status.notin_(["retired", "lost"])
    )

    if search:
        query = query.filter(
            or_(
                Tool.tool_number.ilike(f"%{search}%"),
                Tool.name.ilike(f"%{search}%"),
                Tool.serial_number.ilike(f"%{search}%")
            )
        )

    if category_id:
        query = query.filter(Tool.category_id == category_id)

    tools = query.order_by(Tool.tool_number).limit(100).all()

    result = []
    for tool in tools:
        result.append({
            "id": tool.id,
            "tool_number": tool.tool_number,
            "name": tool.name,
            "serial_number": tool.serial_number,
            "category_name": tool.category.name if tool.category else None,
            "asset_type": tool.category.asset_type if tool.category else None,
            "purchase_cost": float(tool.purchase_cost or 0),
            "accumulated_depreciation": float(tool.accumulated_depreciation or 0),
            "net_book_value": float(tool.purchase_cost or 0) - float(tool.accumulated_depreciation or 0),
            "status": tool.status,
            "current_location": get_tool_current_location(tool),
        })

    return result


@router.get("/disposals/available-items", response_model=List[dict])
async def get_available_items(
    search: Optional[str] = Query(None, description="Search by item number or name"),
    warehouse_id: Optional[int] = Query(None, description="Filter by warehouse"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get inventory items with stock available for disposal"""
    query = db.query(
        ItemStock.item_id,
        ItemStock.warehouse_id,
        ItemMaster.item_number,
        ItemMaster.description.label("item_name"),
        Warehouse.name.label("warehouse_name"),
        ItemStock.quantity_on_hand,
        ItemStock.average_cost
    ).join(
        ItemMaster, ItemStock.item_id == ItemMaster.id
    ).join(
        Warehouse, ItemStock.warehouse_id == Warehouse.id
    ).filter(
        ItemMaster.company_id == current_user.company_id,
        ItemStock.quantity_on_hand > 0
    )

    if search:
        query = query.filter(
            or_(
                ItemMaster.item_number.ilike(f"%{search}%"),
                ItemMaster.description.ilike(f"%{search}%")
            )
        )

    if warehouse_id:
        query = query.filter(ItemStock.warehouse_id == warehouse_id)

    items = query.order_by(ItemMaster.item_number).limit(100).all()

    result = []
    for item in items:
        avg_cost = float(item.average_cost or 0)
        qty = float(item.quantity_on_hand or 0)
        result.append({
            "item_id": item.item_id,
            "item_number": item.item_number,
            "item_name": item.item_name,
            "warehouse_id": item.warehouse_id,
            "warehouse_name": item.warehouse_name,
            "quantity_on_hand": qty,
            "average_cost": avg_cost,
            "total_value": qty * avg_cost,
        })

    return result


@router.get("/disposals/{disposal_id}", response_model=dict)
async def get_disposal(
    disposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get disposal by ID"""
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
        joinedload(Disposal.journal_entry),
    ).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    return disposal_to_response(disposal)


@router.put("/disposals/{disposal_id}", response_model=dict)
async def update_disposal(
    disposal_id: int,
    data: DisposalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update disposal (draft only)"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update draft disposals"
        )

    # Update fields
    if data.disposal_date is not None:
        disposal.disposal_date = data.disposal_date
    if data.reason is not None:
        disposal.reason = data.reason
    if data.method is not None:
        disposal.method = data.method
    if data.salvage_received is not None:
        disposal.salvage_received = data.salvage_received
    if data.salvage_reference is not None:
        disposal.salvage_reference = data.salvage_reference
    if data.notes is not None:
        disposal.notes = data.notes

    db.commit()
    db.refresh(disposal)

    # Reload with relationships
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
        joinedload(Disposal.journal_entry),
    ).filter(Disposal.id == disposal.id).first()

    return disposal_to_response(disposal)


@router.delete("/disposals/{disposal_id}")
async def delete_disposal(
    disposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete disposal (draft only)"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete draft disposals"
        )

    db.delete(disposal)
    db.commit()

    return {"message": "Disposal deleted successfully"}


# =============================================================================
# DISPOSAL WORKFLOW ENDPOINTS
# =============================================================================

@router.post("/disposals/{disposal_id}/approve", response_model=dict)
async def approve_disposal(
    disposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Approve a disposal"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only approve draft disposals"
        )

    # Check that disposal has at least one line
    if not disposal.tool_lines and not disposal.item_lines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disposal must have at least one tool or item line"
        )

    disposal.status = "approved"
    disposal.approved_by = current_user.id
    disposal.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(disposal)

    # Reload with relationships
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
        joinedload(Disposal.journal_entry),
    ).filter(Disposal.id == disposal.id).first()

    return disposal_to_response(disposal)


@router.post("/disposals/{disposal_id}/post", response_model=dict)
async def post_disposal(
    disposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Post a disposal - creates journal entry and updates tool/inventory records.

    For Tools:
    - DR: Accumulated Depreciation (1290)
    - DR: Loss on Disposal (5340) or CR: Gain on Disposal (5341)
    - DR: Cash (1110) if salvage received
    - CR: Tools & Equipment (1210)

    For Items:
    - DR: Inventory Write-off (5350)
    - DR: Cash (1110) if salvage received
    - CR: Inventory (1140)
    """
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool).joinedload(Tool.category),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
    ).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only post approved disposals"
        )

    # Get fiscal period
    fiscal_period = db.query(FiscalPeriod).filter(
        FiscalPeriod.company_id == current_user.company_id,
        FiscalPeriod.start_date <= disposal.disposal_date,
        FiscalPeriod.end_date >= disposal.disposal_date,
        FiscalPeriod.status == "open"
    ).first()

    if not fiscal_period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No open fiscal period found for the disposal date"
        )

    # Get required accounts
    def get_account_by_code(code: str) -> Account:
        account = db.query(Account).filter(
            Account.company_id == current_user.company_id,
            Account.code == code,
            Account.is_active == True
        ).first()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Account {code} not found. Please set up the chart of accounts."
            )
        return account

    # Check if any salvage exists on lines
    has_tool_salvage = any(float(tl.salvage_value or 0) > 0 for tl in disposal.tool_lines)
    has_item_salvage = any(float(il.salvage_value or 0) > 0 for il in disposal.item_lines)
    has_any_salvage = has_tool_salvage or has_item_salvage

    # Account codes
    cash_account = get_account_by_code("1110") if has_any_salvage else None
    tools_account = get_account_by_code("1210") if disposal.tool_lines else None
    accum_depr_account = get_account_by_code("1290") if disposal.tool_lines else None
    inventory_account = get_account_by_code("1140") if disposal.item_lines else None

    # Get or create disposal loss/gain accounts
    loss_account = db.query(Account).filter(
        Account.company_id == current_user.company_id,
        Account.code == "5340"
    ).first()

    gain_account = db.query(Account).filter(
        Account.company_id == current_user.company_id,
        Account.code == "5341"
    ).first()

    inventory_writeoff_account = db.query(Account).filter(
        Account.company_id == current_user.company_id,
        Account.code == "5350"
    ).first()

    # Create accounts if they don't exist
    if not loss_account and disposal.tool_lines:
        # Get parent account (5300 series)
        parent = db.query(Account).filter(
            Account.company_id == current_user.company_id,
            Account.code == "5300"
        ).first()
        # Get expense account type
        expense_type = db.query(AccountType).filter(AccountType.name == "Expenses").first()
        loss_account = Account(
            company_id=current_user.company_id,
            code="5340",
            name="Loss on Asset Disposal",
            account_type_id=parent.account_type_id if parent else (expense_type.id if expense_type else None),
            parent_id=parent.id if parent else None,
            is_header=False,
            is_active=True,
            created_by=current_user.id
        )
        db.add(loss_account)
        db.flush()

    if not gain_account and disposal.tool_lines:
        parent = db.query(Account).filter(
            Account.company_id == current_user.company_id,
            Account.code == "5300"
        ).first()
        expense_type = db.query(AccountType).filter(AccountType.name == "Expenses").first()
        gain_account = Account(
            company_id=current_user.company_id,
            code="5341",
            name="Gain on Asset Disposal",
            account_type_id=parent.account_type_id if parent else (expense_type.id if expense_type else None),
            parent_id=parent.id if parent else None,
            is_header=False,
            is_active=True,
            created_by=current_user.id
        )
        db.add(gain_account)
        db.flush()

    if not inventory_writeoff_account and disposal.item_lines:
        parent = db.query(Account).filter(
            Account.company_id == current_user.company_id,
            Account.code == "5300"
        ).first()
        expense_type = db.query(AccountType).filter(AccountType.name == "Expenses").first()
        inventory_writeoff_account = Account(
            company_id=current_user.company_id,
            code="5350",
            name="Inventory Write-off Loss",
            account_type_id=parent.account_type_id if parent else (expense_type.id if expense_type else None),
            parent_id=parent.id if parent else None,
            is_header=False,
            is_active=True,
            created_by=current_user.id
        )
        db.add(inventory_writeoff_account)
        db.flush()

    # Create journal entry
    entry_number = generate_journal_entry_number(db, current_user.company_id)

    journal_entry = JournalEntry(
        company_id=current_user.company_id,
        entry_number=entry_number,
        entry_date=disposal.disposal_date,
        description=f"Asset/Inventory Disposal - {disposal.disposal_number} ({disposal.reason})",
        reference=disposal.disposal_number,
        source_type="disposal",
        source_id=disposal.id,
        source_number=disposal.disposal_number,
        fiscal_period_id=fiscal_period.id,
        status="posted",
        is_auto_generated=True,
        posted_at=datetime.utcnow(),
        posted_by=current_user.id,
        created_by=current_user.id,
    )
    db.add(journal_entry)
    db.flush()

    line_number = 0
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    # Determine business_unit_id for the disposal
    # For items, we'll use the warehouse's BU; for tools, use their warehouse or default
    # Get from first item line's warehouse if available, otherwise default
    first_warehouse_id = None
    if disposal.item_lines:
        first_warehouse_id = disposal.item_lines[0].warehouse_id
    elif disposal.tool_lines:
        for tl in disposal.tool_lines:
            if tl.tool and tl.tool.assigned_warehouse_id:
                first_warehouse_id = tl.tool.assigned_warehouse_id
                break

    business_unit_id = get_business_unit_for_disposal(db, current_user.company_id, first_warehouse_id)

    # Process tool lines
    total_tool_accum_depr = Decimal("0")
    total_tool_original_cost = Decimal("0")
    total_tool_loss = Decimal("0")
    total_tool_gain = Decimal("0")
    total_tool_salvage = Decimal("0")

    for tool_line in disposal.tool_lines:
        tool = tool_line.tool

        # Accumulate for journal entry
        total_tool_accum_depr += Decimal(str(tool_line.accumulated_depreciation or 0))
        total_tool_original_cost += Decimal(str(tool_line.original_cost or 0))
        total_tool_salvage += Decimal(str(tool_line.salvage_value or 0))

        gain_loss = Decimal(str(tool_line.gain_loss or 0))
        if gain_loss < 0:
            total_tool_loss += abs(gain_loss)
        else:
            total_tool_gain += gain_loss

        # Update tool record
        tool.is_disposed = True
        tool.disposal_id = disposal.id
        tool.disposal_date = disposal.disposal_date
        tool.status = "retired"
        tool.is_active = False

    # Create journal lines for tools
    if disposal.tool_lines:
        # DR: Accumulated Depreciation
        if total_tool_accum_depr > 0:
            line_number += 1
            db.add(JournalEntryLine(
                journal_entry_id=journal_entry.id,
                line_number=line_number,
                account_id=accum_depr_account.id,
                debit=float(total_tool_accum_depr),
                credit=0,
                description=f"Accumulated depreciation removed - {len(disposal.tool_lines)} tools",
                business_unit_id=business_unit_id
            ))
            total_debit += total_tool_accum_depr

        # DR: Loss on Disposal (if any)
        if total_tool_loss > 0:
            line_number += 1
            db.add(JournalEntryLine(
                journal_entry_id=journal_entry.id,
                line_number=line_number,
                account_id=loss_account.id,
                debit=float(total_tool_loss),
                credit=0,
                description=f"Loss on tool disposal - {disposal.reason}",
                business_unit_id=business_unit_id
            ))
            total_debit += total_tool_loss

        # CR: Gain on Disposal (if any)
        if total_tool_gain > 0:
            line_number += 1
            db.add(JournalEntryLine(
                journal_entry_id=journal_entry.id,
                line_number=line_number,
                account_id=gain_account.id,
                debit=0,
                credit=float(total_tool_gain),
                description=f"Gain on tool disposal",
                business_unit_id=business_unit_id
            ))
            total_credit += total_tool_gain

        # DR: Cash for tool salvage (if any)
        if total_tool_salvage > 0 and cash_account:
            line_number += 1
            db.add(JournalEntryLine(
                journal_entry_id=journal_entry.id,
                line_number=line_number,
                account_id=cash_account.id,
                debit=float(total_tool_salvage),
                credit=0,
                description=f"Salvage received for tools",
                business_unit_id=business_unit_id
            ))
            total_debit += total_tool_salvage

        # CR: Tools & Equipment (original cost)
        line_number += 1
        db.add(JournalEntryLine(
            journal_entry_id=journal_entry.id,
            line_number=line_number,
            account_id=tools_account.id,
            debit=0,
            credit=float(total_tool_original_cost),
            description=f"Tools removed - {len(disposal.tool_lines)} tools",
            business_unit_id=business_unit_id
        ))
        total_credit += total_tool_original_cost

    # Process item lines
    total_item_cost = Decimal("0")
    total_item_loss = Decimal("0")
    total_item_salvage = Decimal("0")

    for item_line in disposal.item_lines:
        # Update item stock
        stock = db.query(ItemStock).filter(
            ItemStock.item_id == item_line.item_id,
            ItemStock.warehouse_id == item_line.warehouse_id
        ).first()

        if stock:
            stock.quantity_on_hand = float(Decimal(str(stock.quantity_on_hand or 0)) - Decimal(str(item_line.quantity)))

        # Create item ledger entry
        # Generate transaction number for ledger
        ledger_tx_number = f"DSP-{disposal.disposal_number}-{item_line.id}"

        # Get business_unit_id for this specific warehouse
        item_bu_id = get_business_unit_for_disposal(db, current_user.company_id, item_line.warehouse_id)

        ledger_entry = ItemLedger(
            company_id=current_user.company_id,
            item_id=item_line.item_id,
            from_warehouse_id=item_line.warehouse_id,  # Disposed FROM this warehouse
            transaction_number=ledger_tx_number,
            transaction_type="DISPOSAL",
            transaction_date=disposal.disposal_date,
            quantity=-float(item_line.quantity),
            unit_cost=float(item_line.unit_cost),
            total_cost=-float(item_line.total_cost),
            notes=f"Disposal {disposal.disposal_number}: {disposal.reason} - {item_line.notes or ''}",
            created_by=current_user.id,
            business_unit_id=item_bu_id
        )
        db.add(ledger_entry)

        # Accumulate for journal entry
        total_item_cost += Decimal(str(item_line.total_cost or 0))
        total_item_salvage += Decimal(str(item_line.salvage_value or 0))
        loss = Decimal(str(item_line.total_cost or 0)) - Decimal(str(item_line.salvage_value or 0))
        total_item_loss += loss

    # Create journal lines for items
    if disposal.item_lines:
        # DR: Inventory Write-off Loss
        if total_item_loss > 0:
            line_number += 1
            db.add(JournalEntryLine(
                journal_entry_id=journal_entry.id,
                line_number=line_number,
                account_id=inventory_writeoff_account.id,
                debit=float(total_item_loss),
                credit=0,
                description=f"Inventory write-off - {len(disposal.item_lines)} items",
                business_unit_id=business_unit_id
            ))
            total_debit += total_item_loss

        # DR: Cash for item salvage (if any)
        if total_item_salvage > 0 and cash_account:
            line_number += 1
            db.add(JournalEntryLine(
                journal_entry_id=journal_entry.id,
                line_number=line_number,
                account_id=cash_account.id,
                debit=float(total_item_salvage),
                credit=0,
                description=f"Salvage received for inventory items",
                business_unit_id=business_unit_id
            ))
            total_debit += total_item_salvage

        # CR: Inventory
        line_number += 1
        db.add(JournalEntryLine(
            journal_entry_id=journal_entry.id,
            line_number=line_number,
            account_id=inventory_account.id,
            debit=0,
            credit=float(total_item_cost),
            description=f"Inventory disposed - {len(disposal.item_lines)} items",
            business_unit_id=business_unit_id
        ))
        total_credit += total_item_cost

    # Update journal entry totals
    journal_entry.total_debit = float(total_debit)
    journal_entry.total_credit = float(total_credit)

    # Update disposal status
    disposal.status = "posted"
    disposal.posted_by = current_user.id
    disposal.posted_at = datetime.utcnow()
    disposal.journal_entry_id = journal_entry.id

    db.commit()

    # Reload with relationships
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
        joinedload(Disposal.journal_entry),
    ).filter(Disposal.id == disposal.id).first()

    return disposal_to_response(disposal)


@router.post("/disposals/{disposal_id}/cancel", response_model=dict)
async def cancel_disposal(
    disposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel a disposal (draft or approved only)"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status not in ["draft", "approved"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only cancel draft or approved disposals"
        )

    disposal.status = "cancelled"

    db.commit()
    db.refresh(disposal)

    # Reload with relationships
    disposal = db.query(Disposal).options(
        joinedload(Disposal.tool_lines).joinedload(DisposalToolLine.tool),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.item),
        joinedload(Disposal.item_lines).joinedload(DisposalItemLine.warehouse),
        joinedload(Disposal.creator),
        joinedload(Disposal.journal_entry),
    ).filter(Disposal.id == disposal.id).first()

    return disposal_to_response(disposal)


# =============================================================================
# DISPOSAL LINE MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/disposals/{disposal_id}/tool-lines", response_model=dict)
async def add_tool_line(
    disposal_id: int,
    data: DisposalToolLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a tool line to a disposal"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only add lines to draft disposals"
        )

    # Check tool
    tool = db.query(Tool).filter(
        Tool.id == data.tool_id,
        Tool.company_id == current_user.company_id,
        Tool.is_disposed == False,
        Tool.is_active == True
    ).first()

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tool not found or already disposed"
        )

    # Check tool not already in this disposal
    existing = db.query(DisposalToolLine).filter(
        DisposalToolLine.disposal_id == disposal_id,
        DisposalToolLine.tool_id == data.tool_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tool already added to this disposal"
        )

    # Get next line number
    max_line = db.query(func.max(DisposalToolLine.line_number)).filter(
        DisposalToolLine.disposal_id == disposal_id
    ).scalar() or 0

    # Calculate values
    original_cost = float(tool.purchase_cost or 0)
    accumulated_depreciation = float(tool.accumulated_depreciation or 0)
    net_book_value = original_cost - accumulated_depreciation
    salvage_value = float(data.salvage_value or 0)
    gain_loss = salvage_value - net_book_value

    tool_line = DisposalToolLine(
        disposal_id=disposal_id,
        line_number=max_line + 1,
        tool_id=tool.id,
        original_cost=original_cost,
        accumulated_depreciation=accumulated_depreciation,
        net_book_value=net_book_value,
        salvage_value=salvage_value,
        gain_loss=gain_loss,
        notes=data.notes,
    )
    db.add(tool_line)
    db.commit()
    db.refresh(tool_line)

    # Load tool relationship
    tool_line = db.query(DisposalToolLine).options(
        joinedload(DisposalToolLine.tool)
    ).filter(DisposalToolLine.id == tool_line.id).first()

    return tool_line_to_response(tool_line)


@router.put("/disposals/{disposal_id}/tool-lines/{line_id}", response_model=dict)
async def update_tool_line(
    disposal_id: int,
    line_id: int,
    data: DisposalToolLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a tool line"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update lines on draft disposals"
        )

    tool_line = db.query(DisposalToolLine).filter(
        DisposalToolLine.id == line_id,
        DisposalToolLine.disposal_id == disposal_id
    ).first()

    if not tool_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool line not found"
        )

    if data.salvage_value is not None:
        tool_line.salvage_value = data.salvage_value
        tool_line.gain_loss = data.salvage_value - float(tool_line.net_book_value or 0)
    if data.notes is not None:
        tool_line.notes = data.notes

    db.commit()
    db.refresh(tool_line)

    # Load tool relationship
    tool_line = db.query(DisposalToolLine).options(
        joinedload(DisposalToolLine.tool)
    ).filter(DisposalToolLine.id == tool_line.id).first()

    return tool_line_to_response(tool_line)


@router.delete("/disposals/{disposal_id}/tool-lines/{line_id}")
async def delete_tool_line(
    disposal_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a tool line"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete lines from draft disposals"
        )

    tool_line = db.query(DisposalToolLine).filter(
        DisposalToolLine.id == line_id,
        DisposalToolLine.disposal_id == disposal_id
    ).first()

    if not tool_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool line not found"
        )

    db.delete(tool_line)
    db.commit()

    return {"message": "Tool line deleted successfully"}


@router.post("/disposals/{disposal_id}/item-lines", response_model=dict)
async def add_item_line(
    disposal_id: int,
    data: DisposalItemLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add an item line to a disposal"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only add lines to draft disposals"
        )

    # Check item
    item = db.query(ItemMaster).filter(
        ItemMaster.id == data.item_id,
        ItemMaster.company_id == current_user.company_id
    ).first()

    if not item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item not found"
        )

    # Check stock
    stock = db.query(ItemStock).filter(
        ItemStock.item_id == data.item_id,
        ItemStock.warehouse_id == data.warehouse_id
    ).first()

    if not stock or float(stock.quantity_on_hand or 0) < data.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient stock in warehouse"
        )

    # Get next line number
    max_line = db.query(func.max(DisposalItemLine.line_number)).filter(
        DisposalItemLine.disposal_id == disposal_id
    ).scalar() or 0

    # Calculate values
    unit_cost = float(stock.average_cost or item.unit_cost or 0)
    total_cost = data.quantity * unit_cost
    salvage_value = float(data.salvage_value or 0)
    gain_loss = salvage_value - total_cost

    item_line = DisposalItemLine(
        disposal_id=disposal_id,
        line_number=max_line + 1,
        item_id=item.id,
        warehouse_id=data.warehouse_id,
        quantity=data.quantity,
        unit_cost=unit_cost,
        total_cost=total_cost,
        salvage_value=salvage_value,
        gain_loss=gain_loss,
        notes=data.notes,
    )
    db.add(item_line)
    db.commit()
    db.refresh(item_line)

    # Load relationships
    item_line = db.query(DisposalItemLine).options(
        joinedload(DisposalItemLine.item),
        joinedload(DisposalItemLine.warehouse)
    ).filter(DisposalItemLine.id == item_line.id).first()

    return item_line_to_response(item_line)


@router.put("/disposals/{disposal_id}/item-lines/{line_id}", response_model=dict)
async def update_item_line(
    disposal_id: int,
    line_id: int,
    data: DisposalItemLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an item line"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update lines on draft disposals"
        )

    item_line = db.query(DisposalItemLine).filter(
        DisposalItemLine.id == line_id,
        DisposalItemLine.disposal_id == disposal_id
    ).first()

    if not item_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item line not found"
        )

    if data.quantity is not None:
        # Check stock
        stock = db.query(ItemStock).filter(
            ItemStock.item_id == item_line.item_id,
            ItemStock.warehouse_id == item_line.warehouse_id
        ).first()

        if not stock or float(stock.quantity_on_hand or 0) < data.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient stock in warehouse"
            )

        item_line.quantity = data.quantity
        item_line.total_cost = data.quantity * float(item_line.unit_cost)

    if data.salvage_value is not None:
        item_line.salvage_value = data.salvage_value

    # Recalculate gain/loss
    item_line.gain_loss = float(item_line.salvage_value or 0) - float(item_line.total_cost or 0)

    if data.notes is not None:
        item_line.notes = data.notes

    db.commit()
    db.refresh(item_line)

    # Load relationships
    item_line = db.query(DisposalItemLine).options(
        joinedload(DisposalItemLine.item),
        joinedload(DisposalItemLine.warehouse)
    ).filter(DisposalItemLine.id == item_line.id).first()

    return item_line_to_response(item_line)


@router.delete("/disposals/{disposal_id}/item-lines/{line_id}")
async def delete_item_line(
    disposal_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an item line"""
    disposal = db.query(Disposal).filter(
        Disposal.id == disposal_id,
        Disposal.company_id == current_user.company_id
    ).first()

    if not disposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disposal not found"
        )

    if disposal.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete lines from draft disposals"
        )

    item_line = db.query(DisposalItemLine).filter(
        DisposalItemLine.id == line_id,
        DisposalItemLine.disposal_id == disposal_id
    ).first()

    if not item_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item line not found"
        )

    db.delete(item_line)
    db.commit()

    return {"message": "Item line deleted successfully"}
