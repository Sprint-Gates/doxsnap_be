"""
Tools Management API endpoints.

Features:
- Tool Categories (fixed assets vs consumables)
- Tools CRUD with single-assignment allocation (Site OR Technician OR Warehouse)
- Tool Purchases with dedicated workflow (separate from PO system)
- Depreciation calculation and posting
- Allocation history tracking
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, desc
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
import logging

from app.database import get_db
from app.models import (
    User, Vendor, Site, Technician, Warehouse, Account, Client,
    ToolCategory, Tool, ToolPurchase, ToolPurchaseLine, ToolAllocationHistory,
    JournalEntry, JournalEntryLine, FiscalPeriod
)
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_tool_number(db: Session, company_id: int) -> str:
    """Generate unique tool number: TL-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"TL-{year}-"

    last_tool = db.query(Tool).filter(
        Tool.company_id == company_id,
        Tool.tool_number.like(f"{prefix}%")
    ).order_by(Tool.id.desc()).first()

    if last_tool:
        try:
            last_num = int(last_tool.tool_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def generate_purchase_number(db: Session, company_id: int) -> str:
    """Generate unique tool purchase number: TP-YYYY-NNNNN"""
    year = datetime.now().year
    prefix = f"TP-{year}-"

    last_purchase = db.query(ToolPurchase).filter(
        ToolPurchase.company_id == company_id,
        ToolPurchase.purchase_number.like(f"{prefix}%")
    ).order_by(ToolPurchase.id.desc()).first()

    if last_purchase:
        try:
            last_num = int(last_purchase.purchase_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def validate_single_assignment(
    assigned_site_id: Optional[int],
    assigned_technician_id: Optional[int],
    assigned_warehouse_id: Optional[int]
) -> bool:
    """Ensure only ONE assignment is set at a time"""
    assignments = [
        assigned_site_id is not None,
        assigned_technician_id is not None,
        assigned_warehouse_id is not None
    ]
    return sum(assignments) <= 1


def tool_to_response(tool: Tool, include_category: bool = True) -> dict:
    """Convert Tool to response dict"""
    response = {
        "id": tool.id,
        "company_id": tool.company_id,
        "tool_number": tool.tool_number,
        "name": tool.name,
        "serial_number": tool.serial_number,
        "barcode": tool.barcode,
        "manufacturer": tool.manufacturer,
        "model": tool.model,
        "specifications": tool.specifications,
        "photo_url": tool.photo_url,
        "purchase_id": tool.purchase_id,
        "purchase_date": tool.purchase_date,
        "purchase_cost": float(tool.purchase_cost) if tool.purchase_cost else None,
        "vendor_id": tool.vendor_id,
        "vendor_name": tool.vendor.name if tool.vendor else None,
        "capitalization_date": tool.capitalization_date,
        "useful_life_months": tool.useful_life_months,
        "salvage_value": float(tool.salvage_value) if tool.salvage_value else None,
        "accumulated_depreciation": float(tool.accumulated_depreciation or 0),
        "net_book_value": float(tool.net_book_value) if tool.net_book_value else None,
        "last_depreciation_date": tool.last_depreciation_date,
        "warranty_expiry": tool.warranty_expiry,
        "warranty_notes": tool.warranty_notes,
        "status": tool.status,
        "condition": tool.condition,
        "assigned_site_id": tool.assigned_site_id,
        "assigned_site_name": tool.assigned_site.name if tool.assigned_site else None,
        "assigned_technician_id": tool.assigned_technician_id,
        "assigned_technician_name": tool.assigned_technician.name if tool.assigned_technician else None,
        "assigned_warehouse_id": tool.assigned_warehouse_id,
        "assigned_warehouse_name": tool.assigned_warehouse.name if tool.assigned_warehouse else None,
        "assigned_at": tool.assigned_at,
        "notes": tool.notes,
        "is_active": tool.is_active,
        "created_at": tool.created_at,
        "updated_at": tool.updated_at
    }

    if include_category and tool.category:
        response["category"] = {
            "id": tool.category.id,
            "name": tool.category.name,
            "code": tool.category.code,
            "asset_type": tool.category.asset_type
        }
    else:
        response["category_id"] = tool.category_id

    return response


def purchase_to_response(purchase: ToolPurchase, include_lines: bool = True) -> dict:
    """Convert ToolPurchase to response dict"""
    response = {
        "id": purchase.id,
        "company_id": purchase.company_id,
        "purchase_number": purchase.purchase_number,
        "purchase_date": purchase.purchase_date,
        "vendor_id": purchase.vendor_id,
        "vendor_name": purchase.vendor.name if purchase.vendor else None,
        "currency": purchase.currency,
        "subtotal": float(purchase.subtotal or 0),
        "tax_amount": float(purchase.tax_amount or 0),
        "total_amount": float(purchase.total_amount or 0),
        "initial_warehouse_id": purchase.initial_warehouse_id,
        "initial_warehouse_name": purchase.initial_warehouse.name if purchase.initial_warehouse else None,
        "status": purchase.status,
        "approved_by": purchase.approved_by,
        "approved_by_name": purchase.approver.name if purchase.approver else None,
        "approved_at": purchase.approved_at,
        "received_by": purchase.received_by,
        "received_by_name": purchase.receiver.name if purchase.receiver else None,
        "received_at": purchase.received_at,
        "reference": purchase.reference,
        "notes": purchase.notes,
        "journal_entry_id": purchase.journal_entry_id,
        "created_at": purchase.created_at,
        "updated_at": purchase.updated_at,
        "lines": []
    }

    if include_lines and purchase.lines:
        for line in purchase.lines:
            line_data = {
                "id": line.id,
                "line_number": line.line_number,
                "category_id": line.category_id,
                "category_name": line.category.name if line.category else None,
                "asset_type": line.category.asset_type if line.category else None,
                "description": line.description,
                "manufacturer": line.manufacturer,
                "model": line.model,
                "quantity": line.quantity,
                "unit_cost": float(line.unit_cost or 0),
                "total_cost": float(line.total_cost or 0),
                "serial_numbers": line.serial_numbers,
                "notes": line.notes
            }
            response["lines"].append(line_data)

    return response


# =============================================================================
# TOOL CATEGORY ENDPOINTS
# =============================================================================

@router.get("/tool-categories", response_model=List[dict])
async def list_tool_categories(
    asset_type: Optional[str] = None,
    is_active: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tool categories"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    query = db.query(ToolCategory).filter(
        ToolCategory.company_id == current_user.company_id
    )

    if is_active is not None:
        query = query.filter(ToolCategory.is_active == is_active)
    if asset_type:
        query = query.filter(ToolCategory.asset_type == asset_type)

    categories = query.order_by(ToolCategory.name).all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "asset_type": c.asset_type,
            "useful_life_months": c.useful_life_months,
            "depreciation_method": c.depreciation_method,
            "salvage_value_percentage": float(c.salvage_value_percentage) if c.salvage_value_percentage else None,
            "asset_account_id": c.asset_account_id,
            "expense_account_id": c.expense_account_id,
            "accumulated_depreciation_account_id": c.accumulated_depreciation_account_id,
            "depreciation_expense_account_id": c.depreciation_expense_account_id,
            "is_active": c.is_active,
            "created_at": c.created_at
        }
        for c in categories
    ]


