"""
Item Master API endpoints for inventory management
Manages items, categories, stock levels, transfers, and ledger entries
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, case
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import logging
import io
import re

from app.database import get_db
from app.models import (
    User, ItemCategory, ItemMaster, ItemStock, ItemLedger,
    ItemTransfer, ItemTransferLine, InvoiceItem, ItemAlias,
    Warehouse, HandHeldDevice, Vendor, WorkOrder
)
from app.api.auth import verify_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt
from app.config import settings

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)


# ============ HHD Authentication Support ============

class HHDContext:
    """Context object for HHD authentication - mimics User for compatibility"""
    def __init__(self, device: HandHeldDevice, technician_id: Optional[int] = None):
        self.device = device
        self.company_id = device.company_id
        self.id = technician_id  # For created_by fields
        self.email = f"hhd:{device.device_code}"
        self.name = device.device_name
        self.role = "technician"  # HHD has technician-level access


def verify_token_payload(token: str) -> Optional[dict]:
    """Verify token and return full payload"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except:
        return None


def get_current_user_or_hhd(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Authenticate either a User (admin portal) or HHD device (mobile app).
    Returns User object for admin tokens, or HHDContext for mobile tokens.
    """
    token = credentials.credentials
    payload = verify_token_payload(token)

    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    sub = payload.get("sub")
    token_type = payload.get("type")

    # Check if this is an HHD token
    if token_type == "hhd" or (sub and sub.startswith("hhd:")):
        device_id = payload.get("device_id")
        if not device_id:
            # Try to extract from sub
            try:
                device_id = int(sub.split(":")[1])
            except:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid HHD token")

        device = db.query(HandHeldDevice).filter(
            HandHeldDevice.id == device_id,
            HandHeldDevice.is_active == True
        ).first()

        if not device:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Device not found or inactive")

        technician_id = payload.get("technician_id")
        return HHDContext(device, technician_id)

    # Regular user token
    email = sub
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


# ============ Pydantic Schemas ============

class ItemCategoryCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = 0


class ItemCategoryUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ItemMasterCreate(BaseModel):
    item_number: str
    description: str
    short_item_no: Optional[int] = None
    search_text: Optional[str] = None
    category_id: Optional[int] = None
    stocking_type: Optional[str] = "S"
    line_type: Optional[str] = "S"
    unit: Optional[str] = "pcs"
    unit_cost: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = "USD"
    minimum_stock_level: Optional[int] = 0
    reorder_quantity: Optional[int] = 0
    primary_vendor_id: Optional[int] = None
    vendor_part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    notes: Optional[str] = None


class ItemMasterUpdate(BaseModel):
    item_number: Optional[str] = None
    description: Optional[str] = None
    short_item_no: Optional[int] = None
    search_text: Optional[str] = None
    category_id: Optional[int] = None
    stocking_type: Optional[str] = None
    line_type: Optional[str] = None
    unit: Optional[str] = None
    unit_cost: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    minimum_stock_level: Optional[int] = None
    reorder_quantity: Optional[int] = None
    primary_vendor_id: Optional[int] = None
    vendor_part_number: Optional[str] = None
    manufacturer: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ItemTransferCreate(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: Optional[int] = None
    to_hhd_id: Optional[int] = None
    notes: Optional[str] = None
    lines: List[dict]  # [{item_id, quantity_requested, notes}]


class ItemTransferLineAdd(BaseModel):
    item_id: int
    quantity_requested: float
    notes: Optional[str] = None


class StockAdjustmentCreate(BaseModel):
    item_id: int
    warehouse_id: Optional[int] = None
    hhd_id: Optional[int] = None
    quantity: float  # Positive for add, negative for subtract
    reason: str
    notes: Optional[str] = None


class ReceiveInvoiceItemRequest(BaseModel):
    invoice_item_id: int
    quantity_to_receive: float
    warehouse_id: int
    item_id: Optional[int] = None  # Link to item master (optional, can create new)
    notes: Optional[str] = None


# ============ Dependencies ============

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin_or_accounting(user: User = Depends(get_current_user)):
    if user.role not in ["admin", "accounting"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or accounting access required")
    return user


# ============ Helper Functions ============

def decimal_to_float(val):
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return val


def generate_transaction_number(db: Session, company_id: int, prefix: str) -> str:
    """Generate unique transaction number"""
    year = datetime.now().year
    month = datetime.now().month
    full_prefix = f"{prefix}-{year}{month:02d}-"

    last_entry = db.query(ItemLedger).filter(
        ItemLedger.company_id == company_id,
        ItemLedger.transaction_number.like(f"{full_prefix}%")
    ).order_by(ItemLedger.id.desc()).first()

    if last_entry:
        try:
            last_num = int(last_entry.transaction_number.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1

    return f"{full_prefix}{new_num:05d}"


def generate_transfer_number(db: Session, company_id: int) -> str:
    """Generate unique transfer number"""
    year = datetime.now().year
    prefix = f"TRF-{year}-"

    last_transfer = db.query(ItemTransfer).filter(
        ItemTransfer.company_id == company_id,
        ItemTransfer.transfer_number.like(f"{prefix}%")
    ).order_by(ItemTransfer.id.desc()).first()

    if last_transfer:
        try:
            last_num = int(last_transfer.transfer_number.split("-")[-1])
            new_num = last_num + 1
        except:
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{new_num:05d}"


def get_or_create_stock(db: Session, company_id: int, item_id: int,
                         warehouse_id: int = None, hhd_id: int = None) -> ItemStock:
    """Get existing stock record or create new one"""
    if warehouse_id:
        stock = db.query(ItemStock).filter(
            ItemStock.item_id == item_id,
            ItemStock.warehouse_id == warehouse_id
        ).first()
    elif hhd_id:
        stock = db.query(ItemStock).filter(
            ItemStock.item_id == item_id,
            ItemStock.handheld_device_id == hhd_id
        ).first()
    else:
        return None

    if not stock:
        stock = ItemStock(
            company_id=company_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            handheld_device_id=hhd_id,
            quantity_on_hand=0
        )
        db.add(stock)
        db.flush()

    return stock


def calculate_weighted_average_cost(
    current_qty: float,
    current_avg_cost: float,
    new_qty: float,
    new_unit_cost: float
) -> float:
    """
    Calculate weighted average cost when receiving new stock.
    Formula: (Current Total Value + New Value) / (Current Qty + New Qty)
    """
    if current_qty <= 0 and new_qty <= 0:
        return new_unit_cost or 0

    current_total = (current_qty or 0) * (current_avg_cost or 0)
    new_total = (new_qty or 0) * (new_unit_cost or 0)
    total_qty = (current_qty or 0) + (new_qty or 0)

    if total_qty <= 0:
        return new_unit_cost or current_avg_cost or 0

    return (current_total + new_total) / total_qty


def update_stock_and_create_ledger(
    db: Session,
    company_id: int,
    item_id: int,
    quantity: float,
    transaction_type: str,
    user_id: int,
    warehouse_id: int = None,
    hhd_id: int = None,
    from_warehouse_id: int = None,
    to_warehouse_id: int = None,
    from_hhd_id: int = None,
    to_hhd_id: int = None,
    invoice_id: int = None,
    work_order_id: int = None,
    transfer_id: int = None,
    unit_cost: float = None,
    notes: str = None
) -> ItemLedger:
    """Update stock levels and create ledger entry with weighted average cost calculation"""

    # Get the item for unit info
    item = db.query(ItemMaster).filter(ItemMaster.id == item_id).first()

    # Determine which stock record to update based on transaction type
    if transaction_type in ["RECEIVE_INVOICE", "INITIAL_STOCK", "ADJUSTMENT_PLUS"]:
        # Adding to warehouse - calculate weighted average cost
        stock = get_or_create_stock(db, company_id, item_id, warehouse_id=to_warehouse_id or warehouse_id)

        current_qty = float(stock.quantity_on_hand or 0)
        current_avg_cost = float(stock.average_cost or 0)

        # Calculate new weighted average cost if unit_cost is provided
        if unit_cost and unit_cost > 0:
            new_avg_cost = calculate_weighted_average_cost(
                current_qty=current_qty,
                current_avg_cost=current_avg_cost,
                new_qty=quantity,
                new_unit_cost=unit_cost
            )
            stock.average_cost = new_avg_cost
            stock.last_cost = unit_cost

        stock.quantity_on_hand = current_qty + quantity
        stock.last_movement_date = datetime.utcnow()
        balance_after = stock.quantity_on_hand

    elif transaction_type == "ADJUSTMENT_MINUS":
        stock = get_or_create_stock(db, company_id, item_id, warehouse_id=from_warehouse_id or warehouse_id, hhd_id=from_hhd_id or hhd_id)
        stock.quantity_on_hand = float(stock.quantity_on_hand or 0) - abs(quantity)
        stock.last_movement_date = datetime.utcnow()
        # Average cost remains unchanged on stock reduction
        balance_after = stock.quantity_on_hand

    elif transaction_type == "TRANSFER_OUT":
        # Deduct from source warehouse - average cost remains unchanged
        stock = get_or_create_stock(db, company_id, item_id, warehouse_id=from_warehouse_id)
        stock.quantity_on_hand = float(stock.quantity_on_hand or 0) - abs(quantity)
        stock.last_movement_date = datetime.utcnow()
        balance_after = stock.quantity_on_hand

    elif transaction_type == "TRANSFER_IN":
        # Add to destination (warehouse or HHD)
        # Use the source stock's average cost for the transfer
        if to_warehouse_id:
            stock = get_or_create_stock(db, company_id, item_id, warehouse_id=to_warehouse_id)
        else:
            stock = get_or_create_stock(db, company_id, item_id, hhd_id=to_hhd_id)

        current_qty = float(stock.quantity_on_hand or 0)
        current_avg_cost = float(stock.average_cost or 0)

        # Calculate weighted average cost for the destination using transfer unit_cost
        if unit_cost and unit_cost > 0:
            new_avg_cost = calculate_weighted_average_cost(
                current_qty=current_qty,
                current_avg_cost=current_avg_cost,
                new_qty=quantity,
                new_unit_cost=unit_cost
            )
            stock.average_cost = new_avg_cost
            stock.last_cost = unit_cost

        stock.quantity_on_hand = current_qty + quantity
        stock.last_movement_date = datetime.utcnow()
        balance_after = stock.quantity_on_hand

    elif transaction_type == "ISSUE_WORK_ORDER":
        # Deduct from HHD - average cost remains unchanged
        stock = get_or_create_stock(db, company_id, item_id, hhd_id=from_hhd_id)
        stock.quantity_on_hand = float(stock.quantity_on_hand or 0) - abs(quantity)
        stock.last_movement_date = datetime.utcnow()
        balance_after = stock.quantity_on_hand

    elif transaction_type == "RETURN_WORK_ORDER":
        # Return to HHD - use existing average cost (no cost change on return)
        stock = get_or_create_stock(db, company_id, item_id, hhd_id=to_hhd_id)
        stock.quantity_on_hand = float(stock.quantity_on_hand or 0) + quantity
        stock.last_movement_date = datetime.utcnow()
        balance_after = stock.quantity_on_hand
    else:
        balance_after = 0

    # Create ledger entry
    transaction_number = generate_transaction_number(db, company_id, transaction_type[:3])

    ledger_entry = ItemLedger(
        company_id=company_id,
        item_id=item_id,
        transaction_number=transaction_number,
        transaction_date=datetime.utcnow(),
        transaction_type=transaction_type,
        quantity=quantity if transaction_type not in ["ADJUSTMENT_MINUS", "TRANSFER_OUT", "ISSUE_WORK_ORDER"] else -abs(quantity),
        unit=item.unit if item else "pcs",
        unit_cost=unit_cost,
        total_cost=unit_cost * quantity if unit_cost else None,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        from_hhd_id=from_hhd_id,
        to_hhd_id=to_hhd_id,
        invoice_id=invoice_id,
        work_order_id=work_order_id,
        transfer_id=transfer_id,
        balance_after=balance_after,
        notes=notes,
        created_by=user_id
    )
    db.add(ledger_entry)

    return ledger_entry


def item_to_response(item: ItemMaster, include_stock: bool = False) -> dict:
    """Convert ItemMaster to response dict"""
    response = {
        "id": item.id,
        "item_number": item.item_number,
        "short_item_no": item.short_item_no,
        "description": item.description,
        "search_text": item.search_text,
        "category_id": item.category_id,
        "category": {
            "id": item.category.id,
            "code": item.category.code,
            "name": item.category.name
        } if item.category else None,
        "stocking_type": item.stocking_type,
        "line_type": item.line_type,
        "unit": item.unit,
        "unit_cost": decimal_to_float(item.unit_cost),
        "unit_price": decimal_to_float(item.unit_price),
        "currency": item.currency,
        "minimum_stock_level": item.minimum_stock_level,
        "reorder_quantity": item.reorder_quantity,
        "primary_vendor_id": item.primary_vendor_id,
        "primary_vendor": {
            "id": item.primary_vendor.id,
            "name": item.primary_vendor.name
        } if item.primary_vendor else None,
        "vendor_part_number": item.vendor_part_number,
        "manufacturer": item.manufacturer,
        "notes": item.notes,
        "is_active": item.is_active,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None
    }

    if include_stock:
        total_stock = sum(decimal_to_float(s.quantity_on_hand) or 0 for s in item.stock_levels)
        response["total_stock"] = total_stock
        response["stock_levels"] = [
            {
                "id": s.id,
                "warehouse_id": s.warehouse_id,
                "warehouse_name": s.warehouse.name if s.warehouse else None,
                "hhd_id": s.handheld_device_id,
                "hhd_code": s.handheld_device.device_code if s.handheld_device else None,
                "quantity_on_hand": decimal_to_float(s.quantity_on_hand),
                "quantity_reserved": decimal_to_float(s.quantity_reserved),
                "average_cost": decimal_to_float(s.average_cost),
                "last_cost": decimal_to_float(s.last_cost)
            }
            for s in item.stock_levels
        ]

    # Include aliases (vendor item codes)
    if hasattr(item, 'aliases') and item.aliases:
        response["aliases"] = [
            {
                "id": alias.id,
                "alias_code": alias.alias_code,
                "alias_description": alias.alias_description,
                "vendor_id": alias.vendor_id,
                "vendor_name": alias.vendor.name if alias.vendor else None,
                "source": alias.source,
                "is_active": alias.is_active,
                "created_at": alias.created_at.isoformat() if alias.created_at else None
            }
            for alias in item.aliases if alias.is_active
        ]
    else:
        response["aliases"] = []

    return response


def category_to_response(cat: ItemCategory) -> dict:
    return {
        "id": cat.id,
        "code": cat.code,
        "name": cat.name,
        "description": cat.description,
        "sort_order": cat.sort_order,
        "is_active": cat.is_active,
        "items_count": len(cat.items) if cat.items else 0,
        "created_at": cat.created_at.isoformat() if cat.created_at else None
    }


# ============ Category Endpoints ============

@router.get("/item-categories/")
async def get_item_categories(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all item categories for the company"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(ItemCategory).filter(ItemCategory.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(ItemCategory.is_active == True)

    categories = query.order_by(ItemCategory.sort_order, ItemCategory.code).all()
    return [category_to_response(c) for c in categories]


@router.post("/item-categories/")
async def create_item_category(
    data: ItemCategoryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new item category"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Check for duplicate code
    existing = db.query(ItemCategory).filter(
        ItemCategory.company_id == user.company_id,
        ItemCategory.code == data.code.upper()
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Category code {data.code} already exists")

    try:
        category = ItemCategory(
            company_id=user.company_id,
            code=data.code.upper(),
            name=data.name,
            description=data.description,
            sort_order=data.sort_order or 0
        )
        db.add(category)
        db.commit()
        db.refresh(category)

        return category_to_response(category)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/item-categories/{category_id}")
async def update_item_category(
    category_id: int,
    data: ItemCategoryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an item category"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    category = db.query(ItemCategory).filter(
        ItemCategory.id == category_id,
        ItemCategory.company_id == user.company_id
    ).first()

    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    try:
        update_data = data.dict(exclude_unset=True)
        if 'code' in update_data and update_data['code']:
            update_data['code'] = update_data['code'].upper()

        for field, value in update_data.items():
            setattr(category, field, value)

        db.commit()
        db.refresh(category)

        return category_to_response(category)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/item-categories/seed-defaults")
async def seed_default_categories(
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Seed default item categories based on MMG classification"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    default_categories = [
        {"code": "CV", "name": "Civil", "sort_order": 1},
        {"code": "EL", "name": "Electrical", "sort_order": 2},
        {"code": "TL", "name": "Tool", "sort_order": 3},
        {"code": "PL", "name": "Plumbing", "sort_order": 4},
        {"code": "MC", "name": "Mechanical", "sort_order": 5},
        {"code": "LGH", "name": "Lighting", "sort_order": 6},
        {"code": "SAN", "name": "Sanitary", "sort_order": 7},
        {"code": "HVC", "name": "HVAC", "sort_order": 8},
    ]

    created = []
    skipped = []

    for cat_data in default_categories:
        existing = db.query(ItemCategory).filter(
            ItemCategory.company_id == user.company_id,
            ItemCategory.code == cat_data["code"]
        ).first()

        if existing:
            skipped.append(cat_data["code"])
            continue

        category = ItemCategory(
            company_id=user.company_id,
            **cat_data
        )
        db.add(category)
        created.append(cat_data["code"])

    db.commit()

    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "message": f"Created {len(created)} categories, skipped {len(skipped)} existing"
    }


# ============ Item Master Endpoints ============

@router.get("/items/")
async def get_items(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    include_inactive: bool = False,
    include_stock: bool = False,
    low_stock: bool = False,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get items for the company with pagination"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Base query
    query = db.query(ItemMaster).filter(ItemMaster.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(ItemMaster.is_active == True)

    if category_id:
        query = query.filter(ItemMaster.category_id == category_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                ItemMaster.item_number.ilike(search_term),
                ItemMaster.description.ilike(search_term),
                ItemMaster.search_text.ilike(search_term)
            )
        )

    # For low_stock, we need to filter after getting stock data
    # This is a special case that may return fewer results
    if low_stock:
        # Get all items with stock to filter
        query = query.options(
            joinedload(ItemMaster.stock_levels).joinedload(ItemStock.warehouse),
            joinedload(ItemMaster.stock_levels).joinedload(ItemStock.handheld_device),
            joinedload(ItemMaster.category),
            joinedload(ItemMaster.primary_vendor)
        )
        all_items = query.order_by(ItemMaster.item_number).all()

        # Filter for low stock
        low_stock_items = []
        for item in all_items:
            item_response = item_to_response(item, include_stock=True)
            if item_response.get('total_stock', 0) <= (item_response.get('minimum_stock_level') or 0):
                low_stock_items.append(item_response)

        # Apply pagination to filtered results
        total = len(low_stock_items)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_items = low_stock_items[start:end]

        return {
            "items": paginated_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }

    # Get total count for pagination
    total = query.count()

    # Add eager loading after count
    if include_stock:
        query = query.options(
            joinedload(ItemMaster.stock_levels).joinedload(ItemStock.warehouse),
            joinedload(ItemMaster.stock_levels).joinedload(ItemStock.handheld_device),
            joinedload(ItemMaster.category),
            joinedload(ItemMaster.primary_vendor)
        )
    else:
        query = query.options(
            joinedload(ItemMaster.category),
            joinedload(ItemMaster.primary_vendor)
        )

    # Apply pagination
    offset = (page - 1) * page_size
    items = query.order_by(ItemMaster.item_number).offset(offset).limit(page_size).all()

    result = [item_to_response(item, include_stock=include_stock) for item in items]

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/items/{item_id}")
async def get_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific item with full details"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    item = db.query(ItemMaster).options(
        joinedload(ItemMaster.stock_levels).joinedload(ItemStock.warehouse),
        joinedload(ItemMaster.stock_levels).joinedload(ItemStock.handheld_device),
        joinedload(ItemMaster.category),
        joinedload(ItemMaster.primary_vendor)
    ).filter(
        ItemMaster.id == item_id,
        ItemMaster.company_id == user.company_id
    ).first()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    return item_to_response(item, include_stock=True)


@router.post("/items/")
async def create_item(
    data: ItemMasterCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Check for duplicate item number
    existing = db.query(ItemMaster).filter(
        ItemMaster.company_id == user.company_id,
        ItemMaster.item_number == data.item_number
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item number {data.item_number} already exists")

    try:
        item = ItemMaster(
            company_id=user.company_id,
            created_by=user.id,
            **data.dict()
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        logger.info(f"Item {item.item_number} created by {user.email}")
        return item_to_response(item)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/items/{item_id}")
async def update_item(
    item_id: int,
    data: ItemMasterUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    item = db.query(ItemMaster).filter(
        ItemMaster.id == item_id,
        ItemMaster.company_id == user.company_id
    ).first()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Check for duplicate item number if being changed
    if data.item_number and data.item_number != item.item_number:
        existing = db.query(ItemMaster).filter(
            ItemMaster.company_id == user.company_id,
            ItemMaster.item_number == data.item_number,
            ItemMaster.id != item_id
        ).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Item number {data.item_number} already exists")

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)

        db.commit()
        db.refresh(item)

        logger.info(f"Item {item.item_number} updated by {user.email}")
        return item_to_response(item)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Soft delete an item (set is_active to False)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    item = db.query(ItemMaster).filter(
        ItemMaster.id == item_id,
        ItemMaster.company_id == user.company_id
    ).first()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Check if item has stock
    total_stock = db.query(func.sum(ItemStock.quantity_on_hand)).filter(
        ItemStock.item_id == item_id
    ).scalar() or 0

    if total_stock > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete item with {total_stock} units in stock. Transfer or adjust stock first."
        )

    item.is_active = False
    db.commit()

    return {"success": True, "message": f"Item {item.item_number} deactivated"}


# ============ Item Alias Endpoints ============

class ItemAliasCreate(BaseModel):
    alias_code: str
    alias_description: Optional[str] = None
    vendor_id: Optional[int] = None
    notes: Optional[str] = None


@router.get("/items/{item_id}/aliases")
async def get_item_aliases(
    item_id: int,
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all aliases for an item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify item exists and belongs to company
    item = db.query(ItemMaster).filter(
        ItemMaster.id == item_id,
        ItemMaster.company_id == user.company_id
    ).first()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    query = db.query(ItemAlias).filter(ItemAlias.item_id == item_id)
    if not include_inactive:
        query = query.filter(ItemAlias.is_active == True)

    aliases = query.order_by(ItemAlias.created_at.desc()).all()

    return [
        {
            "id": alias.id,
            "alias_code": alias.alias_code,
            "alias_description": alias.alias_description,
            "vendor_id": alias.vendor_id,
            "vendor_name": alias.vendor.name if alias.vendor else None,
            "source": alias.source,
            "notes": alias.notes,
            "is_active": alias.is_active,
            "created_at": alias.created_at.isoformat() if alias.created_at else None
        }
        for alias in aliases
    ]


@router.post("/items/{item_id}/aliases")
async def add_item_alias(
    item_id: int,
    data: ItemAliasCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add an alias to an item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify item exists and belongs to company
    item = db.query(ItemMaster).filter(
        ItemMaster.id == item_id,
        ItemMaster.company_id == user.company_id
    ).first()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Check if alias already exists for this company
    existing = db.query(ItemAlias).filter(
        ItemAlias.company_id == user.company_id,
        func.upper(ItemAlias.alias_code) == data.alias_code.strip().upper()
    ).first()

    if existing:
        if existing.item_id == item_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This alias already exists for this item")
        else:
            # Get the other item's info
            other_item = db.query(ItemMaster).filter(ItemMaster.id == existing.item_id).first()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alias '{data.alias_code}' already exists for item '{other_item.item_number if other_item else 'unknown'}'"
            )

    alias = ItemAlias(
        company_id=user.company_id,
        item_id=item_id,
        alias_code=data.alias_code.strip(),
        alias_description=data.alias_description,
        vendor_id=data.vendor_id,
        notes=data.notes,
        source="manual",
        created_by=user.id
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)

    return {
        "success": True,
        "message": f"Alias '{alias.alias_code}' added to item",
        "alias": {
            "id": alias.id,
            "alias_code": alias.alias_code,
            "alias_description": alias.alias_description,
            "vendor_id": alias.vendor_id,
            "source": alias.source,
            "created_at": alias.created_at.isoformat() if alias.created_at else None
        }
    }


@router.delete("/items/{item_id}/aliases/{alias_id}")
async def delete_item_alias(
    item_id: int,
    alias_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an alias from an item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    alias = db.query(ItemAlias).filter(
        ItemAlias.id == alias_id,
        ItemAlias.item_id == item_id,
        ItemAlias.company_id == user.company_id
    ).first()

    if not alias:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found")

    alias_code = alias.alias_code
    db.delete(alias)
    db.commit()

    return {"success": True, "message": f"Alias '{alias_code}' deleted"}


# ============ Item Ledger Endpoints ============

@router.get("/items/{item_id}/ledger")
async def get_item_ledger(
    item_id: int,
    transaction_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    warehouse_id: Optional[int] = None,
    hhd_id: Optional[int] = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get ledger entries for an item"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(ItemLedger).filter(
        ItemLedger.company_id == user.company_id,
        ItemLedger.item_id == item_id
    )

    if transaction_type:
        query = query.filter(ItemLedger.transaction_type == transaction_type)
    if from_date:
        query = query.filter(ItemLedger.transaction_date >= from_date)
    if to_date:
        query = query.filter(ItemLedger.transaction_date <= to_date)
    if warehouse_id:
        query = query.filter(
            or_(
                ItemLedger.from_warehouse_id == warehouse_id,
                ItemLedger.to_warehouse_id == warehouse_id
            )
        )
    if hhd_id:
        query = query.filter(
            or_(
                ItemLedger.from_hhd_id == hhd_id,
                ItemLedger.to_hhd_id == hhd_id
            )
        )

    entries = query.order_by(ItemLedger.transaction_date.desc()).limit(limit).all()

    return [
        {
            "id": e.id,
            "transaction_number": e.transaction_number,
            "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
            "transaction_type": e.transaction_type,
            "quantity": decimal_to_float(e.quantity),
            "unit": e.unit,
            "unit_cost": decimal_to_float(e.unit_cost),
            "total_cost": decimal_to_float(e.total_cost),
            "from_warehouse_id": e.from_warehouse_id,
            "from_warehouse_name": e.from_warehouse.name if e.from_warehouse else None,
            "to_warehouse_id": e.to_warehouse_id,
            "to_warehouse_name": e.to_warehouse.name if e.to_warehouse else None,
            "from_hhd_id": e.from_hhd_id,
            "from_hhd_code": e.from_hhd.device_code if e.from_hhd else None,
            "to_hhd_id": e.to_hhd_id,
            "to_hhd_code": e.to_hhd.device_code if e.to_hhd else None,
            "invoice_id": e.invoice_id,
            "work_order_id": e.work_order_id,
            "transfer_id": e.transfer_id,
            "balance_after": decimal_to_float(e.balance_after),
            "notes": e.notes,
            "created_by_name": e.creator.name if e.creator else None,
            "created_at": e.created_at.isoformat() if e.created_at else None
        }
        for e in entries
    ]


# ============ All Ledger Entries Endpoint ============

@router.get("/item-ledger/")
async def get_all_ledger_entries(
    item_id: Optional[int] = None,
    transaction_type: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    warehouse_id: Optional[int] = None,
    hhd_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all ledger entries with filters"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(ItemLedger).options(
        joinedload(ItemLedger.item),
        joinedload(ItemLedger.from_warehouse),
        joinedload(ItemLedger.to_warehouse),
        joinedload(ItemLedger.from_hhd),
        joinedload(ItemLedger.to_hhd),
        joinedload(ItemLedger.creator)
    ).filter(ItemLedger.company_id == user.company_id)

    if item_id:
        query = query.filter(ItemLedger.item_id == item_id)

    if transaction_type:
        query = query.filter(ItemLedger.transaction_type == transaction_type)

    if from_date:
        query = query.filter(ItemLedger.transaction_date >= from_date)

    if to_date:
        query = query.filter(ItemLedger.transaction_date <= to_date)

    if warehouse_id:
        query = query.filter(
            or_(
                ItemLedger.from_warehouse_id == warehouse_id,
                ItemLedger.to_warehouse_id == warehouse_id
            )
        )

    if hhd_id:
        query = query.filter(
            or_(
                ItemLedger.from_hhd_id == hhd_id,
                ItemLedger.to_hhd_id == hhd_id
            )
        )

    if search:
        search_term = f"%{search}%"
        query = query.join(ItemLedger.item).filter(
            or_(
                ItemMaster.item_number.ilike(search_term),
                ItemMaster.description.ilike(search_term),
                ItemLedger.transaction_number.ilike(search_term)
            )
        )

    # Get total count for pagination
    total_count = query.count()

    # Get paginated results
    entries = query.order_by(ItemLedger.transaction_date.desc(), ItemLedger.id.desc()).offset(offset).limit(limit).all()

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "entries": [
            {
                "id": e.id,
                "transaction_number": e.transaction_number,
                "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
                "transaction_type": e.transaction_type,
                "item_id": e.item_id,
                "item_number": e.item.item_number if e.item else None,
                "item_description": e.item.description if e.item else None,
                "quantity": decimal_to_float(e.quantity),
                "unit": e.unit,
                "unit_cost": decimal_to_float(e.unit_cost),
                "total_cost": decimal_to_float(e.total_cost),
                "from_warehouse_id": e.from_warehouse_id,
                "from_warehouse_name": e.from_warehouse.name if e.from_warehouse else None,
                "to_warehouse_id": e.to_warehouse_id,
                "to_warehouse_name": e.to_warehouse.name if e.to_warehouse else None,
                "from_hhd_id": e.from_hhd_id,
                "from_hhd_code": e.from_hhd.device_code if e.from_hhd else None,
                "to_hhd_id": e.to_hhd_id,
                "to_hhd_code": e.to_hhd.device_code if e.to_hhd else None,
                "invoice_id": e.invoice_id,
                "work_order_id": e.work_order_id,
                "transfer_id": e.transfer_id,
                "balance_after": decimal_to_float(e.balance_after),
                "notes": e.notes,
                "created_by_name": e.creator.name if e.creator else None,
                "created_at": e.created_at.isoformat() if e.created_at else None
            }
            for e in entries
        ]
    }


# ============ Stock Adjustment Endpoints ============

@router.post("/items/adjust-stock")
async def adjust_stock(
    data: StockAdjustmentCreate,
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Manually adjust stock levels (for corrections, counts, etc.)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    if not data.warehouse_id and not data.hhd_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must specify warehouse_id or hhd_id")

    item = db.query(ItemMaster).filter(
        ItemMaster.id == data.item_id,
        ItemMaster.company_id == user.company_id
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    try:
        transaction_type = "ADJUSTMENT_PLUS" if data.quantity > 0 else "ADJUSTMENT_MINUS"
        notes = f"Reason: {data.reason}"
        if data.notes:
            notes += f" | {data.notes}"

        ledger_entry = update_stock_and_create_ledger(
            db=db,
            company_id=user.company_id,
            item_id=data.item_id,
            quantity=abs(data.quantity),
            transaction_type=transaction_type,
            user_id=user.id,
            warehouse_id=data.warehouse_id,
            hhd_id=data.hhd_id,
            from_warehouse_id=data.warehouse_id if data.quantity < 0 else None,
            to_warehouse_id=data.warehouse_id if data.quantity > 0 else None,
            from_hhd_id=data.hhd_id if data.quantity < 0 else None,
            to_hhd_id=data.hhd_id if data.quantity > 0 else None,
            unit_cost=float(item.unit_cost) if item.unit_cost else None,
            notes=notes
        )

        db.commit()

        return {
            "success": True,
            "message": f"Stock adjusted by {data.quantity} units",
            "transaction_number": ledger_entry.transaction_number
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============ Transfer Endpoints ============

@router.get("/transfers/")
async def get_transfers(
    status_filter: Optional[str] = None,
    from_warehouse_id: Optional[int] = None,
    to_hhd_id: Optional[int] = None,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all transfers for the company (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # For HHD authentication, force filter by to_hhd_id
    if isinstance(auth_context, HHDContext):
        to_hhd_id = auth_context.device.id

    query = db.query(ItemTransfer).filter(ItemTransfer.company_id == auth_context.company_id)

    if status_filter:
        query = query.filter(ItemTransfer.status == status_filter)
    if from_warehouse_id:
        query = query.filter(ItemTransfer.from_warehouse_id == from_warehouse_id)
    if to_hhd_id:
        query = query.filter(ItemTransfer.to_hhd_id == to_hhd_id)

    transfers = query.order_by(ItemTransfer.created_at.desc()).all()

    return [
        {
            "id": t.id,
            "transfer_number": t.transfer_number,
            "transfer_date": t.transfer_date.isoformat() if t.transfer_date else None,
            "status": t.status,
            "from_warehouse_id": t.from_warehouse_id,
            "from_warehouse_name": t.from_warehouse.name if t.from_warehouse else None,
            "to_warehouse_id": t.to_warehouse_id,
            "to_warehouse_name": t.to_warehouse.name if t.to_warehouse else None,
            "to_hhd_id": t.to_hhd_id,
            "to_hhd_code": t.to_hhd.device_code if t.to_hhd else None,
            "lines_count": len(t.lines),
            "notes": t.notes,
            "created_at": t.created_at.isoformat() if t.created_at else None
        }
        for t in transfers
    ]


@router.get("/transfers/{transfer_id}")
async def get_transfer(
    transfer_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a specific transfer with lines (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    transfer = db.query(ItemTransfer).options(
        joinedload(ItemTransfer.lines).joinedload(ItemTransferLine.item),
        joinedload(ItemTransfer.from_warehouse),
        joinedload(ItemTransfer.to_warehouse),
        joinedload(ItemTransfer.to_hhd)
    ).filter(
        ItemTransfer.id == transfer_id,
        ItemTransfer.company_id == auth_context.company_id
    ).first()

    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")

    # For HHD authentication, verify the transfer is to this HHD
    if isinstance(auth_context, HHDContext):
        if transfer.to_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transfer not assigned to this device")

    return {
        "id": transfer.id,
        "transfer_number": transfer.transfer_number,
        "transfer_date": transfer.transfer_date.isoformat() if transfer.transfer_date else None,
        "status": transfer.status,
        "from_warehouse_id": transfer.from_warehouse_id,
        "from_warehouse_name": transfer.from_warehouse.name if transfer.from_warehouse else None,
        "to_warehouse_id": transfer.to_warehouse_id,
        "to_warehouse_name": transfer.to_warehouse.name if transfer.to_warehouse else None,
        "to_hhd_id": transfer.to_hhd_id,
        "to_hhd_code": transfer.to_hhd.device_code if transfer.to_hhd else None,
        "notes": transfer.notes,
        "lines": [
            {
                "id": line.id,
                "item_id": line.item_id,
                "item_number": line.item.item_number if line.item else None,
                "item_description": line.item.description if line.item else None,
                "quantity_requested": decimal_to_float(line.quantity_requested),
                "quantity_transferred": decimal_to_float(line.quantity_transferred),
                "unit": line.unit or (line.item.unit if line.item else "pcs"),
                "unit_cost": decimal_to_float(line.unit_cost),
                "notes": line.notes
            }
            for line in transfer.lines
        ],
        "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
        "completed_at": transfer.completed_at.isoformat() if transfer.completed_at else None
    }


@router.post("/transfers/")
async def create_transfer(
    data: ItemTransferCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new stock transfer"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    if not data.to_warehouse_id and not data.to_hhd_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must specify destination warehouse or HHD")

    if not data.lines or len(data.lines) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transfer must have at least one line item")

    # Validate source warehouse
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == data.from_warehouse_id,
        Warehouse.company_id == user.company_id
    ).first()
    if not warehouse:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source warehouse not found")

    try:
        transfer = ItemTransfer(
            company_id=user.company_id,
            transfer_number=generate_transfer_number(db, user.company_id),
            transfer_date=datetime.utcnow(),
            status="draft",
            from_warehouse_id=data.from_warehouse_id,
            to_warehouse_id=data.to_warehouse_id,
            to_hhd_id=data.to_hhd_id,
            notes=data.notes,
            created_by=user.id
        )
        db.add(transfer)
        db.flush()

        for line_data in data.lines:
            item = db.query(ItemMaster).filter(
                ItemMaster.id == line_data.get('item_id'),
                ItemMaster.company_id == user.company_id
            ).first()
            if not item:
                continue

            line = ItemTransferLine(
                transfer_id=transfer.id,
                item_id=line_data.get('item_id'),
                quantity_requested=line_data.get('quantity_requested'),
                unit=item.unit,
                unit_cost=float(item.unit_cost) if item.unit_cost else None,
                notes=line_data.get('notes')
            )
            db.add(line)

        db.commit()
        db.refresh(transfer)

        return {"success": True, "transfer_id": transfer.id, "transfer_number": transfer.transfer_number}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/transfers/{transfer_id}/complete")
async def complete_transfer(
    transfer_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Complete a transfer and update stock levels (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    transfer = db.query(ItemTransfer).options(
        joinedload(ItemTransfer.lines)
    ).filter(
        ItemTransfer.id == transfer_id,
        ItemTransfer.company_id == auth_context.company_id
    ).first()

    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")

    # For HHD authentication, verify the transfer is to this HHD
    if isinstance(auth_context, HHDContext):
        if transfer.to_hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Transfer not assigned to this device")

    if transfer.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transfer already completed")

    try:
        for line in transfer.lines:
            # Check source stock
            source_stock = db.query(ItemStock).filter(
                ItemStock.item_id == line.item_id,
                ItemStock.warehouse_id == transfer.from_warehouse_id
            ).first()

            if not source_stock or float(source_stock.quantity_on_hand or 0) < float(line.quantity_requested):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient stock for item {line.item.item_number if line.item else line.item_id}"
                )

            # Use the source warehouse's weighted average cost for the transfer
            # This ensures the cost follows the inventory accurately
            transfer_unit_cost = float(source_stock.average_cost) if source_stock.average_cost else (
                float(line.unit_cost) if line.unit_cost else None
            )

            # Create TRANSFER_OUT ledger entry (from source)
            update_stock_and_create_ledger(
                db=db,
                company_id=auth_context.company_id,
                item_id=line.item_id,
                quantity=float(line.quantity_requested),
                transaction_type="TRANSFER_OUT",
                user_id=auth_context.id,
                from_warehouse_id=transfer.from_warehouse_id,
                transfer_id=transfer.id,
                unit_cost=transfer_unit_cost,
                notes=f"Transfer {transfer.transfer_number}"
            )

            # Create TRANSFER_IN ledger entry (to destination)
            # Use the same weighted average cost from source
            update_stock_and_create_ledger(
                db=db,
                company_id=auth_context.company_id,
                item_id=line.item_id,
                quantity=float(line.quantity_requested),
                transaction_type="TRANSFER_IN",
                user_id=auth_context.id,
                to_warehouse_id=transfer.to_warehouse_id,
                to_hhd_id=transfer.to_hhd_id,
                transfer_id=transfer.id,
                unit_cost=transfer_unit_cost,
                notes=f"Transfer {transfer.transfer_number}"
            )

            # Update line with actual quantity transferred and cost used
            line.quantity_transferred = line.quantity_requested
            line.unit_cost = transfer_unit_cost

        # Update transfer status
        transfer.status = "completed"
        transfer.completed_at = datetime.utcnow()
        transfer.completed_by = auth_context.id

        db.commit()

        return {"success": True, "message": f"Transfer {transfer.transfer_number} completed"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============ Warehouse Stock View ============

@router.get("/warehouses/{warehouse_id}/stock")
async def get_warehouse_stock(
    warehouse_id: int,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all stock levels for a warehouse"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.company_id == user.company_id
    ).first()
    if not warehouse:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found")

    query = db.query(ItemStock).options(
        joinedload(ItemStock.item).joinedload(ItemMaster.category)
    ).filter(
        ItemStock.warehouse_id == warehouse_id,
        ItemStock.quantity_on_hand > 0
    )

    stocks = query.all()

    result = []
    for stock in stocks:
        item = stock.item
        if not item:
            continue

        # Apply filters
        if search:
            search_lower = search.lower()
            if not (search_lower in item.item_number.lower() or
                    search_lower in item.description.lower() or
                    (item.search_text and search_lower in item.search_text.lower())):
                continue

        if category_id and item.category_id != category_id:
            continue

        result.append({
            "item_id": item.id,
            "item_number": item.item_number,
            "description": item.description,
            "category": item.category.name if item.category else None,
            "unit": item.unit,
            "quantity_on_hand": decimal_to_float(stock.quantity_on_hand),
            "quantity_reserved": decimal_to_float(stock.quantity_reserved),
            "average_cost": decimal_to_float(stock.average_cost),
            "last_cost": decimal_to_float(stock.last_cost),
            "minimum_stock_level": item.minimum_stock_level,
            "is_low_stock": decimal_to_float(stock.quantity_on_hand) <= (item.minimum_stock_level or 0)
        })

    return {
        "warehouse": {
            "id": warehouse.id,
            "name": warehouse.name,
            "code": warehouse.code
        },
        "items": result,
        "total_items": len(result)
    }


# ============ HHD Stock View ============

@router.get("/hhd/{hhd_id}/stock")
async def get_hhd_stock(
    hhd_id: int,
    auth_context = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all stock levels for a handheld device (supports both admin and HHD authentication)"""
    if not auth_context.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # For HHD authentication, verify the request is for this HHD
    if isinstance(auth_context, HHDContext):
        if hhd_id != auth_context.device.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only view your own device stock")

    hhd = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == hhd_id,
        HandHeldDevice.company_id == auth_context.company_id
    ).first()
    if not hhd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HHD not found")

    # Check direct HHD stock first
    stocks = db.query(ItemStock).options(
        joinedload(ItemStock.item).joinedload(ItemMaster.category)
    ).filter(
        ItemStock.handheld_device_id == hhd_id,
        ItemStock.quantity_on_hand > 0
    ).all()

    # If no direct HHD stock, check linked warehouse stock
    if not stocks and hhd.warehouse_id:
        stocks = db.query(ItemStock).options(
            joinedload(ItemStock.item).joinedload(ItemMaster.category)
        ).filter(
            ItemStock.warehouse_id == hhd.warehouse_id,
            ItemStock.quantity_on_hand > 0
        ).all()

    items = []
    for stock in stocks:
        if stock.item:
            on_hand = decimal_to_float(stock.quantity_on_hand) or 0
            reserved = decimal_to_float(stock.quantity_reserved) or 0
            available = on_hand - reserved

            items.append({
                "item_id": stock.item.id,
                "item_number": stock.item.item_number,
                "description": stock.item.description,
                "category": stock.item.category.name if stock.item.category else None,
                "unit": stock.item.unit,
                "quantity_on_hand": on_hand,
                "quantity_reserved": reserved,
                "quantity_available": available,
                "unit_cost": decimal_to_float(stock.item.unit_cost),
                "last_movement_date": stock.last_movement_date.isoformat() if stock.last_movement_date else None
            })

    return {
        "hhd": {
            "id": hhd.id,
            "device_code": hhd.device_code,
            "device_name": hhd.device_name,
            "assigned_technician": hhd.assigned_technician.name if hhd.assigned_technician else None
        },
        "items": items,
        "total_items": len(items)
    }


