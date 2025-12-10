"""
Cycle Count API endpoints for physical inventory verification
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
import logging

from app.database import get_db
from app.models import (
    User, CycleCount, CycleCountItem, ItemMaster, ItemStock,
    ItemLedger, ItemCategory, Warehouse
)
from app.api.auth import verify_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)


# ============ Helper Functions ============

def decimal_to_float(val):
    """Convert Decimal to float for JSON serialization"""
    if val is None:
        return None
    return float(val)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current user from token"""
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


def generate_count_number(db: Session, company_id: int) -> str:
    """Generate next cycle count number for company"""
    year = datetime.now().year
    prefix = f"CC-{year}-"

    last_count = db.query(CycleCount).filter(
        CycleCount.company_id == company_id,
        CycleCount.count_number.like(f"{prefix}%")
    ).order_by(CycleCount.id.desc()).first()

    if last_count:
        try:
            last_num = int(last_count.count_number.split("-")[-1])
            next_num = last_num + 1
        except (ValueError, IndexError):
            next_num = 1
    else:
        next_num = 1

    return f"{prefix}{next_num:05d}"


def generate_transaction_number(db: Session, company_id: int, prefix: str = "ADJ") -> str:
    """Generate transaction number for ledger entries"""
    today = datetime.now().strftime("%Y%m%d")
    tx_prefix = f"{prefix}-{today}-"

    last_tx = db.query(ItemLedger).filter(
        ItemLedger.company_id == company_id,
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

    return f"{tx_prefix}{next_num:05d}"


# ============ Pydantic Schemas ============

class CycleCountCreate(BaseModel):
    warehouse_id: int
    count_type: str = "full"  # full, partial, category
    category_id: Optional[int] = None
    notes: Optional[str] = None


class CycleCountUpdate(BaseModel):
    notes: Optional[str] = None
    status: Optional[str] = None


class CycleCountItemUpdate(BaseModel):
    counted_quantity: float
    notes: Optional[str] = None


class BulkCountUpdate(BaseModel):
    items: List[dict]  # [{item_id, counted_quantity, notes}]


# ============ Response Helpers ============

def cycle_count_to_response(cc: CycleCount, include_items: bool = False) -> dict:
    """Convert CycleCount model to response dict"""
    response = {
        "id": cc.id,
        "count_number": cc.count_number,
        "count_date": cc.count_date.isoformat() if cc.count_date else None,
        "warehouse_id": cc.warehouse_id,
        "warehouse_name": cc.warehouse.name if cc.warehouse else None,
        "warehouse_code": cc.warehouse.code if cc.warehouse else None,
        "status": cc.status,
        "count_type": cc.count_type,
        "category_id": cc.category_id,
        "category_name": cc.category.name if cc.category else None,
        "total_items_counted": cc.total_items_counted,
        "items_with_variance": cc.items_with_variance,
        "total_variance_value": decimal_to_float(cc.total_variance_value),
        "notes": cc.notes,
        "created_by": cc.created_by,
        "created_by_name": cc.creator.name if cc.creator else None,
        "completed_by": cc.completed_by,
        "completed_by_name": cc.completer.name if cc.completer else None,
        "completed_at": cc.completed_at.isoformat() if cc.completed_at else None,
        "created_at": cc.created_at.isoformat() if cc.created_at else None,
        "updated_at": cc.updated_at.isoformat() if cc.updated_at else None,
    }

    if include_items:
        response["items"] = [
            {
                "id": item.id,
                "item_id": item.item_id,
                "item_number": item.item.item_number if item.item else None,
                "item_description": item.item.description if item.item else None,
                "category_name": item.item.category.name if item.item and item.item.category else None,
                "unit": item.item.unit if item.item else None,
                "system_quantity": decimal_to_float(item.system_quantity),
                "counted_quantity": decimal_to_float(item.counted_quantity),
                "variance_quantity": decimal_to_float(item.variance_quantity),
                "variance_value": decimal_to_float(item.variance_value),
                "unit_cost": decimal_to_float(item.unit_cost),
                "status": item.status,
                "counted_by": item.counted_by,
                "counted_by_name": item.counter.name if item.counter else None,
                "counted_at": item.counted_at.isoformat() if item.counted_at else None,
                "notes": item.notes,
            }
            for item in cc.items
        ]
        response["items_count"] = len(cc.items)

    return response


# ============ Cycle Count Endpoints ============

@router.get("/cycle-counts/")
async def get_cycle_counts(
    warehouse_id: Optional[int] = None,
    status: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all cycle counts for the company"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    query = db.query(CycleCount).options(
        joinedload(CycleCount.warehouse),
        joinedload(CycleCount.category),
        joinedload(CycleCount.creator),
        joinedload(CycleCount.completer)
    ).filter(CycleCount.company_id == user.company_id)

    if warehouse_id:
        query = query.filter(CycleCount.warehouse_id == warehouse_id)

    if status:
        query = query.filter(CycleCount.status == status)

    if from_date:
        query = query.filter(CycleCount.count_date >= from_date)

    if to_date:
        query = query.filter(CycleCount.count_date <= to_date)

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    counts = query.order_by(CycleCount.count_date.desc()).offset(offset).limit(page_size).all()

    return {
        "items": [cycle_count_to_response(cc) for cc in counts],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/cycle-counts/{count_id}")
async def get_cycle_count(
    count_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific cycle count with all items"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    cc = db.query(CycleCount).options(
        joinedload(CycleCount.warehouse),
        joinedload(CycleCount.category),
        joinedload(CycleCount.creator),
        joinedload(CycleCount.completer),
        joinedload(CycleCount.items).joinedload(CycleCountItem.item).joinedload(ItemMaster.category),
        joinedload(CycleCount.items).joinedload(CycleCountItem.counter)
    ).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    return cycle_count_to_response(cc, include_items=True)


@router.post("/cycle-counts/")
async def create_cycle_count(
    data: CycleCountCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new cycle count and populate with warehouse items"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Verify warehouse
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == data.warehouse_id,
        Warehouse.company_id == user.company_id
    ).first()
    if not warehouse:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warehouse not found")

    # Verify category if specified
    if data.category_id:
        category = db.query(ItemCategory).filter(
            ItemCategory.id == data.category_id,
            ItemCategory.company_id == user.company_id
        ).first()
        if not category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    try:
        # Create cycle count
        cc = CycleCount(
            company_id=user.company_id,
            count_number=generate_count_number(db, user.company_id),
            count_date=datetime.now(),
            warehouse_id=data.warehouse_id,
            count_type=data.count_type,
            category_id=data.category_id,
            notes=data.notes,
            status="draft",
            created_by=user.id
        )
        db.add(cc)
        db.flush()  # Get the ID

        # Get items to count based on count_type
        stock_query = db.query(ItemStock).options(
            joinedload(ItemStock.item)
        ).filter(
            ItemStock.warehouse_id == data.warehouse_id,
            ItemStock.quantity_on_hand > 0
        )

        # Filter by category if specified
        if data.count_type == "category" and data.category_id:
            stock_query = stock_query.join(ItemMaster).filter(
                ItemMaster.category_id == data.category_id
            )

        stocks = stock_query.all()

        # Also get items with zero stock that had activity (for full counts)
        if data.count_type == "full":
            # Get all items in this warehouse from item_master
            items_with_stock = {s.item_id for s in stocks}

            zero_stock_items = db.query(ItemMaster).filter(
                ItemMaster.company_id == user.company_id,
                ItemMaster.is_active == True,
                ~ItemMaster.id.in_(items_with_stock) if items_with_stock else True
            )

            if data.category_id:
                zero_stock_items = zero_stock_items.filter(ItemMaster.category_id == data.category_id)

            # For full counts, we may want to include items that had stock at some point
            # Check ledger for items that had transactions in this warehouse
            items_with_history = db.query(ItemLedger.item_id).filter(
                ItemLedger.company_id == user.company_id,
                and_(
                    ItemLedger.to_warehouse_id == data.warehouse_id
                ) | and_(
                    ItemLedger.from_warehouse_id == data.warehouse_id
                )
            ).distinct().all()
            items_with_history_ids = {i[0] for i in items_with_history}

            # Add zero stock items that had history
            for item_id in items_with_history_ids - items_with_stock:
                item = db.query(ItemMaster).filter(ItemMaster.id == item_id).first()
                if item and item.is_active:
                    if not data.category_id or item.category_id == data.category_id:
                        cc_item = CycleCountItem(
                            cycle_count_id=cc.id,
                            item_id=item_id,
                            system_quantity=0,
                            unit_cost=decimal_to_float(item.unit_cost) or 0,
                            status="pending"
                        )
                        db.add(cc_item)

        # Create cycle count items for items with stock
        for stock in stocks:
            cc_item = CycleCountItem(
                cycle_count_id=cc.id,
                item_id=stock.item_id,
                system_quantity=stock.quantity_on_hand,
                unit_cost=decimal_to_float(stock.average_cost) or decimal_to_float(stock.item.unit_cost) or 0,
                status="pending"
            )
            db.add(cc_item)

        db.commit()

        # Reload with relationships
        db.refresh(cc)
        cc = db.query(CycleCount).options(
            joinedload(CycleCount.warehouse),
            joinedload(CycleCount.category),
            joinedload(CycleCount.creator),
            joinedload(CycleCount.items).joinedload(CycleCountItem.item)
        ).filter(CycleCount.id == cc.id).first()

        return cycle_count_to_response(cc, include_items=True)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating cycle count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating cycle count: {str(e)}"
        )


@router.put("/cycle-counts/{count_id}/items/{item_id}")
async def update_cycle_count_item(
    count_id: int,
    item_id: int,
    data: CycleCountItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a single cycle count item with counted quantity"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get cycle count
    cc = db.query(CycleCount).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    if cc.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot update completed cycle count")

    # Get the cycle count item
    cc_item = db.query(CycleCountItem).filter(
        CycleCountItem.cycle_count_id == count_id,
        CycleCountItem.item_id == item_id
    ).first()

    if not cc_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cycle count")

    try:
        # Update the item
        cc_item.counted_quantity = Decimal(str(data.counted_quantity))
        cc_item.variance_quantity = cc_item.counted_quantity - cc_item.system_quantity
        cc_item.variance_value = cc_item.variance_quantity * (cc_item.unit_cost or Decimal("0"))
        cc_item.status = "counted"
        cc_item.counted_by = user.id
        cc_item.counted_at = datetime.now()
        if data.notes:
            cc_item.notes = data.notes

        # Update cycle count status if needed
        if cc.status == "draft":
            cc.status = "in_progress"

        db.commit()

        return {
            "id": cc_item.id,
            "item_id": cc_item.item_id,
            "system_quantity": decimal_to_float(cc_item.system_quantity),
            "counted_quantity": decimal_to_float(cc_item.counted_quantity),
            "variance_quantity": decimal_to_float(cc_item.variance_quantity),
            "variance_value": decimal_to_float(cc_item.variance_value),
            "status": cc_item.status
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating item: {str(e)}"
        )


@router.post("/cycle-counts/{count_id}/bulk-update")
async def bulk_update_cycle_count_items(
    count_id: int,
    data: BulkCountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update multiple cycle count items at once"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get cycle count
    cc = db.query(CycleCount).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    if cc.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot update completed cycle count")

    try:
        updated_count = 0
        for item_data in data.items:
            item_id = item_data.get("item_id")
            counted_qty = item_data.get("counted_quantity")

            if item_id is None or counted_qty is None:
                continue

            cc_item = db.query(CycleCountItem).filter(
                CycleCountItem.cycle_count_id == count_id,
                CycleCountItem.item_id == item_id
            ).first()

            if cc_item:
                cc_item.counted_quantity = Decimal(str(counted_qty))
                cc_item.variance_quantity = cc_item.counted_quantity - cc_item.system_quantity
                cc_item.variance_value = cc_item.variance_quantity * (cc_item.unit_cost or Decimal("0"))
                cc_item.status = "counted"
                cc_item.counted_by = user.id
                cc_item.counted_at = datetime.now()
                if item_data.get("notes"):
                    cc_item.notes = item_data.get("notes")
                updated_count += 1

        # Update cycle count status
        if cc.status == "draft":
            cc.status = "in_progress"

        db.commit()

        return {"success": True, "updated_count": updated_count}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating items: {str(e)}"
        )


@router.post("/cycle-counts/{count_id}/complete")
async def complete_cycle_count(
    count_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Complete a cycle count and apply adjustments to inventory.
    Creates ledger entries for all variances.
    """
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    # Get cycle count with items
    cc = db.query(CycleCount).options(
        joinedload(CycleCount.items).joinedload(CycleCountItem.item),
        joinedload(CycleCount.warehouse)
    ).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    if cc.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cycle count already completed")

    # Check all items have been counted
    uncounted_items = [item for item in cc.items if item.status == "pending"]
    if uncounted_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{len(uncounted_items)} items have not been counted yet"
        )

    try:
        total_items_counted = 0
        items_with_variance = 0
        total_variance_value = Decimal("0")

        for cc_item in cc.items:
            total_items_counted += 1

            if cc_item.variance_quantity and cc_item.variance_quantity != 0:
                items_with_variance += 1
                total_variance_value += cc_item.variance_value or Decimal("0")

                # Get current stock record
                stock = db.query(ItemStock).filter(
                    ItemStock.warehouse_id == cc.warehouse_id,
                    ItemStock.item_id == cc_item.item_id
                ).first()

                # Determine adjustment type
                if cc_item.variance_quantity > 0:
                    tx_type = "CYCLE_COUNT_PLUS"
                else:
                    tx_type = "CYCLE_COUNT_MINUS"

                # Create ledger entry
                ledger_entry = ItemLedger(
                    company_id=user.company_id,
                    item_id=cc_item.item_id,
                    transaction_number=generate_transaction_number(db, user.company_id, "CC"),
                    transaction_date=datetime.now(),
                    transaction_type=tx_type,
                    quantity=cc_item.variance_quantity,
                    unit=cc_item.item.unit if cc_item.item else "pcs",
                    unit_cost=cc_item.unit_cost,
                    total_cost=abs(cc_item.variance_value or Decimal("0")),
                    to_warehouse_id=cc.warehouse_id if cc_item.variance_quantity > 0 else None,
                    from_warehouse_id=cc.warehouse_id if cc_item.variance_quantity < 0 else None,
                    balance_after=cc_item.counted_quantity,
                    notes=f"Cycle count adjustment: {cc.count_number}. {cc_item.notes or ''}".strip(),
                    created_by=user.id
                )
                db.add(ledger_entry)

                # Update or create stock record
                if stock:
                    stock.quantity_on_hand = cc_item.counted_quantity
                    stock.last_count_date = datetime.now()
                    stock.last_movement_date = datetime.now()
                else:
                    # Create stock record if it doesn't exist
                    stock = ItemStock(
                        company_id=user.company_id,
                        item_id=cc_item.item_id,
                        warehouse_id=cc.warehouse_id,
                        quantity_on_hand=cc_item.counted_quantity,
                        average_cost=cc_item.unit_cost,
                        last_count_date=datetime.now(),
                        last_movement_date=datetime.now()
                    )
                    db.add(stock)

                cc_item.status = "adjusted"
            else:
                # No variance - just update last count date
                stock = db.query(ItemStock).filter(
                    ItemStock.warehouse_id == cc.warehouse_id,
                    ItemStock.item_id == cc_item.item_id
                ).first()
                if stock:
                    stock.last_count_date = datetime.now()

        # Update cycle count summary
        cc.status = "completed"
        cc.completed_by = user.id
        cc.completed_at = datetime.now()
        cc.total_items_counted = total_items_counted
        cc.items_with_variance = items_with_variance
        cc.total_variance_value = total_variance_value

        db.commit()

        return {
            "success": True,
            "message": "Cycle count completed and adjustments applied",
            "summary": {
                "total_items_counted": total_items_counted,
                "items_with_variance": items_with_variance,
                "total_variance_value": decimal_to_float(total_variance_value)
            }
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error completing cycle count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error completing cycle count: {str(e)}"
        )


@router.post("/cycle-counts/{count_id}/cancel")
async def cancel_cycle_count(
    count_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a cycle count (cannot cancel completed counts)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    cc = db.query(CycleCount).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    if cc.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot cancel completed cycle count")

    cc.status = "cancelled"
    db.commit()

    return {"success": True, "message": "Cycle count cancelled"}


@router.delete("/cycle-counts/{count_id}")
async def delete_cycle_count(
    count_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a cycle count (only draft or cancelled counts)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    cc = db.query(CycleCount).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    if cc.status not in ["draft", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete draft or cancelled cycle counts"
        )

    db.delete(cc)
    db.commit()

    return {"success": True, "message": "Cycle count deleted"}


@router.post("/cycle-counts/{count_id}/add-item")
async def add_item_to_cycle_count(
    count_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add an item to an existing cycle count (for partial counts)"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    cc = db.query(CycleCount).filter(
        CycleCount.id == count_id,
        CycleCount.company_id == user.company_id
    ).first()

    if not cc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle count not found")

    if cc.status == "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify completed cycle count")

    # Check item exists
    item = db.query(ItemMaster).filter(
        ItemMaster.id == item_id,
        ItemMaster.company_id == user.company_id
    ).first()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Check if already in count
    existing = db.query(CycleCountItem).filter(
        CycleCountItem.cycle_count_id == count_id,
        CycleCountItem.item_id == item_id
    ).first()

    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item already in cycle count")

    # Get current stock
    stock = db.query(ItemStock).filter(
        ItemStock.warehouse_id == cc.warehouse_id,
        ItemStock.item_id == item_id
    ).first()

    system_qty = decimal_to_float(stock.quantity_on_hand) if stock else 0
    unit_cost = decimal_to_float(stock.average_cost) if stock else decimal_to_float(item.unit_cost) or 0

    # Add item to count
    cc_item = CycleCountItem(
        cycle_count_id=count_id,
        item_id=item_id,
        system_quantity=system_qty,
        unit_cost=unit_cost,
        status="pending"
    )
    db.add(cc_item)
    db.commit()

    return {
        "id": cc_item.id,
        "item_id": cc_item.item_id,
        "item_number": item.item_number,
        "item_description": item.description,
        "system_quantity": system_qty,
        "unit_cost": unit_cost,
        "status": "pending"
    }