@router.post("/tool-categories", response_model=dict)
async def create_tool_category(
    name: str,
    asset_type: str,
    code: Optional[str] = None,
    useful_life_months: Optional[int] = None,
    depreciation_method: Optional[str] = "straight_line",
    salvage_value_percentage: Optional[float] = None,
    asset_account_id: Optional[int] = None,
    expense_account_id: Optional[int] = None,
    accumulated_depreciation_account_id: Optional[int] = None,
    depreciation_expense_account_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new tool category"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    if asset_type not in ["fixed_asset", "consumable"]:
        raise HTTPException(status_code=400, detail="asset_type must be 'fixed_asset' or 'consumable'")

    # Check for duplicate name
    existing = db.query(ToolCategory).filter(
        ToolCategory.company_id == current_user.company_id,
        ToolCategory.name == name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="A category with this name already exists")

    category = ToolCategory(
        company_id=current_user.company_id,
        name=name,
        code=code,
        asset_type=asset_type,
        useful_life_months=useful_life_months,
        depreciation_method=depreciation_method,
        salvage_value_percentage=salvage_value_percentage,
        asset_account_id=asset_account_id,
        expense_account_id=expense_account_id,
        accumulated_depreciation_account_id=accumulated_depreciation_account_id,
        depreciation_expense_account_id=depreciation_expense_account_id
    )

    db.add(category)
    db.commit()
    db.refresh(category)

    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "asset_type": category.asset_type,
        "useful_life_months": category.useful_life_months,
        "depreciation_method": category.depreciation_method,
        "salvage_value_percentage": float(category.salvage_value_percentage) if category.salvage_value_percentage else None,
        "is_active": category.is_active,
        "created_at": category.created_at
    }


@router.get("/tool-categories/{category_id}", response_model=dict)
async def get_tool_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific tool category"""
    category = db.query(ToolCategory).filter(
        ToolCategory.id == category_id,
        ToolCategory.company_id == current_user.company_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Tool category not found")

    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "asset_type": category.asset_type,
        "useful_life_months": category.useful_life_months,
        "depreciation_method": category.depreciation_method,
        "salvage_value_percentage": float(category.salvage_value_percentage) if category.salvage_value_percentage else None,
        "asset_account_id": category.asset_account_id,
        "expense_account_id": category.expense_account_id,
        "accumulated_depreciation_account_id": category.accumulated_depreciation_account_id,
        "depreciation_expense_account_id": category.depreciation_expense_account_id,
        "is_active": category.is_active,
        "created_at": category.created_at,
        "updated_at": category.updated_at
    }


@router.put("/tool-categories/{category_id}", response_model=dict)
async def update_tool_category(
    category_id: int,
    name: Optional[str] = None,
    code: Optional[str] = None,
    asset_type: Optional[str] = None,
    useful_life_months: Optional[int] = None,
    depreciation_method: Optional[str] = None,
    salvage_value_percentage: Optional[float] = None,
    asset_account_id: Optional[int] = None,
    expense_account_id: Optional[int] = None,
    accumulated_depreciation_account_id: Optional[int] = None,
    depreciation_expense_account_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a tool category"""
    category = db.query(ToolCategory).filter(
        ToolCategory.id == category_id,
        ToolCategory.company_id == current_user.company_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Tool category not found")

    if name is not None:
        category.name = name
    if code is not None:
        category.code = code
    if asset_type is not None:
        if asset_type not in ["fixed_asset", "consumable"]:
            raise HTTPException(status_code=400, detail="asset_type must be 'fixed_asset' or 'consumable'")
        category.asset_type = asset_type
    if useful_life_months is not None:
        category.useful_life_months = useful_life_months
    if depreciation_method is not None:
        category.depreciation_method = depreciation_method
    if salvage_value_percentage is not None:
        category.salvage_value_percentage = salvage_value_percentage
    if asset_account_id is not None:
        category.asset_account_id = asset_account_id
    if expense_account_id is not None:
        category.expense_account_id = expense_account_id
    if accumulated_depreciation_account_id is not None:
        category.accumulated_depreciation_account_id = accumulated_depreciation_account_id
    if depreciation_expense_account_id is not None:
        category.depreciation_expense_account_id = depreciation_expense_account_id
    if is_active is not None:
        category.is_active = is_active

    category.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(category)

    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "asset_type": category.asset_type,
        "useful_life_months": category.useful_life_months,
        "depreciation_method": category.depreciation_method,
        "salvage_value_percentage": float(category.salvage_value_percentage) if category.salvage_value_percentage else None,
        "is_active": category.is_active,
        "updated_at": category.updated_at
    }