@router.get("/hhd/{hhd_id}/ledger")
async def get_hhd_ledger(
    hhd_id: int,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get ledger entries for a handheld device - shows all stock movements"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    hhd = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == hhd_id,
        HandHeldDevice.company_id == user.company_id
    ).first()
    if not hhd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HHD not found")

    entries = db.query(ItemLedger).options(
        joinedload(ItemLedger.item)
    ).filter(
        or_(
            ItemLedger.from_hhd_id == hhd_id,
            ItemLedger.to_hhd_id == hhd_id
        )
    ).order_by(ItemLedger.transaction_date.desc()).limit(limit).all()

    return [
        {
            "id": e.id,
            "transaction_number": e.transaction_number,
            "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
            "transaction_type": e.transaction_type,
            "item_id": e.item_id,
            "item_number": e.item.item_number if e.item else None,
            "item_description": e.item.description if e.item else None,
            "quantity": decimal_to_float(e.quantity),
            "unit": e.unit,
            "work_order_id": e.work_order_id,
            "notes": e.notes
        }
        for e in entries
    ]


# ============ Import Endpoint ============

@router.post("/items/import")
async def import_items_from_excel(
    file: UploadFile = File(...),
    user: User = Depends(require_admin_or_accounting),
    db: Session = Depends(get_db)
):
    """Import items from Excel file (XML format from MMG)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    content = await file.read()
    content_str = content.decode('utf-8', errors='ignore')

    # Parse XML Excel format
    row_pattern = r'<Row[^>]*>(.*?)</Row>'
    cell_pattern = r'<Data[^>]*>([^<]*)</Data>'

    rows = re.findall(row_pattern, content_str, re.DOTALL)

    if len(rows) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File appears to be empty or invalid")

    # Get category code to ID mapping
    categories = db.query(ItemCategory).filter(ItemCategory.company_id == user.company_id).all()
    category_map = {c.code: c.id for c in categories}

    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []

    # Skip header row
    for i, row_content in enumerate(rows[1:], start=2):
        try:
            cells = re.findall(cell_pattern, row_content)
            if len(cells) < 5:
                continue

            # Map columns based on MMG format
            # Col 0: Short Item No
            # Col 2: Item Number
            # Col 3: Description
            # Col 4: Description 2
            # Col 9: Sales Code 2 (category)

            short_item_no = int(cells[0]) if cells[0] and cells[0].isdigit() else None
            item_number = cells[2] if len(cells) > 2 else None
            description = cells[3] if len(cells) > 3 else ""
            description2 = cells[4].strip() if len(cells) > 4 and cells[4].strip() else ""
            category_code = cells[9] if len(cells) > 9 else None

            if not item_number:
                continue

            # Concatenate descriptions
            full_description = description
            if description2:
                full_description = f"{description} {description2}"

            # Find category
            category_id = category_map.get(category_code) if category_code else None

            # Check if item exists
            existing = db.query(ItemMaster).filter(
                ItemMaster.company_id == user.company_id,
                ItemMaster.item_number == item_number
            ).first()

            if existing:
                # Update existing
                existing.description = full_description
                existing.short_item_no = short_item_no
                existing.search_text = full_description
                if category_id:
                    existing.category_id = category_id
                updated_count += 1
            else:
                # Create new
                item = ItemMaster(
                    company_id=user.company_id,
                    item_number=item_number,
                    short_item_no=short_item_no,
                    description=full_description,
                    search_text=full_description,
                    category_id=category_id,
                    created_by=user.id
                )
                db.add(item)
                created_count += 1

        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")
            skipped_count += 1
            continue

    db.commit()

    return {
        "success": True,
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": errors[:10] if errors else []  # Return first 10 errors
    }


# ============ Invoice Receiving Endpoints ============

@router.post("/invoices/{invoice_id}/receive-item")
async def receive_invoice_item(
    invoice_id: int,
    data: ReceiveInvoiceItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Receive a single invoice item to a specified warehouse.
    Creates stock and ledger entries with weighted average cost calculation.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get the invoice item
    invoice_item = db.query(InvoiceItem).filter(
        InvoiceItem.id == data.invoice_item_id,
        InvoiceItem.invoice_id == invoice_id
    ).first()

    if not invoice_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice item not found")

    # Validate warehouse belongs to company
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == data.warehouse_id,
        Warehouse.company_id == user.company_id,
        Warehouse.is_active == True
    ).first()

    if not warehouse:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found or inactive")

    # Check quantity
    already_received = float(invoice_item.quantity_received or 0)
    invoice_qty = float(invoice_item.quantity or 0)
    remaining = invoice_qty - already_received

    if data.quantity_to_receive > remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot receive {data.quantity_to_receive} units. Only {remaining} remaining."
        )

    # If item_id is provided, use it. Otherwise, try to find or create the item
    item_id = data.item_id or invoice_item.item_id

    if not item_id:
        # Try to find item by item number
        if invoice_item.item_number:
            existing_item = db.query(ItemMaster).filter(
                ItemMaster.company_id == user.company_id,
                ItemMaster.item_number == invoice_item.item_number
            ).first()
            if existing_item:
                item_id = existing_item.id

    if not item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No item linked to this invoice line. Please link or create an item first."
        )

    try:
        unit_cost = float(invoice_item.unit_price) if invoice_item.unit_price else None

        # Create ledger entry and update stock
        ledger_entry = update_stock_and_create_ledger(
            db=db,
            company_id=user.company_id,
            item_id=item_id,
            quantity=data.quantity_to_receive,
            transaction_type="RECEIVE_INVOICE",
            user_id=user.id,
            to_warehouse_id=data.warehouse_id,
            invoice_id=invoice_id,
            unit_cost=unit_cost,
            notes=data.notes or f"Received from invoice"
        )

        # Update invoice item status
        invoice_item.quantity_received = already_received + data.quantity_to_receive
        invoice_item.received_to_warehouse_id = data.warehouse_id
        invoice_item.received_by = user.id
        invoice_item.received_at = datetime.utcnow()

        new_received = float(invoice_item.quantity_received)
        if new_received >= invoice_qty:
            invoice_item.receive_status = "received"
        elif new_received > 0:
            invoice_item.receive_status = "partial"

        # Link item to invoice item if not already linked
        if not invoice_item.item_id:
            invoice_item.item_id = item_id

        db.commit()

        return {
            "success": True,
            "message": f"Received {data.quantity_to_receive} units to {warehouse.name}",
            "transaction_number": ledger_entry.transaction_number,
            "quantity_received": new_received,
            "quantity_remaining": invoice_qty - new_received,
            "receive_status": invoice_item.receive_status
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error receiving invoice item: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/invoices/{invoice_id}/confirm")
async def confirm_invoice_to_main_warehouse(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Confirm an invoice and auto-receive all linked items to the main warehouse.
    This creates stock and ledger entries for all invoice items that have linked items.
    Items without links are skipped but noted in the response.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get the main warehouse for the company
    main_warehouse = db.query(Warehouse).filter(
        Warehouse.company_id == user.company_id,
        Warehouse.is_main == True,
        Warehouse.is_active == True
    ).first()

    if not main_warehouse:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No main warehouse set. Please designate a main warehouse before confirming invoices."
        )

    # Get all invoice items for this invoice
    invoice_items = db.query(InvoiceItem).filter(
        InvoiceItem.invoice_id == invoice_id
    ).all()

    if not invoice_items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No invoice items found")

    received_items = []
    skipped_items = []
    errors = []

    try:
        for invoice_item in invoice_items:
            # Skip already fully received items
            already_received = float(invoice_item.quantity_received or 0)
            invoice_qty = float(invoice_item.quantity or 0)
            remaining = invoice_qty - already_received

            if remaining <= 0:
                skipped_items.append({
                    "id": invoice_item.id,
                    "description": invoice_item.item_description,
                    "reason": "Already fully received"
                })
                continue

            # Check if item is linked
            item_id = invoice_item.item_id

            # Try to find item by item number if not linked
            if not item_id and invoice_item.item_number:
                existing_item = db.query(ItemMaster).filter(
                    ItemMaster.company_id == user.company_id,
                    ItemMaster.item_number == invoice_item.item_number
                ).first()
                if existing_item:
                    item_id = existing_item.id
                    invoice_item.item_id = item_id  # Link for future

            if not item_id:
                skipped_items.append({
                    "id": invoice_item.id,
                    "description": invoice_item.item_description,
                    "item_number": invoice_item.item_number,
                    "reason": "No linked item in Item Master"
                })
                continue

            try:
                unit_cost = float(invoice_item.unit_price) if invoice_item.unit_price else None

                # Create ledger entry and update stock
                ledger_entry = update_stock_and_create_ledger(
                    db=db,
                    company_id=user.company_id,
                    item_id=item_id,
                    quantity=remaining,
                    transaction_type="RECEIVE_INVOICE",
                    user_id=user.id,
                    to_warehouse_id=main_warehouse.id,
                    invoice_id=invoice_id,
                    unit_cost=unit_cost,
                    notes=f"Auto-received from invoice confirmation"
                )

                # Update invoice item status
                invoice_item.quantity_received = invoice_qty
                invoice_item.received_to_warehouse_id = main_warehouse.id
                invoice_item.received_by = user.id
                invoice_item.received_at = datetime.utcnow()
                invoice_item.receive_status = "received"

                received_items.append({
                    "id": invoice_item.id,
                    "description": invoice_item.item_description,
                    "quantity": remaining,
                    "transaction_number": ledger_entry.transaction_number
                })

            except Exception as item_error:
                errors.append({
                    "id": invoice_item.id,
                    "description": invoice_item.item_description,
                    "error": str(item_error)
                })

        db.commit()

        return {
            "success": True,
            "message": f"Invoice confirmed. {len(received_items)} items received to {main_warehouse.name}.",
            "main_warehouse": {
                "id": main_warehouse.id,
                "name": main_warehouse.name
            },
            "received_items": received_items,
            "skipped_items": skipped_items,
            "errors": errors
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error confirming invoice: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/invoices/{invoice_id}/items")
async def get_invoice_items(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all items from an invoice with their receiving status"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    invoice_items = db.query(InvoiceItem).filter(
        InvoiceItem.invoice_id == invoice_id
    ).all()

    return [
        {
            "id": item.id,
            "item_id": item.item_id,
            "item_number": item.item_number,
            "item_description": item.item_description,
            "quantity": decimal_to_float(item.quantity),
            "unit": item.unit,
            "unit_price": decimal_to_float(item.unit_price),
            "total_price": decimal_to_float(item.total_price),
            "quantity_received": decimal_to_float(item.quantity_received),
            "receive_status": item.receive_status,
            "received_to_warehouse_id": item.received_to_warehouse_id,
            "received_to_warehouse_name": item.warehouse.name if item.warehouse else None,
            "received_at": item.received_at.isoformat() if item.received_at else None,
            "linked_item": {
                "id": item.item.id,
                "item_number": item.item.item_number,
                "description": item.item.description
            } if item.item else None
        }
        for item in invoice_items
    ]


class LinkInvoiceItemRequest(BaseModel):
    item_id: int
    auto_receive: Optional[bool] = True


@router.post("/invoice-items/{invoice_item_id}/link")
async def link_invoice_item_to_master(
    invoice_item_id: int,
    data: LinkInvoiceItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Link an invoice item to an Item Master item.
    Optionally auto-receive to main warehouse.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get the invoice item
    invoice_item = db.query(InvoiceItem).filter(
        InvoiceItem.id == invoice_item_id
    ).first()

    if not invoice_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice item not found")

    # Validate the item belongs to the company
    master_item = db.query(ItemMaster).filter(
        ItemMaster.id == data.item_id,
        ItemMaster.company_id == user.company_id,
        ItemMaster.is_active == True
    ).first()

    if not master_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item Master item not found")

    # Link the invoice item to the master item
    invoice_item.item_id = master_item.id
    db.flush()

    # Save the vendor/supplier item code as an alias for future automatic matching
    alias_created = False
    if invoice_item.item_number:
        # Check if this alias already exists
        existing_alias = db.query(ItemAlias).filter(
            ItemAlias.company_id == user.company_id,
            ItemAlias.alias_code == invoice_item.item_number
        ).first()

        if not existing_alias:
            # Get vendor_id from the invoice if available
            from app.models import ProcessedImage
            invoice = db.query(ProcessedImage).filter(
                ProcessedImage.id == invoice_item.invoice_id
            ).first()
            vendor_id = invoice.vendor_id if invoice else None

            # Create new alias
            new_alias = ItemAlias(
                company_id=user.company_id,
                item_id=master_item.id,
                alias_code=invoice_item.item_number,
                alias_description=invoice_item.item_description,
                vendor_id=vendor_id,
                source="invoice_link",
                created_by=user.id
            )
            db.add(new_alias)
            db.flush()
            alias_created = True
            logger.info(f"Created alias '{invoice_item.item_number}' for item {master_item.item_number}")

    result = {
        "success": True,
        "message": f"Invoice item linked to '{master_item.description}'",
        "invoice_item_id": invoice_item.id,
        "linked_item_id": master_item.id,
        "linked_item_number": master_item.item_number,
        "linked_item_description": master_item.description,
        "alias_created": alias_created,
        "alias_code": invoice_item.item_number if alias_created else None,
        "auto_received": False,
        "receive_details": None
    }

    # Auto-receive to main warehouse if requested
    if data.auto_receive:
        quantity = float(invoice_item.quantity or 0)
        already_received = float(invoice_item.quantity_received or 0)
        remaining = quantity - already_received

        if remaining > 0:
            # Get main warehouse
            main_warehouse = db.query(Warehouse).filter(
                Warehouse.company_id == user.company_id,
                Warehouse.is_main == True,
                Warehouse.is_active == True
            ).first()

            if main_warehouse:
                try:
                    unit_cost = float(invoice_item.unit_price) if invoice_item.unit_price else None

                    # Create ledger entry and update stock
                    ledger_entry = update_stock_and_create_ledger(
                        db=db,
                        company_id=user.company_id,
                        item_id=master_item.id,
                        quantity=remaining,
                        transaction_type="RECEIVE_INVOICE",
                        user_id=user.id,
                        to_warehouse_id=main_warehouse.id,
                        invoice_id=invoice_item.invoice_id,
                        unit_cost=unit_cost,
                        notes=f"Manually linked and received from invoice"
                    )

                    # Update invoice item status
                    invoice_item.quantity_received = quantity
                    invoice_item.received_to_warehouse_id = main_warehouse.id
                    invoice_item.received_by = user.id
                    invoice_item.received_at = datetime.utcnow()
                    invoice_item.receive_status = "received"

                    # Get updated stock info
                    stock = db.query(ItemStock).filter(
                        ItemStock.item_id == master_item.id,
                        ItemStock.warehouse_id == main_warehouse.id
                    ).first()

                    result["auto_received"] = True
                    result["receive_details"] = {
                        "warehouse_id": main_warehouse.id,
                        "warehouse_name": main_warehouse.name,
                        "quantity_received": remaining,
                        "transaction_number": ledger_entry.transaction_number,
                        "new_quantity_on_hand": float(stock.quantity_on_hand) if stock else remaining,
                        "new_average_cost": float(stock.average_cost) if stock and stock.average_cost else (unit_cost or 0)
                    }
                    result["message"] = f"Item linked and {remaining} units received to {main_warehouse.name}"

                except Exception as receive_error:
                    logger.error(f"Error auto-receiving after linking: {receive_error}")
                    result["auto_received"] = False
                    result["message"] = f"Item linked but auto-receive failed: {str(receive_error)}"
            else:
                result["auto_received"] = False
                result["message"] = "Item linked but no main warehouse set for auto-receive"
        else:
            result["auto_received"] = False
            result["message"] = "Item linked (no quantity remaining to receive)"

    db.commit()
    return result


@router.get("/invoice-items/{invoice_item_id}/suggestions")
async def get_item_suggestions_for_invoice_item(
    invoice_item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get Item Master suggestions for an unlinked invoice item based on fuzzy matching.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get the invoice item
    invoice_item = db.query(InvoiceItem).filter(
        InvoiceItem.id == invoice_item_id
    ).first()

    if not invoice_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice item not found")

    if invoice_item.item_id:
        # Already linked
        return {
            "invoice_item_id": invoice_item_id,
            "already_linked": True,
            "linked_item": {
                "id": invoice_item.item.id,
                "item_number": invoice_item.item.item_number,
                "description": invoice_item.item.description
            },
            "suggestions": []
        }

    # Get all active items for the company
    items = db.query(ItemMaster).filter(
        ItemMaster.company_id == user.company_id,
        ItemMaster.is_active == True
    ).all()

    if not items:
        return {
            "invoice_item_id": invoice_item_id,
            "already_linked": False,
            "suggestions": []
        }

    # Calculate similarity for each item
    description = invoice_item.item_description or ""
    item_code = invoice_item.item_number or ""

    suggestions = []
    for item in items:
        # Calculate similarity based on description
        desc_similarity = 0.0
        if description and item.description:
            # Simple word overlap similarity
            desc_words = set(description.lower().split())
            item_words = set(item.description.lower().split())
            if desc_words and item_words:
                intersection = desc_words & item_words
                union = desc_words | item_words
                desc_similarity = len(intersection) / len(union) if union else 0

        # Check for item number similarity
        code_similarity = 0.0
        if item_code and item.item_number:
            if item_code.upper() == item.item_number.upper():
                code_similarity = 1.0
            elif item_code.upper() in item.item_number.upper() or item.item_number.upper() in item_code.upper():
                code_similarity = 0.5

        # Check for alias match
        alias_similarity = 0.0
        if item_code and item.aliases:
            for alias in item.aliases:
                if alias.is_active and alias.alias_code:
                    if item_code.upper() == alias.alias_code.upper():
                        alias_similarity = 1.0
                        break
                    elif item_code.upper() in alias.alias_code.upper() or alias.alias_code.upper() in item_code.upper():
                        alias_similarity = max(alias_similarity, 0.7)

        # Combine similarities
        best_similarity = max(desc_similarity, code_similarity, alias_similarity)

        # Determine match reason
        match_reason = ""
        if alias_similarity >= best_similarity and alias_similarity > 0:
            match_reason = "Vendor item code (alias) match"
        elif code_similarity >= desc_similarity and code_similarity > 0:
            match_reason = "Item code match"
        elif desc_similarity > 0:
            match_reason = "Description similarity"

        if best_similarity > 0.1:  # Only include if some similarity
            # Get stock level for this item
            total_stock = sum(
                float(s.quantity_on_hand or 0)
                for s in item.stock_levels
            ) if item.stock_levels else 0

            # Get category name if exists
            category_name = item.category.name if item.category else None

            suggestions.append({
                "id": item.id,
                "item_number": item.item_number,
                "short_item_no": item.short_item_no,
                "description": item.description,
                "uom": item.unit,
                "category": category_name,
                "quantity_on_hand": total_stock,
                "confidence": round(best_similarity, 2),  # Return as decimal 0-1
                "match_reason": match_reason
            })

    # Sort by confidence descending
    suggestions.sort(key=lambda x: x["confidence"], reverse=True)

    return {
        "invoice_item_id": invoice_item_id,
        "invoice_item_description": description,
        "invoice_item_number": item_code,
        "already_linked": False,
        "suggestions": suggestions[:10]  # Top 10 suggestions
    }


@router.get("/invoices/{invoice_id}/unlinked-items")
async def get_unlinked_invoice_items(
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all unlinked (not matched to Item Master) items from an invoice.
    Useful for the manual linking UI.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get unlinked invoice items
    unlinked_items = db.query(InvoiceItem).filter(
        InvoiceItem.invoice_id == invoice_id,
        InvoiceItem.item_id == None
    ).all()

    return [
        {
            "id": item.id,
            "item_number": item.item_number,
            "item_description": item.item_description,
            "quantity": decimal_to_float(item.quantity),
            "unit": item.unit,
            "unit_price": decimal_to_float(item.unit_price),
            "total_price": decimal_to_float(item.total_price),
            "receive_status": item.receive_status
        }
        for item in unlinked_items
    ]


class CreateGenericItemRequest(BaseModel):
    """Request to create a generic Item Master entry from an invoice line item"""
    category_id: Optional[int] = None
    unit: Optional[str] = "EA"
    auto_receive: Optional[bool] = True


@router.post("/invoice-items/{invoice_item_id}/create-generic")
async def create_generic_item_from_invoice(
    invoice_item_id: int,
    data: CreateGenericItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a generic Item Master entry from an unlinked invoice line item.
    This is useful when an invoice contains items not yet in the Item Master.

    The new item will:
    1. Use the invoice item description as the item description
    2. Generate a unique item number based on description
    3. Link the invoice item to the new Item Master entry
    4. Optionally auto-receive to main warehouse
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get the invoice item
    invoice_item = db.query(InvoiceItem).filter(
        InvoiceItem.id == invoice_item_id
    ).first()

    if not invoice_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice item not found")

    if invoice_item.item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice item is already linked to an Item Master entry"
        )

    # Get or validate category
    category = None
    if data.category_id:
        category = db.query(ItemCategory).filter(
            ItemCategory.id == data.category_id,
            ItemCategory.company_id == user.company_id
        ).first()
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    else:
        # Try to get or create a "General" category
        category = db.query(ItemCategory).filter(
            ItemCategory.company_id == user.company_id,
            ItemCategory.name.ilike("general")
        ).first()

        if not category:
            # Create a General category
            category = ItemCategory(
                company_id=user.company_id,
                name="General",
                description="General category for uncategorized items",
                code="GEN"
            )
            db.add(category)
            db.flush()

    # Generate item number from description
    description = invoice_item.item_description or "Generic Item"

    # Create a sanitized item number from description
    # Take first 3 chars of each word, uppercase, max 20 chars
    words = description.split()[:4]  # Max 4 words
    base_item_no = "-".join(w[:3].upper() for w in words if w)
    base_item_no = base_item_no[:20] if base_item_no else "GEN"

    # Check for uniqueness and add suffix if needed
    item_number = base_item_no
    counter = 1
    while db.query(ItemMaster).filter(
        ItemMaster.company_id == user.company_id,
        ItemMaster.item_number == item_number
    ).first():
        item_number = f"{base_item_no}-{counter}"
        counter += 1

    # Get next short_item_no
    max_short_no = db.query(func.max(ItemMaster.short_item_no)).filter(
        ItemMaster.company_id == user.company_id
    ).scalar() or 0
    short_item_no = max_short_no + 1

    # Create the new Item Master entry
    new_item = ItemMaster(
        company_id=user.company_id,
        category_id=category.id if category else None,
        item_number=item_number,
        short_item_no=short_item_no,
        description=description,
        unit=data.unit or invoice_item.unit or "EA",
        is_active=True,
        notes=f"Created from invoice line item. Original item code: {invoice_item.item_number or 'N/A'}"
    )
    db.add(new_item)
    db.flush()

    # Link the invoice item to the new Item Master entry
    invoice_item.item_id = new_item.id

    # Create an alias if the invoice item has an item code
    alias_created = False
    if invoice_item.item_number:
        # Get vendor_id from the invoice if available
        from app.models import ProcessedImage
        invoice = db.query(ProcessedImage).filter(
            ProcessedImage.id == invoice_item.invoice_id
        ).first()
        vendor_id = invoice.vendor_id if invoice else None

        new_alias = ItemAlias(
            company_id=user.company_id,
            item_id=new_item.id,
            alias_code=invoice_item.item_number,
            alias_description=invoice_item.item_description,
            vendor_id=vendor_id,
            source="generic_item_creation",
            created_by=user.id
        )
        db.add(new_alias)
        alias_created = True

    result = {
        "success": True,
        "message": f"Created new Item Master entry '{item_number}'",
        "invoice_item_id": invoice_item.id,
        "created_item": {
            "id": new_item.id,
            "item_number": new_item.item_number,
            "short_item_no": new_item.short_item_no,
            "description": new_item.description,
            "unit": new_item.unit,
            "category": category.name if category else None
        },
        "alias_created": alias_created,
        "auto_received": False,
        "receive_details": None
    }

    # Auto-receive to main warehouse if requested
    if data.auto_receive:
        quantity = float(invoice_item.quantity or 0)

        if quantity > 0:
            main_warehouse = db.query(Warehouse).filter(
                Warehouse.company_id == user.company_id,
                Warehouse.is_main == True,
                Warehouse.is_active == True
            ).first()

            if main_warehouse:
                try:
                    unit_cost = float(invoice_item.unit_price) if invoice_item.unit_price else None

                    # Create ledger entry and update stock
                    ledger_entry = update_stock_and_create_ledger(
                        db=db,
                        company_id=user.company_id,
                        item_id=new_item.id,
                        quantity=quantity,
                        transaction_type="RECEIVE_INVOICE",
                        user_id=user.id,
                        to_warehouse_id=main_warehouse.id,
                        invoice_id=invoice_item.invoice_id,
                        unit_cost=unit_cost,
                        notes=f"Initial stock from invoice - new generic item"
                    )

                    # Update invoice item status
                    invoice_item.quantity_received = quantity
                    invoice_item.received_to_warehouse_id = main_warehouse.id
                    invoice_item.received_by = user.id
                    invoice_item.received_at = datetime.utcnow()
                    invoice_item.receive_status = "received"

                    # Get updated stock info
                    stock = db.query(ItemStock).filter(
                        ItemStock.item_id == new_item.id,
                        ItemStock.warehouse_id == main_warehouse.id
                    ).first()

                    result["auto_received"] = True
                    result["receive_details"] = {
                        "warehouse_id": main_warehouse.id,
                        "warehouse_name": main_warehouse.name,
                        "quantity_received": quantity,
                        "transaction_number": ledger_entry.transaction_number,
                        "new_quantity_on_hand": float(stock.quantity_on_hand) if stock else quantity,
                        "unit_cost": unit_cost
                    }
                    result["message"] = f"Created '{item_number}' and received {quantity} units to {main_warehouse.name}"

                except Exception as receive_error:
                    logger.error(f"Error auto-receiving new generic item: {receive_error}")
                    result["auto_received"] = False
                    result["message"] = f"Item created but auto-receive failed: {str(receive_error)}"
            else:
                result["message"] = f"Created '{item_number}' (no main warehouse for auto-receive)"
        else:
            result["message"] = f"Created '{item_number}' (no quantity to receive)"

    db.commit()
    return result


# ============ Bulk Import ============

@router.post("/items/bulk-import")
async def bulk_import_items(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bulk import items from misc/item-master-mmg.xls file.
    Skips items that already exist (by item_number).
    Restricted to specific user only.
    """
    # Restrict to specific user
    if user.email != "flahham@mmg-holdings.com":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is restricted"
        )

    try:
        from lxml import etree
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="lxml not installed on server"
        )

    import os

    # Find the Excel file
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    excel_path = os.path.join(backend_dir, 'misc', 'item-master-mmg.xls')

    if not os.path.exists(excel_path):
        raise HTTPException(
            status_code=404,
            detail=f"Item master file not found at {excel_path}"
        )

    # Parse XML spreadsheet with recovery mode
    parser = etree.XMLParser(recover=True)
    tree = etree.parse(excel_path, parser)
    root = tree.getroot()

    # Find worksheet and rows
    ns = '{urn:schemas-microsoft-com:office:spreadsheet}'
    worksheets = root.findall(f'.//{ns}Worksheet')
    if not worksheets:
        raise HTTPException(status_code=500, detail="No worksheet found in file")

    table = worksheets[0].find(f'{ns}Table')
    rows = table.findall(f'{ns}Row')

    if len(rows) < 2:
        raise HTTPException(status_code=500, detail="File has no data rows")

    # Get headers from first row
    header_row = rows[0]
    headers = []
    for cell in header_row.findall(f'{ns}Cell'):
        data = cell.find(f'{ns}Data')
        headers.append(data.text if data is not None else '')

    # Create column index map
    col_map = {h: i for i, h in enumerate(headers)}

    # Get existing item numbers for this company
    existing_items = set(
        item.item_number.lower() for item in db.query(ItemMaster.item_number).filter(
            ItemMaster.company_id == user.company_id
        ).all()
    )

    created = 0
    skipped = 0
    errors = []

    # Process data rows
    for row_idx, row in enumerate(rows[1:], start=2):
        try:
            # Extract cell values
            cells = row.findall(f'{ns}Cell')
            values = [''] * len(headers)

            cell_idx = 0
            for cell in cells:
                # Handle ss:Index attribute for sparse rows
                index_attr = cell.get(f'{ns}Index')
                if index_attr:
                    cell_idx = int(index_attr) - 1

                data = cell.find(f'{ns}Data')
                if data is not None and data.text:
                    if cell_idx < len(values):
                        values[cell_idx] = data.text.strip()
                cell_idx += 1

            # Get item number
            item_number = values[col_map.get('Item Number', 2)] if 'Item Number' in col_map else ''
            if not item_number or item_number.lower() in existing_items:
                skipped += 1
                continue

            # Get description (concat Description + Description 2)
            desc1 = values[col_map.get('Description', 3)] if 'Description' in col_map else ''
            desc2 = values[col_map.get('Description 2', 4)] if 'Description 2' in col_map else ''
            description = f"{desc1} {desc2}".strip() if desc2 else desc1

            if not description:
                description = item_number  # Fallback

            # Get short item number
            short_item_str = values[col_map.get('Short Item No', 0)] if 'Short Item No' in col_map else ''
            short_item_no = None
            if short_item_str:
                try:
                    short_item_no = int(float(short_item_str))
                except:
                    pass

            # Get search text
            search_text = values[col_map.get('Search Text', 5)] if 'Search Text' in col_map else None

            # Get stocking type and line type
            stocking_type = values[col_map.get('Stocking Type', 7)] if 'Stocking Type' in col_map else 'S'
            line_type = values[col_map.get('Line Type', 6)] if 'Line Type' in col_map else 'S'

            item = ItemMaster(
                company_id=user.company_id,
                item_number=item_number,
                short_item_no=short_item_no,
                description=description[:500],
                search_text=search_text[:500] if search_text else None,
                stocking_type=stocking_type[:10] if stocking_type else 'S',
                line_type=line_type[:10] if line_type else 'S',
                is_active=True,
                created_by=user.id
            )
            db.add(item)
            existing_items.add(item_number.lower())
            created += 1

            # Commit in batches of 1000
            if created % 1000 == 0:
                db.flush()
                logger.info(f"Item import progress: {created} items created")

        except Exception as e:
            errors.append({"row": row_idx, "error": str(e)})
            if len(errors) > 100:
                break  # Stop if too many errors

    db.commit()
    logger.info(f"Bulk item import: created={created}, skipped={skipped}, errors={len(errors)}")

    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "errors": len(errors),
        "error_details": errors[:10] if errors else []
    }


