"""
Landed Cost Service for calculating and allocating extra costs to GRN lines.

This service handles:
- Allocation of extra costs (freight, duties, port handling, etc.) to GRN lines
- Landed cost calculation (invoice price + allocated extra costs)
- Inventory cost updates using landed cost
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
import logging

from app.models import (
    GoodsReceipt, GoodsReceiptLine, GoodsReceiptExtraCost,
    ItemStock, ItemLedger
)

logger = logging.getLogger(__name__)


class LandedCostService:
    """Service for managing landed costs on Goods Receipts"""

    def __init__(self, db: Session, company_id: int, user_id: int):
        self.db = db
        self.company_id = company_id
        self.user_id = user_id

    def allocate_extra_costs(self, grn_id: int) -> GoodsReceipt:
        """
        Allocate all extra costs to GRN lines proportionally by line value.

        Formula for each line:
        - line_ratio = line_total_price / sum(all_line_total_prices)
        - allocated_extra_cost = total_extra_costs * line_ratio
        - landed_unit_cost = unit_price + (allocated_extra_cost / quantity)
        - landed_total_cost = landed_unit_cost * quantity

        Args:
            grn_id: The Goods Receipt ID

        Returns:
            Updated GoodsReceipt with allocated costs
        """
        grn = self.db.query(GoodsReceipt).filter(
            GoodsReceipt.id == grn_id,
            GoodsReceipt.company_id == self.company_id
        ).first()

        if not grn:
            raise ValueError(f"Goods Receipt {grn_id} not found")

        # Calculate total extra costs
        total_extra_costs = Decimal('0')
        if grn.extra_costs:
            for cost in grn.extra_costs:
                total_extra_costs += Decimal(str(cost.amount or 0))

        # Calculate total line value for ratio calculation
        total_line_value = Decimal('0')
        for line in grn.lines:
            total_line_value += Decimal(str(line.total_price or 0))

        if total_line_value == 0:
            logger.warning(f"GRN {grn.grn_number} has zero total line value, skipping allocation")
            return grn

        # Allocate costs to each line proportionally
        allocated_sum = Decimal('0')
        lines_count = len(grn.lines)

        for i, line in enumerate(grn.lines):
            line_value = Decimal(str(line.total_price or 0))

            if line_value == 0:
                line.allocated_extra_cost = Decimal('0')
                line.landed_unit_cost = line.unit_price
                line.landed_total_cost = line.total_price
                continue

            # Calculate line ratio
            line_ratio = line_value / total_line_value

            # Calculate allocated extra cost for this line
            # For the last line, use remaining amount to avoid rounding errors
            if i == lines_count - 1:
                allocated_cost = total_extra_costs - allocated_sum
            else:
                allocated_cost = (total_extra_costs * line_ratio).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
                allocated_sum += allocated_cost

            line.allocated_extra_cost = allocated_cost

            # Calculate landed unit cost
            quantity = Decimal(str(line.quantity_received or 0))
            if quantity > 0:
                unit_price = Decimal(str(line.unit_price or 0))
                # Landed unit cost = unit price + (allocated extra cost / quantity)
                extra_per_unit = (allocated_cost / quantity).quantize(
                    Decimal('0.0001'), rounding=ROUND_HALF_UP
                )
                line.landed_unit_cost = unit_price + extra_per_unit
                line.landed_total_cost = (line.landed_unit_cost * quantity).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP
                )
            else:
                line.landed_unit_cost = line.unit_price
                line.landed_total_cost = line.total_price

        # Update GRN header totals
        grn.total_extra_costs = total_extra_costs
        grn.total_landed_cost = Decimal(str(grn.total_amount or 0)) + total_extra_costs

        # Mark as import if extra costs exist
        if total_extra_costs > 0:
            grn.is_import = True

        self.db.flush()

        logger.info(
            f"Allocated extra costs for GRN {grn.grn_number}: "
            f"total_extra_costs={total_extra_costs}, total_landed_cost={grn.total_landed_cost}"
        )

        return grn

    def recalculate_grn_landed_costs(self, grn_id: int) -> GoodsReceipt:
        """
        Recalculate all landed costs for a GRN.
        Use this after adding, updating, or deleting extra costs.

        Args:
            grn_id: The Goods Receipt ID

        Returns:
            Updated GoodsReceipt
        """
        return self.allocate_extra_costs(grn_id)

    def get_landed_cost_summary(self, grn_id: int) -> dict:
        """
        Get a summary of landed costs for a GRN.

        Args:
            grn_id: The Goods Receipt ID

        Returns:
            Dictionary with cost breakdown
        """
        grn = self.db.query(GoodsReceipt).filter(
            GoodsReceipt.id == grn_id,
            GoodsReceipt.company_id == self.company_id
        ).first()

        if not grn:
            raise ValueError(f"Goods Receipt {grn_id} not found")

        # Group extra costs by type
        costs_by_type = {}
        total_extra = Decimal('0')

        if grn.extra_costs:
            for cost in grn.extra_costs:
                cost_type = cost.cost_type
                amount = Decimal(str(cost.amount or 0))
                total_extra += amount

                if cost_type not in costs_by_type:
                    costs_by_type[cost_type] = {
                        "type": cost_type,
                        "total": Decimal('0'),
                        "count": 0
                    }
                costs_by_type[cost_type]["total"] += amount
                costs_by_type[cost_type]["count"] += 1

        # Calculate allocation summary per line
        line_allocations = []
        for line in grn.lines:
            line_allocations.append({
                "line_id": line.id,
                "item_description": line.item_description,
                "quantity": float(line.quantity_received or 0),
                "unit_price": float(line.unit_price or 0),
                "line_total": float(line.total_price or 0),
                "allocated_extra_cost": float(line.allocated_extra_cost or 0),
                "landed_unit_cost": float(line.landed_unit_cost) if line.landed_unit_cost else None,
                "landed_total_cost": float(line.landed_total_cost) if line.landed_total_cost else None,
                "extra_cost_per_unit": (
                    float(line.allocated_extra_cost / line.quantity_received)
                    if line.quantity_received and line.allocated_extra_cost
                    else 0
                )
            })

        return {
            "grn_id": grn.id,
            "grn_number": grn.grn_number,
            "is_import": grn.is_import or False,
            "invoice_total": float(grn.total_amount or 0),
            "total_extra_costs": float(total_extra),
            "total_landed_cost": float(grn.total_landed_cost or 0),
            "extra_cost_percentage": (
                float(total_extra / Decimal(str(grn.total_amount))) * 100
                if grn.total_amount and grn.total_amount > 0
                else 0
            ),
            "costs_by_type": [
                {
                    "type": v["type"],
                    "total": float(v["total"]),
                    "count": v["count"]
                }
                for v in costs_by_type.values()
            ],
            "line_allocations": line_allocations
        }


def allocate_extra_costs(db: Session, grn_id: int, company_id: int, user_id: int) -> GoodsReceipt:
    """
    Convenience function to allocate extra costs.

    Args:
        db: Database session
        grn_id: The Goods Receipt ID
        company_id: The company ID
        user_id: The user ID

    Returns:
        Updated GoodsReceipt
    """
    service = LandedCostService(db, company_id, user_id)
    return service.allocate_extra_costs(grn_id)


def get_effective_unit_cost(line: GoodsReceiptLine) -> Decimal:
    """
    Get the effective unit cost for inventory updates.
    Returns landed_unit_cost if available, otherwise unit_price.

    Args:
        line: The GoodsReceiptLine

    Returns:
        Effective unit cost as Decimal
    """
    if line.landed_unit_cost is not None and line.landed_unit_cost > 0:
        return Decimal(str(line.landed_unit_cost))
    return Decimal(str(line.unit_price or 0))


def get_effective_total_cost(line: GoodsReceiptLine) -> Decimal:
    """
    Get the effective total cost for inventory/accounting.
    Returns landed_total_cost if available, otherwise total_price.

    Args:
        line: The GoodsReceiptLine

    Returns:
        Effective total cost as Decimal
    """
    if line.landed_total_cost is not None and line.landed_total_cost > 0:
        return Decimal(str(line.landed_total_cost))
    return Decimal(str(line.total_price or 0))