@router.delete("/tool-categories/{category_id}")
async def delete_tool_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a tool category"""
    category = db.query(ToolCategory).filter(
        ToolCategory.id == category_id,
        ToolCategory.company_id == current_user.company_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Tool category not found")

    # Check if any tools are using this category
    tool_count = db.query(Tool).filter(
        Tool.category_id == category_id,
        Tool.is_active == True
    ).count()

    if tool_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete category with {tool_count} active tools. Deactivate instead."
        )

    category.is_active = False
    category.updated_at = datetime.utcnow()

    db.commit()

    return {"message": "Tool category deactivated successfully"}


# =============================================================================
# TOOL ENDPOINTS
# =============================================================================

@router.get("/tools", response_model=List[dict])
async def list_tools(
    category_id: Optional[int] = None,
    status: Optional[str] = None,
    condition: Optional[str] = None,
    assigned_site_id: Optional[int] = None,
    assigned_technician_id: Optional[int] = None,
    assigned_warehouse_id: Optional[int] = None,
    is_active: bool = True,
    search: Optional[str] = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List tools with optional filters"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    query = db.query(Tool).options(
        joinedload(Tool.category),
        joinedload(Tool.vendor),
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse)
    ).filter(Tool.company_id == current_user.company_id)

    if is_active is not None:
        query = query.filter(Tool.is_active == is_active)
    if category_id:
        query = query.filter(Tool.category_id == category_id)
    if status:
        query = query.filter(Tool.status == status)
    if condition:
        query = query.filter(Tool.condition == condition)
    if assigned_site_id:
        query = query.filter(Tool.assigned_site_id == assigned_site_id)
    if assigned_technician_id:
        query = query.filter(Tool.assigned_technician_id == assigned_technician_id)
    if assigned_warehouse_id:
        query = query.filter(Tool.assigned_warehouse_id == assigned_warehouse_id)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Tool.name.ilike(search_filter)) |
            (Tool.tool_number.ilike(search_filter)) |
            (Tool.serial_number.ilike(search_filter)) |
            (Tool.barcode.ilike(search_filter))
        )

    tools = query.order_by(Tool.created_at.desc()).offset(offset).limit(limit).all()

    return [tool_to_response(tool) for tool in tools]


@router.post("/tools", response_model=dict)
async def create_tool(
    category_id: int,
    name: str,
    serial_number: Optional[str] = None,
    barcode: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    specifications: Optional[str] = None,
    photo_url: Optional[str] = None,
    purchase_date: Optional[date] = None,
    purchase_cost: Optional[float] = None,
    vendor_id: Optional[int] = None,
    useful_life_months: Optional[int] = None,
    salvage_value: Optional[float] = None,
    warranty_expiry: Optional[date] = None,
    warranty_notes: Optional[str] = None,
    status: str = "available",
    condition: str = "good",
    assigned_site_id: Optional[int] = None,
    assigned_technician_id: Optional[int] = None,
    assigned_warehouse_id: Optional[int] = None,
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new tool manually (not from purchase)"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    # Validate category
    category = db.query(ToolCategory).filter(
        ToolCategory.id == category_id,
        ToolCategory.company_id == current_user.company_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Tool category not found")

    # Validate single assignment
    if not validate_single_assignment(assigned_site_id, assigned_technician_id, assigned_warehouse_id):
        raise HTTPException(
            status_code=400,
            detail="Tool can only be assigned to ONE of: Site, Technician, or Warehouse"
        )

    # Generate tool number
    tool_number = generate_tool_number(db, current_user.company_id)

    # Use category defaults if not provided
    if useful_life_months is None and category.useful_life_months:
        useful_life_months = category.useful_life_months

    # Calculate salvage value from percentage if not provided
    if salvage_value is None and purchase_cost and category.salvage_value_percentage:
        salvage_value = float(purchase_cost) * float(category.salvage_value_percentage) / 100

    # Calculate initial net book value
    net_book_value = purchase_cost if purchase_cost else None

    tool = Tool(
        company_id=current_user.company_id,
        category_id=category_id,
        tool_number=tool_number,
        name=name,
        serial_number=serial_number,
        barcode=barcode,
        manufacturer=manufacturer,
        model=model,
        specifications=specifications,
        photo_url=photo_url,
        purchase_date=purchase_date,
        purchase_cost=purchase_cost,
        vendor_id=vendor_id,
        capitalization_date=purchase_date if category.asset_type == "fixed_asset" else None,
        useful_life_months=useful_life_months,
        salvage_value=salvage_value,
        net_book_value=net_book_value,
        warranty_expiry=warranty_expiry,
        warranty_notes=warranty_notes,
        status=status,
        condition=condition,
        assigned_site_id=assigned_site_id,
        assigned_technician_id=assigned_technician_id,
        assigned_warehouse_id=assigned_warehouse_id,
        assigned_at=datetime.utcnow() if any([assigned_site_id, assigned_technician_id, assigned_warehouse_id]) else None,
        notes=notes,
        created_by=current_user.id
    )

    db.add(tool)
    db.flush()

    # Create initial allocation history if assigned
    if any([assigned_site_id, assigned_technician_id, assigned_warehouse_id]):
        history = ToolAllocationHistory(
            tool_id=tool.id,
            transfer_date=datetime.utcnow(),
            to_site_id=assigned_site_id,
            to_technician_id=assigned_technician_id,
            to_warehouse_id=assigned_warehouse_id,
            reason="initial_assignment",
            notes="Initial assignment on tool creation",
            transferred_by=current_user.id
        )
        db.add(history)

    db.commit()
    db.refresh(tool)

    # Reload with relationships
    tool = db.query(Tool).options(
        joinedload(Tool.category),
        joinedload(Tool.vendor),
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse)
    ).filter(Tool.id == tool.id).first()

    return tool_to_response(tool)


@router.get("/tools/{tool_id}", response_model=dict)
async def get_tool(
    tool_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific tool with full details"""
    tool = db.query(Tool).options(
        joinedload(Tool.category),
        joinedload(Tool.vendor),
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse),
        joinedload(Tool.purchase)
    ).filter(
        Tool.id == tool_id,
        Tool.company_id == current_user.company_id
    ).first()

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return tool_to_response(tool)