# ============ Slow Moving / Non-Moving Items ============

@router.get("/item-stock/slow-moving/")
async def get_slow_moving_items(
    days_threshold: int = Query(90, description="Items not moved for this many days are slow-moving"),
    non_moving_days: int = Query(180, description="Items not moved for this many days are non-moving"),
    include_zero_stock: bool = Query(False, description="Include items with zero stock"),
    warehouse_id: Optional[int] = Query(None, description="Filter by warehouse"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search in item number or description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_or_hhd=Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """
    Get slow-moving and non-moving inventory items.
    - Slow-moving: Items with stock that haven't moved for X days (default 90)
    - Non-moving: Items with stock that haven't moved for Y days (default 180)
    """
    from datetime import timedelta

    company_id = user_or_hhd.company_id
    today = datetime.utcnow()
    slow_moving_date = today - timedelta(days=days_threshold)
    non_moving_date = today - timedelta(days=non_moving_days)

    # Base query - join ItemStock with ItemMaster
    query = db.query(
        ItemStock.id,
        ItemStock.item_id,
        ItemStock.warehouse_id,
        ItemStock.quantity_on_hand,
        ItemStock.quantity_reserved,
        ItemStock.average_cost,
        ItemStock.last_cost,
        ItemStock.last_movement_date,
        ItemMaster.item_number,
        ItemMaster.description,
        ItemMaster.unit,
        ItemMaster.category_id,
        Warehouse.name.label('warehouse_name'),
        ItemCategory.name.label('category_name')
    ).join(
        ItemMaster, ItemMaster.id == ItemStock.item_id
    ).outerjoin(
        Warehouse, Warehouse.id == ItemStock.warehouse_id
    ).outerjoin(
        ItemCategory, ItemCategory.id == ItemMaster.category_id
    ).filter(
        ItemStock.company_id == company_id,
        ItemStock.warehouse_id.isnot(None),  # Only warehouse stock, not HHD
        ItemMaster.is_active == True
    )

    # Filter: Only items that haven't moved recently (slow-moving threshold)
    query = query.filter(
        or_(
            ItemStock.last_movement_date.is_(None),
            ItemStock.last_movement_date < slow_moving_date
        )
    )

    # Filter: Include or exclude zero stock items
    if not include_zero_stock:
        query = query.filter(ItemStock.quantity_on_hand > 0)

    # Filter by warehouse
    if warehouse_id:
        query = query.filter(ItemStock.warehouse_id == warehouse_id)

    # Filter by category
    if category_id:
        query = query.filter(ItemMaster.category_id == category_id)

    # Search filter
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                ItemMaster.item_number.ilike(search_term),
                ItemMaster.description.ilike(search_term)
            )
        )

    # Get total count for pagination
    total = query.count()

    # Order by last movement date (oldest first), then by value
    query = query.order_by(
        ItemStock.last_movement_date.asc().nullsfirst(),
        (ItemStock.quantity_on_hand * ItemStock.last_cost).desc().nullslast()
    )

    # Pagination
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    # Calculate summary statistics
    summary_query = db.query(
        func.count(ItemStock.id).label('total_items'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand), 0).label('total_quantity'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand * ItemStock.last_cost), 0).label('total_value'),
        func.sum(
            case(
                (or_(ItemStock.last_movement_date.is_(None), ItemStock.last_movement_date < non_moving_date), 1),
                else_=0
            )
        ).label('non_moving_count'),
        func.sum(
            case(
                (and_(
                    ItemStock.last_movement_date.isnot(None),
                    ItemStock.last_movement_date >= non_moving_date,
                    ItemStock.last_movement_date < slow_moving_date
                ), 1),
                else_=0
            )
        ).label('slow_moving_count')
    ).join(
        ItemMaster, ItemMaster.id == ItemStock.item_id
    ).filter(
        ItemStock.company_id == company_id,
        ItemStock.warehouse_id.isnot(None),
        ItemMaster.is_active == True,
        or_(
            ItemStock.last_movement_date.is_(None),
            ItemStock.last_movement_date < slow_moving_date
        )
    )

    if not include_zero_stock:
        summary_query = summary_query.filter(ItemStock.quantity_on_hand > 0)
    if warehouse_id:
        summary_query = summary_query.filter(ItemStock.warehouse_id == warehouse_id)
    if category_id:
        summary_query = summary_query.filter(ItemMaster.category_id == category_id)

    summary = summary_query.first()

    # Format results
    result_items = []
    for item in items:
        days_since_movement = None
        movement_status = "non_moving"

        if item.last_movement_date:
            days_since_movement = (today - item.last_movement_date).days
            if days_since_movement >= non_moving_days:
                movement_status = "non_moving"
            else:
                movement_status = "slow_moving"
        else:
            movement_status = "non_moving"
            days_since_movement = None  # Never moved

        stock_value = float(item.quantity_on_hand or 0) * float(item.last_cost or 0)

        result_items.append({
            "id": item.id,
            "item_id": item.item_id,
            "item_number": item.item_number,
            "description": item.description,
            "unit": item.unit,
            "category_id": item.category_id,
            "category_name": item.category_name,
            "warehouse_id": item.warehouse_id,
            "warehouse_name": item.warehouse_name,
            "quantity_on_hand": float(item.quantity_on_hand or 0),
            "quantity_reserved": float(item.quantity_reserved or 0),
            "average_cost": float(item.average_cost or 0),
            "last_cost": float(item.last_cost or 0),
            "stock_value": round(stock_value, 2),
            "last_movement_date": item.last_movement_date.isoformat() if item.last_movement_date else None,
            "days_since_movement": days_since_movement,
            "movement_status": movement_status
        })

    return {
        "items": result_items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size
        },
        "summary": {
            "total_items": summary.total_items or 0,
            "total_quantity": float(summary.total_quantity or 0),
            "total_value": round(float(summary.total_value or 0), 2),
            "non_moving_count": summary.non_moving_count or 0,
            "slow_moving_count": summary.slow_moving_count or 0
        },
        "thresholds": {
            "slow_moving_days": days_threshold,
            "non_moving_days": non_moving_days
        }
    }