@router.put("/tools/{tool_id}", response_model=dict)
async def update_tool(
    tool_id: int,
    name: Optional[str] = None,
    serial_number: Optional[str] = None,
    barcode: Optional[str] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    specifications: Optional[str] = None,
    photo_url: Optional[str] = None,
    useful_life_months: Optional[int] = None,
    salvage_value: Optional[float] = None,
    warranty_expiry: Optional[date] = None,
    warranty_notes: Optional[str] = None,
    status: Optional[str] = None,
    condition: Optional[str] = None,
    notes: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update tool details (not allocation - use allocate endpoint)"""
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.company_id == current_user.company_id
    ).first()

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    if name is not None:
        tool.name = name
    if serial_number is not None:
        tool.serial_number = serial_number
    if barcode is not None:
        tool.barcode = barcode
    if manufacturer is not None:
        tool.manufacturer = manufacturer
    if model is not None:
        tool.model = model
    if specifications is not None:
        tool.specifications = specifications
    if photo_url is not None:
        tool.photo_url = photo_url
    if useful_life_months is not None:
        tool.useful_life_months = useful_life_months
    if salvage_value is not None:
        tool.salvage_value = salvage_value
    if warranty_expiry is not None:
        tool.warranty_expiry = warranty_expiry
    if warranty_notes is not None:
        tool.warranty_notes = warranty_notes
    if status is not None:
        tool.status = status
    if condition is not None:
        tool.condition = condition
    if notes is not None:
        tool.notes = notes
    if is_active is not None:
        tool.is_active = is_active

    tool.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(tool)

    # Reload with relationships
    tool = db.query(Tool).options(
        joinedload(Tool.category),
        joinedload(Tool.vendor),
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse)
    ).filter(Tool.id == tool.id).first()

    return tool_to_response(tool)


@router.post("/tools/{tool_id}/allocate", response_model=dict)
async def allocate_tool(
    tool_id: int,
    assigned_site_id: Optional[int] = None,
    assigned_technician_id: Optional[int] = None,
    assigned_warehouse_id: Optional[int] = None,
    reason: Optional[str] = "reassignment",
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Assign or transfer a tool to a new location.
    Only ONE assignment can be active at a time.
    No journal entries are created on transfer (per requirements).
    """
    tool = db.query(Tool).options(
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse)
    ).filter(
        Tool.id == tool_id,
        Tool.company_id == current_user.company_id
    ).first()

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Validate single assignment
    if not validate_single_assignment(assigned_site_id, assigned_technician_id, assigned_warehouse_id):
        raise HTTPException(
            status_code=400,
            detail="Tool can only be assigned to ONE of: Site, Technician, or Warehouse"
        )

    # Validate reason
    valid_reasons = ["initial_assignment", "reassignment", "return", "maintenance"]
    if reason not in valid_reasons:
        reason = "reassignment"

    # Validate target entities exist
    if assigned_site_id:
        # Site is linked to company through Client
        site = db.query(Site).join(Client, Site.client_id == Client.id).filter(
            Site.id == assigned_site_id,
            Client.company_id == current_user.company_id
        ).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

    if assigned_technician_id:
        technician = db.query(Technician).filter(
            Technician.id == assigned_technician_id,
            Technician.company_id == current_user.company_id
        ).first()
        if not technician:
            raise HTTPException(status_code=404, detail="Technician not found")

    if assigned_warehouse_id:
        warehouse = db.query(Warehouse).filter(
            Warehouse.id == assigned_warehouse_id,
            Warehouse.company_id == current_user.company_id
        ).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="Warehouse not found")

    # Create allocation history record
    history = ToolAllocationHistory(
        tool_id=tool.id,
        transfer_date=datetime.utcnow(),
        from_site_id=tool.assigned_site_id,
        from_technician_id=tool.assigned_technician_id,
        from_warehouse_id=tool.assigned_warehouse_id,
        to_site_id=assigned_site_id,
        to_technician_id=assigned_technician_id,
        to_warehouse_id=assigned_warehouse_id,
        reason=reason,
        notes=notes,
        transferred_by=current_user.id
    )
    db.add(history)

    # Update tool assignment
    tool.assigned_site_id = assigned_site_id
    tool.assigned_technician_id = assigned_technician_id
    tool.assigned_warehouse_id = assigned_warehouse_id
    tool.assigned_at = datetime.utcnow()

    # Update status based on assignment
    if assigned_technician_id or assigned_site_id:
        tool.status = "in_use"
    elif assigned_warehouse_id:
        tool.status = "available"
    else:
        tool.status = "available"

    tool.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(tool)

    # Reload with relationships
    tool = db.query(Tool).options(
        joinedload(Tool.category),
        joinedload(Tool.vendor),
        joinedload(Tool.assigned_site),
        joinedload(Tool.assigned_technician),
        joinedload(Tool.assigned_warehouse)
    ).filter(Tool.id == tool.id).first()

    return {
        "message": "Tool allocated successfully",
        "tool": tool_to_response(tool)
    }


@router.get("/tools/{tool_id}/history", response_model=List[dict])
async def get_tool_allocation_history(
    tool_id: int,
    limit: int = Query(50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get allocation history for a tool"""
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.company_id == current_user.company_id
    ).first()

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    history = db.query(ToolAllocationHistory).options(
        joinedload(ToolAllocationHistory.from_site),
        joinedload(ToolAllocationHistory.from_technician),
        joinedload(ToolAllocationHistory.from_warehouse),
        joinedload(ToolAllocationHistory.to_site),
        joinedload(ToolAllocationHistory.to_technician),
        joinedload(ToolAllocationHistory.to_warehouse),
        joinedload(ToolAllocationHistory.transferred_by_user)
    ).filter(
        ToolAllocationHistory.tool_id == tool_id
    ).order_by(ToolAllocationHistory.transfer_date.desc()).limit(limit).all()

    return [
        {
            "id": h.id,
            "transfer_date": h.transfer_date,
            "from_site_id": h.from_site_id,
            "from_site_name": h.from_site.name if h.from_site else None,
            "from_technician_id": h.from_technician_id,
            "from_technician_name": h.from_technician.name if h.from_technician else None,
            "from_warehouse_id": h.from_warehouse_id,
            "from_warehouse_name": h.from_warehouse.name if h.from_warehouse else None,
            "to_site_id": h.to_site_id,
            "to_site_name": h.to_site.name if h.to_site else None,
            "to_technician_id": h.to_technician_id,
            "to_technician_name": h.to_technician.name if h.to_technician else None,
            "to_warehouse_id": h.to_warehouse_id,
            "to_warehouse_name": h.to_warehouse.name if h.to_warehouse else None,
            "reason": h.reason,
            "notes": h.notes,
            "transferred_by": h.transferred_by,
            "transferred_by_name": h.transferred_by_user.name if h.transferred_by_user else None,
            "created_at": h.created_at
        }
        for h in history
    ]


@router.delete("/tools/{tool_id}")
async def delete_tool(
    tool_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a tool (deactivate)"""
    tool = db.query(Tool).filter(
        Tool.id == tool_id,
        Tool.company_id == current_user.company_id
    ).first()

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    tool.is_active = False
    tool.status = "retired"
    tool.updated_at = datetime.utcnow()

    db.commit()

    return {"message": "Tool deactivated successfully"}


# =============================================================================
# TOOL PURCHASE ENDPOINTS
# =============================================================================

class ToolPurchaseLineInput(BaseModel):
    category_id: int
    description: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    quantity: int = 1
    unit_cost: float
    serial_numbers: Optional[str] = None
    notes: Optional[str] = None


class ToolPurchaseInput(BaseModel):
    purchase_date: date
    vendor_id: int
    currency: str = "USD"
    initial_warehouse_id: Optional[int] = None
    tax_amount: float = 0
    reference: Optional[str] = None
    notes: Optional[str] = None
    lines: List[ToolPurchaseLineInput] = []


@router.get("/tool-purchases", response_model=List[dict])
async def list_tool_purchases(
    status: Optional[str] = None,
    vendor_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List tool purchases"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    query = db.query(ToolPurchase).options(
        joinedload(ToolPurchase.vendor),
        joinedload(ToolPurchase.initial_warehouse)
    ).filter(ToolPurchase.company_id == current_user.company_id)

    if status:
        query = query.filter(ToolPurchase.status == status)
    if vendor_id:
        query = query.filter(ToolPurchase.vendor_id == vendor_id)
    if start_date:
        query = query.filter(ToolPurchase.purchase_date >= start_date)
    if end_date:
        query = query.filter(ToolPurchase.purchase_date <= end_date)

    purchases = query.order_by(ToolPurchase.created_at.desc()).offset(offset).limit(limit).all()

    return [purchase_to_response(p, include_lines=False) for p in purchases]


@router.post("/tool-purchases", response_model=dict)
async def create_tool_purchase(
    data: ToolPurchaseInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new tool purchase"""
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    # Validate vendor
    vendor = db.query(Vendor).filter(
        Vendor.id == data.vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Validate warehouse if provided
    if data.initial_warehouse_id:
        warehouse = db.query(Warehouse).filter(
            Warehouse.id == data.initial_warehouse_id,
            Warehouse.company_id == current_user.company_id
        ).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="Warehouse not found")

    # Generate purchase number
    purchase_number = generate_purchase_number(db, current_user.company_id)

    purchase = ToolPurchase(
        company_id=current_user.company_id,
        purchase_number=purchase_number,
        purchase_date=data.purchase_date,
        vendor_id=data.vendor_id,
        currency=data.currency,
        initial_warehouse_id=data.initial_warehouse_id,
        tax_amount=data.tax_amount,
        reference=data.reference,
        notes=data.notes,
        status="draft",
        created_by=current_user.id
    )

    db.add(purchase)
    db.flush()

    # Add lines
    subtotal = Decimal("0")
    line_number = 1

    for line_data in data.lines:
        # Validate category
        category = db.query(ToolCategory).filter(
            ToolCategory.id == line_data.category_id,
            ToolCategory.company_id == current_user.company_id
        ).first()

        if not category:
            raise HTTPException(status_code=404, detail=f"Tool category {line_data.category_id} not found")

        total_cost = Decimal(str(line_data.quantity)) * Decimal(str(line_data.unit_cost))

        line = ToolPurchaseLine(
            purchase_id=purchase.id,
            line_number=line_number,
            category_id=line_data.category_id,
            description=line_data.description,
            manufacturer=line_data.manufacturer,
            model=line_data.model,
            quantity=line_data.quantity,
            unit_cost=line_data.unit_cost,
            total_cost=total_cost,
            serial_numbers=line_data.serial_numbers,
            notes=line_data.notes
        )
        db.add(line)
        subtotal += total_cost
        line_number += 1

    purchase.subtotal = subtotal
    purchase.total_amount = subtotal + Decimal(str(data.tax_amount))

    db.commit()
    db.refresh(purchase)

    # Reload with relationships
    purchase = db.query(ToolPurchase).options(
        joinedload(ToolPurchase.vendor),
        joinedload(ToolPurchase.initial_warehouse),
        joinedload(ToolPurchase.lines).joinedload(ToolPurchaseLine.category)
    ).filter(ToolPurchase.id == purchase.id).first()

    return purchase_to_response(purchase)


@router.get("/tool-purchases/{purchase_id}", response_model=dict)
async def get_tool_purchase(
    purchase_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific tool purchase"""
    purchase = db.query(ToolPurchase).options(
        joinedload(ToolPurchase.vendor),
        joinedload(ToolPurchase.initial_warehouse),
        joinedload(ToolPurchase.lines).joinedload(ToolPurchaseLine.category),
        joinedload(ToolPurchase.approver),
        joinedload(ToolPurchase.receiver)
    ).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    return purchase_to_response(purchase)


@router.put("/tool-purchases/{purchase_id}", response_model=dict)
async def update_tool_purchase(
    purchase_id: int,
    purchase_date: Optional[date] = None,
    vendor_id: Optional[int] = None,
    currency: Optional[str] = None,
    initial_warehouse_id: Optional[int] = None,
    tax_amount: Optional[float] = None,
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a tool purchase (draft only)"""
    purchase = db.query(ToolPurchase).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Can only update draft purchases")

    if purchase_date is not None:
        purchase.purchase_date = purchase_date
    if vendor_id is not None:
        purchase.vendor_id = vendor_id
    if currency is not None:
        purchase.currency = currency
    if initial_warehouse_id is not None:
        purchase.initial_warehouse_id = initial_warehouse_id
    if tax_amount is not None:
        purchase.tax_amount = tax_amount
        purchase.total_amount = float(purchase.subtotal or 0) + tax_amount
    if reference is not None:
        purchase.reference = reference
    if notes is not None:
        purchase.notes = notes

    purchase.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(purchase)

    # Reload with relationships
    purchase = db.query(ToolPurchase).options(
        joinedload(ToolPurchase.vendor),
        joinedload(ToolPurchase.initial_warehouse),
        joinedload(ToolPurchase.lines).joinedload(ToolPurchaseLine.category)
    ).filter(ToolPurchase.id == purchase.id).first()

    return purchase_to_response(purchase)


@router.delete("/tool-purchases/{purchase_id}")
async def delete_tool_purchase(
    purchase_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a tool purchase (draft only)"""
    purchase = db.query(ToolPurchase).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Can only delete draft purchases")

    # Delete lines first
    db.query(ToolPurchaseLine).filter(ToolPurchaseLine.purchase_id == purchase.id).delete()
    db.delete(purchase)
    db.commit()

    return {"message": "Tool purchase deleted successfully"}


@router.post("/tool-purchases/{purchase_id}/lines", response_model=dict)
async def add_purchase_line(
    purchase_id: int,
    line: ToolPurchaseLineInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a line to a tool purchase"""
    purchase = db.query(ToolPurchase).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Can only add lines to draft purchases")

    # Validate category
    category = db.query(ToolCategory).filter(
        ToolCategory.id == line.category_id,
        ToolCategory.company_id == current_user.company_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Tool category not found")

    # Get next line number
    max_line = db.query(func.max(ToolPurchaseLine.line_number)).filter(
        ToolPurchaseLine.purchase_id == purchase.id
    ).scalar() or 0

    total_cost = Decimal(str(line.quantity)) * Decimal(str(line.unit_cost))

    new_line = ToolPurchaseLine(
        purchase_id=purchase.id,
        line_number=max_line + 1,
        category_id=line.category_id,
        description=line.description,
        manufacturer=line.manufacturer,
        model=line.model,
        quantity=line.quantity,
        unit_cost=line.unit_cost,
        total_cost=total_cost,
        serial_numbers=line.serial_numbers,
        notes=line.notes
    )
    db.add(new_line)

    # Update purchase totals
    purchase.subtotal = float(purchase.subtotal or 0) + float(total_cost)
    purchase.total_amount = purchase.subtotal + float(purchase.tax_amount or 0)
    purchase.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(new_line)

    return {
        "id": new_line.id,
        "line_number": new_line.line_number,
        "category_id": new_line.category_id,
        "description": new_line.description,
        "quantity": new_line.quantity,
        "unit_cost": float(new_line.unit_cost),
        "total_cost": float(new_line.total_cost)
    }


@router.delete("/tool-purchases/{purchase_id}/lines/{line_id}")
async def delete_purchase_line(
    purchase_id: int,
    line_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a line from a tool purchase"""
    purchase = db.query(ToolPurchase).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Can only delete lines from draft purchases")

    line = db.query(ToolPurchaseLine).filter(
        ToolPurchaseLine.id == line_id,
        ToolPurchaseLine.purchase_id == purchase.id
    ).first()

    if not line:
        raise HTTPException(status_code=404, detail="Purchase line not found")

    # Update purchase totals
    purchase.subtotal = float(purchase.subtotal or 0) - float(line.total_cost or 0)
    purchase.total_amount = purchase.subtotal + float(purchase.tax_amount or 0)
    purchase.updated_at = datetime.utcnow()

    db.delete(line)
    db.commit()

    return {"message": "Purchase line deleted successfully"}


@router.post("/tool-purchases/{purchase_id}/approve", response_model=dict)
async def approve_tool_purchase(
    purchase_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Approve a tool purchase"""
    purchase = db.query(ToolPurchase).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status != "draft":
        raise HTTPException(status_code=400, detail=f"Cannot approve purchase with status '{purchase.status}'")

    # Must have at least one line
    if not purchase.lines:
        raise HTTPException(status_code=400, detail="Cannot approve purchase with no lines")

    purchase.status = "approved"
    purchase.approved_by = current_user.id
    purchase.approved_at = datetime.utcnow()
    purchase.updated_at = datetime.utcnow()

    db.commit()

    return {
        "message": "Tool purchase approved successfully",
        "purchase_number": purchase.purchase_number,
        "status": purchase.status
    }


@router.post("/tool-purchases/{purchase_id}/receive", response_model=dict)
async def receive_tool_purchase(
    purchase_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Receive a tool purchase.
    This will:
    1. Create Tool records for each line item
    2. Create journal entry for accounting
    3. Mark purchase as received
    """
    purchase = db.query(ToolPurchase).options(
        joinedload(ToolPurchase.lines).joinedload(ToolPurchaseLine.category),
        joinedload(ToolPurchase.vendor)
    ).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status != "approved":
        raise HTTPException(status_code=400, detail=f"Cannot receive purchase with status '{purchase.status}'")

    try:
        tools_created = []

        # Create tools for each line
        for line in purchase.lines:
            category = line.category

            # Parse serial numbers if provided
            serial_numbers = []
            if line.serial_numbers:
                serial_numbers = [s.strip() for s in line.serial_numbers.split(",") if s.strip()]

            # Create tool(s) for this line
            for i in range(line.quantity):
                tool_number = generate_tool_number(db, current_user.company_id)
                unit_cost = float(line.unit_cost or 0)

                # Get serial number for this tool if available
                serial_number = serial_numbers[i] if i < len(serial_numbers) else None

                # Calculate salvage value from category settings
                salvage_value = None
                if category.asset_type == "fixed_asset" and category.salvage_value_percentage:
                    salvage_value = unit_cost * float(category.salvage_value_percentage) / 100

                tool = Tool(
                    company_id=current_user.company_id,
                    category_id=line.category_id,
                    tool_number=tool_number,
                    name=line.description,
                    serial_number=serial_number,
                    manufacturer=line.manufacturer,
                    model=line.model,
                    purchase_id=purchase.id,
                    purchase_date=purchase.purchase_date,
                    purchase_cost=unit_cost,
                    vendor_id=purchase.vendor_id,
                    capitalization_date=purchase.purchase_date if category.asset_type == "fixed_asset" else None,
                    useful_life_months=category.useful_life_months,
                    salvage_value=salvage_value,
                    net_book_value=unit_cost if category.asset_type == "fixed_asset" else None,
                    status="available",
                    condition="excellent",
                    assigned_warehouse_id=purchase.initial_warehouse_id,
                    assigned_at=datetime.utcnow() if purchase.initial_warehouse_id else None,
                    notes=line.notes,
                    created_by=current_user.id
                )
                db.add(tool)
                db.flush()

                tools_created.append(tool)

                # Create initial allocation history if assigned to warehouse
                if purchase.initial_warehouse_id:
                    history = ToolAllocationHistory(
                        tool_id=tool.id,
                        transfer_date=datetime.utcnow(),
                        to_warehouse_id=purchase.initial_warehouse_id,
                        reason="initial_assignment",
                        notes=f"Received from purchase {purchase.purchase_number}",
                        transferred_by=current_user.id
                    )
                    db.add(history)

        # Create journal entry
        journal_entry = create_tool_purchase_journal_entry(
            db, purchase, current_user.company_id, current_user.id
        )

        if journal_entry:
            purchase.journal_entry_id = journal_entry.id

        # Update purchase status
        purchase.status = "received"
        purchase.received_by = current_user.id
        purchase.received_at = datetime.utcnow()
        purchase.updated_at = datetime.utcnow()

        db.commit()

        return {
            "message": "Tool purchase received successfully",
            "purchase_number": purchase.purchase_number,
            "tools_created": len(tools_created),
            "journal_entry_id": purchase.journal_entry_id
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error receiving tool purchase {purchase_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error receiving purchase: {str(e)}")


@router.post("/tool-purchases/{purchase_id}/cancel", response_model=dict)
async def cancel_tool_purchase(
    purchase_id: int,
    reason: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a tool purchase"""
    purchase = db.query(ToolPurchase).filter(
        ToolPurchase.id == purchase_id,
        ToolPurchase.company_id == current_user.company_id
    ).first()

    if not purchase:
        raise HTTPException(status_code=404, detail="Tool purchase not found")

    if purchase.status == "received":
        raise HTTPException(status_code=400, detail="Cannot cancel a received purchase")

    if purchase.status == "cancelled":
        raise HTTPException(status_code=400, detail="Purchase is already cancelled")

    purchase.status = "cancelled"
    if reason:
        purchase.notes = f"{purchase.notes or ''}\nCancelled: {reason}".strip()
    purchase.updated_at = datetime.utcnow()

    db.commit()

    return {
        "message": "Tool purchase cancelled successfully",
        "purchase_number": purchase.purchase_number,
        "status": purchase.status
    }


# =============================================================================
# JOURNAL ENTRY HELPER
# =============================================================================

def create_tool_purchase_journal_entry(
    db: Session,
    purchase: ToolPurchase,
    company_id: int,
    user_id: int
) -> Optional[JournalEntry]:
    """
    Create journal entry for tool purchase receiving.

    For Fixed Assets:
    - DR: Tools & Equipment (1210)
    - CR: Accounts Payable (2110)

    For Consumables:
    - DR: Tools Expense (5250)
    - CR: Accounts Payable (2110)
    """
    try:
        # Group lines by asset type
        fixed_asset_total = Decimal("0")
        consumable_total = Decimal("0")

        for line in purchase.lines:
            if line.category and line.category.asset_type == "fixed_asset":
                fixed_asset_total += Decimal(str(line.total_cost or 0))
            else:
                consumable_total += Decimal(str(line.total_cost or 0))

        total_value = fixed_asset_total + consumable_total
        tax_amount = Decimal(str(purchase.tax_amount or 0))
        total_with_tax = total_value + tax_amount

        if total_value == 0:
            return None

        # Generate entry number
        year = datetime.now().year
        prefix = f"JE-{year}-"
        last_entry = db.query(JournalEntry).filter(
            JournalEntry.company_id == company_id,
            JournalEntry.entry_number.like(f"{prefix}%")
        ).order_by(desc(JournalEntry.entry_number)).first()

        if last_entry:
            try:
                last_num = int(last_entry.entry_number.split("-")[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        entry_number = f"{prefix}{next_num:06d}"

        # Get fiscal period
        fiscal_period = db.query(FiscalPeriod).filter(
            FiscalPeriod.company_id == company_id,
            FiscalPeriod.start_date <= purchase.purchase_date,
            FiscalPeriod.end_date >= purchase.purchase_date,
            FiscalPeriod.status != "closed"
        ).first()

        # Create journal entry
        vendor_name = purchase.vendor.name if purchase.vendor else "Unknown Vendor"

        entry = JournalEntry(
            company_id=company_id,
            entry_number=entry_number,
            entry_date=purchase.purchase_date,
            description=f"Tool Purchase - {purchase.purchase_number} from {vendor_name}",
            reference=purchase.purchase_number,
            source_type="tool_purchase",
            source_id=purchase.id,
            source_number=purchase.purchase_number,
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="posted",
            is_auto_generated=True,
            posted_at=datetime.utcnow(),
            posted_by=user_id,
            created_by=user_id
        )
        db.add(entry)
        db.flush()

        lines = []
        line_number = 1

        # Get accounts from category or use default accounts
        asset_account_id = None
        expense_account_id = None

        for line in purchase.lines:
            if line.category:
                if line.category.asset_type == "fixed_asset" and line.category.asset_account_id:
                    asset_account_id = line.category.asset_account_id
                elif line.category.asset_type == "consumable" and line.category.expense_account_id:
                    expense_account_id = line.category.expense_account_id

        # Fall back to default accounts if not set in category
        if fixed_asset_total > 0 and not asset_account_id:
            # Look for default Tools & Equipment account (1210)
            default_asset = db.query(Account).filter(
                Account.company_id == company_id,
                Account.code == "1210"
            ).first()
            if default_asset:
                asset_account_id = default_asset.id

        if consumable_total > 0 and not expense_account_id:
            # Look for default Tools Expense account (5250)
            default_expense = db.query(Account).filter(
                Account.company_id == company_id,
                Account.code == "5250"
            ).first()
            if default_expense:
                expense_account_id = default_expense.id

        # Debit: Fixed Assets (if any)
        if fixed_asset_total > 0 and asset_account_id:
            asset_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=asset_account_id,
                debit=float(fixed_asset_total),
                credit=0,
                description=f"Tools & Equipment - {purchase.purchase_number}",
                vendor_id=purchase.vendor_id,
                line_number=line_number
            )
            db.add(asset_line)
            lines.append(asset_line)
            line_number += 1

        # Debit: Consumables Expense (if any)
        if consumable_total > 0 and expense_account_id:
            expense_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=expense_account_id,
                debit=float(consumable_total),
                credit=0,
                description=f"Tools Expense - {purchase.purchase_number}",
                vendor_id=purchase.vendor_id,
                line_number=line_number
            )
            db.add(expense_line)
            lines.append(expense_line)
            line_number += 1

        # Credit: Accounts Payable (using vendor's or default account)
        # For now we'll just use a placeholder - in production you'd look up the AP account
        ap_account = db.query(Account).filter(
            Account.company_id == company_id,
            Account.code == "2110"  # Standard AP account
        ).first()

        if ap_account:
            ap_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=ap_account.id,
                debit=0,
                credit=float(total_with_tax),
                description=f"Payable for {purchase.purchase_number} - {vendor_name}",
                vendor_id=purchase.vendor_id,
                line_number=line_number
            )
            db.add(ap_line)
            lines.append(ap_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        logger.info(f"Created journal entry {entry.entry_number} for tool purchase {purchase.purchase_number}")

        return entry

    except Exception as e:
        logger.error(f"Error creating journal entry for tool purchase: {e}")
        return None


# =============================================================================
# DEPRECIATION ENDPOINTS
# =============================================================================

@router.post("/tools/depreciation/calculate", response_model=dict)
async def calculate_depreciation(
    as_of_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Preview depreciation calculation for all fixed asset tools.
    Does not create any journal entries.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    if as_of_date is None:
        as_of_date = date.today()

    # Get all active fixed asset tools
    tools = db.query(Tool).options(
        joinedload(Tool.category)
    ).filter(
        Tool.company_id == current_user.company_id,
        Tool.is_active == True,
        Tool.category.has(asset_type="fixed_asset"),
        Tool.capitalization_date.isnot(None),
        Tool.purchase_cost.isnot(None)
    ).all()

    depreciation_details = []
    total_depreciation = Decimal("0")

    for tool in tools:
        if not tool.useful_life_months or tool.useful_life_months <= 0:
            continue

        # Calculate months since last depreciation (or capitalization)
        last_dep_date = tool.last_depreciation_date or tool.capitalization_date
        if not last_dep_date:
            continue

        # Only depreciate if we haven't depreciated this period
        if tool.last_depreciation_date and tool.last_depreciation_date >= as_of_date:
            continue

        # Calculate monthly depreciation (straight-line)
        purchase_cost = Decimal(str(tool.purchase_cost))
        salvage_value = Decimal(str(tool.salvage_value or 0))
        depreciable_amount = purchase_cost - salvage_value
        monthly_depreciation = depreciable_amount / Decimal(str(tool.useful_life_months))

        # Calculate months to depreciate
        months_since_last = ((as_of_date.year - last_dep_date.year) * 12 +
                            (as_of_date.month - last_dep_date.month))

        if months_since_last <= 0:
            continue

        # Calculate depreciation for this period
        accumulated = Decimal(str(tool.accumulated_depreciation or 0))
        remaining_to_depreciate = depreciable_amount - accumulated

        if remaining_to_depreciate <= 0:
            continue

        period_depreciation = min(
            monthly_depreciation * months_since_last,
            remaining_to_depreciate
        )

        new_nbv = purchase_cost - accumulated - period_depreciation

        depreciation_details.append({
            "tool_id": tool.id,
            "tool_number": tool.tool_number,
            "name": tool.name,
            "purchase_cost": float(purchase_cost),
            "salvage_value": float(salvage_value),
            "accumulated_depreciation": float(accumulated),
            "period_depreciation": float(period_depreciation),
            "new_accumulated_depreciation": float(accumulated + period_depreciation),
            "new_net_book_value": float(new_nbv),
            "months_depreciated": months_since_last
        })

        total_depreciation += period_depreciation

    return {
        "as_of_date": as_of_date,
        "tools_count": len(depreciation_details),
        "total_depreciation": float(total_depreciation),
        "details": depreciation_details
    }


@router.post("/tools/depreciation/run", response_model=dict)
async def run_depreciation(
    as_of_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Run depreciation for all fixed asset tools.
    Creates a consolidated journal entry for all depreciation.
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must be associated with a company")

    if as_of_date is None:
        as_of_date = date.today()

    # First calculate depreciation
    calc_result = await calculate_depreciation(as_of_date, current_user, db)

    if calc_result["tools_count"] == 0:
        return {
            "message": "No tools require depreciation",
            "tools_processed": 0,
            "total_depreciation": 0,
            "journal_entry_id": None
        }

    try:
        total_depreciation = Decimal(str(calc_result["total_depreciation"]))

        # Update each tool
        for detail in calc_result["details"]:
            tool = db.query(Tool).filter(Tool.id == detail["tool_id"]).first()
            if tool:
                tool.accumulated_depreciation = detail["new_accumulated_depreciation"]
                tool.net_book_value = detail["new_net_book_value"]
                tool.last_depreciation_date = as_of_date
                tool.updated_at = datetime.utcnow()

        # Create consolidated journal entry
        journal_entry = create_depreciation_journal_entry(
            db,
            current_user.company_id,
            current_user.id,
            as_of_date,
            total_depreciation,
            calc_result["tools_count"]
        )

        db.commit()

        return {
            "message": "Depreciation run completed successfully",
            "as_of_date": as_of_date,
            "tools_processed": calc_result["tools_count"],
            "total_depreciation": float(total_depreciation),
            "journal_entry_id": journal_entry.id if journal_entry else None,
            "details": calc_result["details"]
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error running depreciation: {e}")
        raise HTTPException(status_code=500, detail=f"Error running depreciation: {str(e)}")


def create_depreciation_journal_entry(
    db: Session,
    company_id: int,
    user_id: int,
    depreciation_date: date,
    total_depreciation: Decimal,
    tools_count: int
) -> Optional[JournalEntry]:
    """
    Create journal entry for depreciation run.

    DR: Depreciation Expense (5330)
    CR: Accumulated Depreciation (1290)
    """
    try:
        # Generate entry number
        year = datetime.now().year
        prefix = f"JE-{year}-"
        last_entry = db.query(JournalEntry).filter(
            JournalEntry.company_id == company_id,
            JournalEntry.entry_number.like(f"{prefix}%")
        ).order_by(desc(JournalEntry.entry_number)).first()

        if last_entry:
            try:
                last_num = int(last_entry.entry_number.split("-")[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

        entry_number = f"{prefix}{next_num:06d}"

        # Get fiscal period
        fiscal_period = db.query(FiscalPeriod).filter(
            FiscalPeriod.company_id == company_id,
            FiscalPeriod.start_date <= depreciation_date,
            FiscalPeriod.end_date >= depreciation_date,
            FiscalPeriod.status != "closed"
        ).first()

        # Create journal entry
        entry = JournalEntry(
            company_id=company_id,
            entry_number=entry_number,
            entry_date=depreciation_date,
            description=f"Tool Depreciation - {tools_count} tools - {depreciation_date.strftime('%B %Y')}",
            reference=f"DEP-{depreciation_date.strftime('%Y%m')}",
            source_type="tool_depreciation",
            fiscal_period_id=fiscal_period.id if fiscal_period else None,
            status="posted",
            is_auto_generated=True,
            posted_at=datetime.utcnow(),
            posted_by=user_id,
            created_by=user_id
        )
        db.add(entry)
        db.flush()

        # Get depreciation accounts
        expense_account = db.query(Account).filter(
            Account.company_id == company_id,
            Account.account_number == "5330"  # Depreciation Expense
        ).first()

        accum_account = db.query(Account).filter(
            Account.company_id == company_id,
            Account.account_number == "1290"  # Accumulated Depreciation
        ).first()

        lines = []

        # DR: Depreciation Expense
        if expense_account:
            expense_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=expense_account.id,
                debit=float(total_depreciation),
                credit=0,
                description=f"Depreciation expense - {tools_count} tools",
                line_number=1
            )
            db.add(expense_line)
            lines.append(expense_line)

        # CR: Accumulated Depreciation
        if accum_account:
            accum_line = JournalEntryLine(
                journal_entry_id=entry.id,
                account_id=accum_account.id,
                debit=0,
                credit=float(total_depreciation),
                description=f"Accumulated depreciation - {tools_count} tools",
                line_number=2
            )
            db.add(accum_line)
            lines.append(accum_line)

        # Update totals
        entry.total_debit = sum(float(l.debit) for l in lines)
        entry.total_credit = sum(float(l.credit) for l in lines)

        logger.info(f"Created depreciation journal entry {entry.entry_number}")

        return entry

    except Exception as e:
        logger.error(f"Error creating depreciation journal entry: {e}")
        return None