@router.get("/item-stock/movement-analysis/")
async def get_movement_analysis(
    warehouse_id: Optional[int] = Query(None, description="Filter by warehouse"),
    user_or_hhd=Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """
    Get an overview of inventory movement analysis - categorized by movement status.
    Returns counts and values for each movement category.
    """
    from datetime import timedelta

    company_id = user_or_hhd.company_id
    today = datetime.utcnow()

    # Define thresholds
    fast_moving_days = 30
    normal_moving_days = 90
    slow_moving_days = 180

    fast_date = today - timedelta(days=fast_moving_days)
    normal_date = today - timedelta(days=normal_moving_days)
    slow_date = today - timedelta(days=slow_moving_days)

    # Base filter
    base_filter = [
        ItemStock.company_id == company_id,
        ItemStock.warehouse_id.isnot(None),
        ItemStock.quantity_on_hand > 0,
        ItemMaster.is_active == True
    ]

    if warehouse_id:
        base_filter.append(ItemStock.warehouse_id == warehouse_id)

    # Query for each category
    def get_category_stats(date_from, date_to=None):
        query = db.query(
            func.count(ItemStock.id).label('count'),
            func.coalesce(func.sum(ItemStock.quantity_on_hand), 0).label('quantity'),
            func.coalesce(func.sum(ItemStock.quantity_on_hand * ItemStock.last_cost), 0).label('value')
        ).join(
            ItemMaster, ItemMaster.id == ItemStock.item_id
        ).filter(*base_filter)

        if date_from and date_to:
            query = query.filter(
                ItemStock.last_movement_date >= date_from,
                ItemStock.last_movement_date < date_to
            )
        elif date_from:
            query = query.filter(ItemStock.last_movement_date >= date_from)
        elif date_to:
            query = query.filter(
                or_(
                    ItemStock.last_movement_date.is_(None),
                    ItemStock.last_movement_date < date_to
                )
            )

        return query.first()

    # Non-moving: never moved or > 180 days
    non_moving = db.query(
        func.count(ItemStock.id).label('count'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand), 0).label('quantity'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand * ItemStock.last_cost), 0).label('value')
    ).join(
        ItemMaster, ItemMaster.id == ItemStock.item_id
    ).filter(
        *base_filter,
        or_(
            ItemStock.last_movement_date.is_(None),
            ItemStock.last_movement_date < slow_date
        )
    ).first()

    # Slow-moving: 90-180 days
    slow_moving = get_category_stats(slow_date, normal_date)

    # Normal-moving: 30-90 days
    normal_moving = get_category_stats(normal_date, fast_date)

    # Fast-moving: < 30 days
    fast_moving = get_category_stats(fast_date, None)

    # Total inventory
    total = db.query(
        func.count(ItemStock.id).label('count'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand), 0).label('quantity'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand * ItemStock.last_cost), 0).label('value')
    ).join(
        ItemMaster, ItemMaster.id == ItemStock.item_id
    ).filter(*base_filter).first()

    total_value = float(total.value or 0)

    def calc_percentage(val):
        if total_value == 0:
            return 0
        return round((float(val or 0) / total_value) * 100, 1)

    return {
        "categories": [
            {
                "name": "Fast Moving",
                "description": f"Moved within last {fast_moving_days} days",
                "days_threshold": fast_moving_days,
                "count": fast_moving.count or 0,
                "quantity": float(fast_moving.quantity or 0),
                "value": round(float(fast_moving.value or 0), 2),
                "value_percentage": calc_percentage(fast_moving.value)
            },
            {
                "name": "Normal Moving",
                "description": f"Moved within {fast_moving_days}-{normal_moving_days} days",
                "days_threshold": normal_moving_days,
                "count": normal_moving.count or 0,
                "quantity": float(normal_moving.quantity or 0),
                "value": round(float(normal_moving.value or 0), 2),
                "value_percentage": calc_percentage(normal_moving.value)
            },
            {
                "name": "Slow Moving",
                "description": f"Moved within {normal_moving_days}-{slow_moving_days} days",
                "days_threshold": slow_moving_days,
                "count": slow_moving.count or 0,
                "quantity": float(slow_moving.quantity or 0),
                "value": round(float(slow_moving.value or 0), 2),
                "value_percentage": calc_percentage(slow_moving.value)
            },
            {
                "name": "Non-Moving",
                "description": f"Not moved for over {slow_moving_days} days",
                "days_threshold": None,
                "count": non_moving.count or 0,
                "quantity": float(non_moving.quantity or 0),
                "value": round(float(non_moving.value or 0), 2),
                "value_percentage": calc_percentage(non_moving.value)
            }
        ],
        "total": {
            "count": total.count or 0,
            "quantity": float(total.quantity or 0),
            "value": round(float(total.value or 0), 2)
        }
    }
