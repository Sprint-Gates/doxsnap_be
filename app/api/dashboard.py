"""
Dashboard API endpoints - optimized stats for dashboard display
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_, case
from typing import Optional
from datetime import datetime
from decimal import Decimal

from app.database import get_db
from app.models import (
    User, WorkOrder, Technician, WorkOrderTimeEntry, Branch,
    work_order_technicians, WorkOrderSparePart, Contract, Client,
    Vendor, ProcessedImage, ItemMaster, ItemStock, ItemTransfer,
    ItemLedger, Warehouse, PettyCashFund, PettyCashTransaction
)
from app.api.auth import get_current_user

router = APIRouter(tags=["dashboard"])


def decimal_to_float(val):
    """Convert Decimal to float for JSON serialization"""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return val


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get dashboard statistics for a specific month/year"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    company_id = user.company_id

    # Build date range for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    # Get work order counts by status
    open_statuses = ['draft', 'pending', 'in_progress', 'on_hold']
    closed_statuses = ['completed', 'cancelled']

    work_order_stats = db.query(
        func.count(WorkOrder.id).label('total'),
        func.sum(case((WorkOrder.status.in_(open_statuses), 1), else_=0)).label('open'),
        func.sum(case((WorkOrder.status.in_(closed_statuses), 1), else_=0)).label('closed'),
        func.sum(case((WorkOrder.work_order_type == 'preventive', 1), else_=0)).label('preventive'),
        func.sum(case((WorkOrder.work_order_type == 'corrective', 1), else_=0)).label('corrective'),
        func.sum(case((WorkOrder.work_order_type == 'operations', 1), else_=0)).label('operations'),
        func.count(func.distinct(WorkOrder.branch_id)).label('branches_served')
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).first()

    # Get billable stats
    billable_stats = db.query(
        func.count(WorkOrder.id).label('count'),
        func.coalesce(func.sum(WorkOrder.billable_amount), 0).label('amount')
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.is_billable == True,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).first()

    # Get all active technicians
    technicians = db.query(Technician).filter(
        Technician.company_id == company_id,
        Technician.is_active == True
    ).all()

    # Get technician utilization from time entries in the selected month
    # Join time entries with work orders to filter by date
    time_entries_query = db.query(
        WorkOrderTimeEntry.technician_id,
        func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('total_hours')
    ).join(
        WorkOrder, WorkOrder.id == WorkOrderTimeEntry.work_order_id
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrderTimeEntry.start_time >= start_date,
        WorkOrderTimeEntry.start_time < end_date
    ).group_by(WorkOrderTimeEntry.technician_id).all()

    # Create a dict for quick lookup
    tech_hours = {te.technician_id: float(te.total_hours or 0) for te in time_entries_query}

    # Get completed work orders count per technician in the month
    completed_wo_query = db.query(
        work_order_technicians.c.technician_id,
        func.count(WorkOrder.id).label('completed_count')
    ).join(
        WorkOrder, WorkOrder.id == work_order_technicians.c.work_order_id
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.status == 'completed',
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).group_by(work_order_technicians.c.technician_id).all()

    # Create a dict for quick lookup
    tech_completed = {row.technician_id: row.completed_count for row in completed_wo_query}

    # Build technician utilization list - include ALL active technicians
    technician_utilization = []
    for tech in technicians:
        hours = tech_hours.get(tech.id, 0)
        completed = tech_completed.get(tech.id, 0)
        technician_utilization.append({
            "id": tech.id,
            "name": tech.name or "Unknown",
            "totalHours": round(hours, 1),
            "workOrdersCompleted": completed
        })

    # Sort by hours descending
    technician_utilization.sort(key=lambda x: x['totalHours'], reverse=True)

    return {
        "month": month,
        "year": year,
        "workOrders": {
            "total": work_order_stats.total or 0,
            "open": work_order_stats.open or 0,
            "closed": work_order_stats.closed or 0,
            "preventive": work_order_stats.preventive or 0,
            "corrective": work_order_stats.corrective or 0,
            "operations": work_order_stats.operations or 0
        },
        "branchesServed": work_order_stats.branches_served or 0,
        "billable": {
            "count": billable_stats.count or 0,
            "amount": decimal_to_float(billable_stats.amount) or 0
        },
        "technicianUtilization": technician_utilization
    }


@router.get("/dashboard/accounting")
async def get_accounting_dashboard(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get accounting dashboard statistics for a specific month/year"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    company_id = user.company_id

    # Build date range for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    # ===== REVENUE METRICS =====
    # Billable work orders by status
    billable_stats = db.query(
        func.count(WorkOrder.id).label('total_billable'),
        func.coalesce(func.sum(WorkOrder.billable_amount), 0).label('total_amount'),
        func.sum(case((WorkOrder.billing_status == 'pending', 1), else_=0)).label('pending_count'),
        func.sum(case((WorkOrder.billing_status == 'pending', WorkOrder.billable_amount), else_=0)).label('pending_amount'),
        func.sum(case((WorkOrder.billing_status == 'invoiced', 1), else_=0)).label('invoiced_count'),
        func.sum(case((WorkOrder.billing_status == 'invoiced', WorkOrder.billable_amount), else_=0)).label('invoiced_amount'),
        func.sum(case((WorkOrder.billing_status == 'paid', 1), else_=0)).label('paid_count'),
        func.sum(case((WorkOrder.billing_status == 'paid', WorkOrder.billable_amount), else_=0)).label('paid_amount')
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.is_billable == True,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).first()

    # ===== COST METRICS =====
    cost_stats = db.query(
        func.coalesce(func.sum(WorkOrder.actual_labor_cost), 0).label('total_labor_cost'),
        func.coalesce(func.sum(WorkOrder.actual_parts_cost), 0).label('total_parts_cost'),
        func.coalesce(func.sum(WorkOrder.actual_total_cost), 0).label('total_cost'),
        func.coalesce(func.sum(WorkOrder.estimated_total_cost), 0).label('estimated_cost')
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).first()

    # ===== LABOR HOURS & OVERTIME =====
    labor_stats = db.query(
        func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('total_hours'),
        func.sum(case((WorkOrderTimeEntry.is_overtime == True, WorkOrderTimeEntry.hours_worked), else_=0)).label('overtime_hours'),
        func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('labor_cost_from_entries')
    ).join(
        WorkOrder, WorkOrder.id == WorkOrderTimeEntry.work_order_id
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrderTimeEntry.start_time >= start_date,
        WorkOrderTimeEntry.start_time < end_date
    ).first()

    # ===== PARTS COST =====
    parts_stats = db.query(
        func.coalesce(func.sum(WorkOrderSparePart.total_cost), 0).label('parts_cost'),
        func.coalesce(func.sum(WorkOrderSparePart.total_price), 0).label('parts_revenue'),
        func.count(WorkOrderSparePart.id).label('parts_issued')
    ).join(
        WorkOrder, WorkOrder.id == WorkOrderSparePart.work_order_id
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).first()

    # ===== REVENUE BY CLIENT (TOP 5) =====
    revenue_by_client = db.query(
        Client.id,
        Client.name,
        func.count(WorkOrder.id).label('work_order_count'),
        func.coalesce(func.sum(WorkOrder.billable_amount), 0).label('total_revenue')
    ).join(
        Branch, Branch.id == WorkOrder.branch_id
    ).join(
        Client, Client.id == Branch.client_id
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.is_billable == True,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).group_by(Client.id, Client.name).order_by(
        func.sum(WorkOrder.billable_amount).desc()
    ).limit(5).all()

    # ===== MONTHLY TREND (Last 6 months) =====
    monthly_trend = []
    for i in range(5, -1, -1):
        trend_month = month - i
        trend_year = year
        if trend_month <= 0:
            trend_month += 12
            trend_year -= 1

        trend_start = datetime(trend_year, trend_month, 1)
        if trend_month == 12:
            trend_end = datetime(trend_year + 1, 1, 1)
        else:
            trend_end = datetime(trend_year, trend_month + 1, 1)

        trend_stats = db.query(
            func.coalesce(func.sum(WorkOrder.billable_amount), 0).label('revenue'),
            func.coalesce(func.sum(WorkOrder.actual_total_cost), 0).label('cost')
        ).filter(
            WorkOrder.company_id == company_id,
            WorkOrder.created_at >= trend_start,
            WorkOrder.created_at < trend_end
        ).first()

        monthly_trend.append({
            "month": trend_month,
            "year": trend_year,
            "monthName": datetime(trend_year, trend_month, 1).strftime("%b"),
            "revenue": decimal_to_float(trend_stats.revenue) or 0,
            "cost": decimal_to_float(trend_stats.cost) or 0
        })

    # ===== ACTIVE CONTRACTS VALUE =====
    contracts_stats = db.query(
        func.count(Contract.id).label('active_contracts'),
        func.coalesce(func.sum(Contract.contract_value), 0).label('total_contract_value'),
        func.coalesce(func.sum(Contract.budget), 0).label('total_budget')
    ).filter(
        Contract.company_id == company_id,
        Contract.status == 'active'
    ).first()

    # ===== WORK ORDER STATUS BREAKDOWN =====
    wo_status_stats = db.query(
        WorkOrder.status,
        func.count(WorkOrder.id).label('count'),
        func.coalesce(func.sum(WorkOrder.billable_amount), 0).label('amount')
    ).filter(
        WorkOrder.company_id == company_id,
        WorkOrder.created_at >= start_date,
        WorkOrder.created_at < end_date
    ).group_by(WorkOrder.status).all()

    work_order_breakdown = {
        row.status: {
            "count": row.count,
            "amount": decimal_to_float(row.amount) or 0
        } for row in wo_status_stats
    }

    # Calculate profit margin
    total_revenue = decimal_to_float(billable_stats.total_amount) or 0
    total_cost = decimal_to_float(cost_stats.total_cost) or 0
    profit = total_revenue - total_cost
    profit_margin = (profit / total_revenue * 100) if total_revenue > 0 else 0

    # ===== PETTY CASH STATISTICS =====
    petty_cash_stats = db.query(
        func.count(PettyCashTransaction.id).label('total_transactions'),
        func.coalesce(func.sum(case(
            (PettyCashTransaction.status == 'approved', PettyCashTransaction.amount),
            else_=0
        )), 0).label('total_spent'),
        func.sum(case((PettyCashTransaction.status == 'pending', 1), else_=0)).label('pending_count'),
        func.coalesce(func.sum(case(
            (PettyCashTransaction.status == 'pending', PettyCashTransaction.amount),
            else_=0
        )), 0).label('pending_amount')
    ).filter(
        PettyCashTransaction.company_id == company_id,
        PettyCashTransaction.transaction_date >= start_date,
        PettyCashTransaction.transaction_date < end_date
    ).first()

    # Get total funds allocated
    fund_stats = db.query(
        func.count(PettyCashFund.id).label('total_funds'),
        func.sum(case((PettyCashFund.status == 'active', 1), else_=0)).label('active_funds'),
        func.coalesce(func.sum(case(
            (PettyCashFund.status == 'active', PettyCashFund.fund_limit),
            else_=0
        )), 0).label('total_allocated'),
        func.coalesce(func.sum(case(
            (PettyCashFund.status == 'active', PettyCashFund.current_balance),
            else_=0
        )), 0).label('total_balance')
    ).filter(
        PettyCashFund.company_id == company_id
    ).first()

    return {
        "month": month,
        "year": year,
        "revenue": {
            "total": decimal_to_float(billable_stats.total_amount) or 0,
            "pending": {
                "count": billable_stats.pending_count or 0,
                "amount": decimal_to_float(billable_stats.pending_amount) or 0
            },
            "invoiced": {
                "count": billable_stats.invoiced_count or 0,
                "amount": decimal_to_float(billable_stats.invoiced_amount) or 0
            },
            "paid": {
                "count": billable_stats.paid_count or 0,
                "amount": decimal_to_float(billable_stats.paid_amount) or 0
            }
        },
        "costs": {
            "labor": decimal_to_float(cost_stats.total_labor_cost) or 0,
            "parts": decimal_to_float(cost_stats.total_parts_cost) or 0,
            "total": total_cost,
            "estimated": decimal_to_float(cost_stats.estimated_cost) or 0
        },
        "labor": {
            "totalHours": decimal_to_float(labor_stats.total_hours) or 0,
            "overtimeHours": decimal_to_float(labor_stats.overtime_hours) or 0,
            "laborCost": decimal_to_float(labor_stats.labor_cost_from_entries) or 0
        },
        "parts": {
            "cost": decimal_to_float(parts_stats.parts_cost) or 0,
            "revenue": decimal_to_float(parts_stats.parts_revenue) or 0,
            "itemsIssued": parts_stats.parts_issued or 0
        },
        "profit": {
            "amount": round(profit, 2),
            "margin": round(profit_margin, 1)
        },
        "topClients": [
            {
                "id": row.id,
                "name": row.name,
                "workOrderCount": row.work_order_count,
                "revenue": decimal_to_float(row.total_revenue) or 0
            } for row in revenue_by_client
        ],
        "monthlyTrend": monthly_trend,
        "contracts": {
            "activeCount": contracts_stats.active_contracts or 0,
            "totalValue": decimal_to_float(contracts_stats.total_contract_value) or 0,
            "totalBudget": decimal_to_float(contracts_stats.total_budget) or 0
        },
        "workOrderBreakdown": work_order_breakdown,
        "pettyCash": {
            "totalTransactions": petty_cash_stats.total_transactions or 0,
            "totalSpent": decimal_to_float(petty_cash_stats.total_spent) or 0,
            "pendingCount": petty_cash_stats.pending_count or 0,
            "pendingAmount": decimal_to_float(petty_cash_stats.pending_amount) or 0,
            "activeFunds": fund_stats.active_funds or 0,
            "totalAllocated": decimal_to_float(fund_stats.total_allocated) or 0,
            "totalBalance": decimal_to_float(fund_stats.total_balance) or 0
        }
    }


@router.get("/dashboard/procurement")
async def get_procurement_dashboard(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get procurement dashboard statistics for a specific month/year"""
    if not user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No company associated")

    company_id = user.company_id

    # Build date range for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    # ===== VENDOR STATISTICS =====
    vendor_stats = db.query(
        func.count(Vendor.id).label('total_vendors'),
        func.sum(case((Vendor.is_active == True, 1), else_=0)).label('active_vendors')
    ).filter(
        Vendor.company_id == company_id
    ).first()

    # ===== INVOICE STATISTICS =====
    invoice_stats = db.query(
        func.count(ProcessedImage.id).label('total_invoices'),
        func.sum(case((ProcessedImage.processing_status == 'pending', 1), else_=0)).label('pending'),
        func.sum(case((ProcessedImage.processing_status == 'completed', 1), else_=0)).label('completed'),
        func.sum(case((ProcessedImage.processing_status == 'failed', 1), else_=0)).label('failed')
    ).join(
        User, User.id == ProcessedImage.user_id
    ).filter(
        User.company_id == company_id,
        ProcessedImage.created_at >= start_date,
        ProcessedImage.created_at < end_date
    ).first()

    # ===== INVENTORY STATISTICS =====
    # Total items in master
    item_master_stats = db.query(
        func.count(ItemMaster.id).label('total_items'),
        func.sum(case((ItemMaster.is_active == True, 1), else_=0)).label('active_items')
    ).filter(
        ItemMaster.company_id == company_id
    ).first()

    # Stock levels
    stock_stats = db.query(
        func.coalesce(func.sum(ItemStock.quantity_on_hand), 0).label('total_on_hand'),
        func.coalesce(func.sum(ItemStock.quantity_reserved), 0).label('total_reserved'),
        func.coalesce(func.sum(ItemStock.quantity_on_order), 0).label('total_on_order'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand * ItemStock.last_cost), 0).label('total_value')
    ).filter(
        ItemStock.company_id == company_id
    ).first()

    # Low stock items count (items below minimum stock level)
    low_stock_count = db.query(func.count(ItemStock.id)).join(
        ItemMaster, ItemMaster.id == ItemStock.item_id
    ).filter(
        ItemStock.company_id == company_id,
        ItemStock.quantity_on_hand < ItemMaster.minimum_stock_level,
        ItemMaster.minimum_stock_level > 0
    ).scalar() or 0

    # ===== TRANSFER STATISTICS =====
    transfer_stats = db.query(
        func.count(ItemTransfer.id).label('total_transfers'),
        func.sum(case((ItemTransfer.status == 'draft', 1), else_=0)).label('draft'),
        func.sum(case((ItemTransfer.status == 'pending', 1), else_=0)).label('pending'),
        func.sum(case((ItemTransfer.status == 'completed', 1), else_=0)).label('completed'),
        func.sum(case((ItemTransfer.status == 'cancelled', 1), else_=0)).label('cancelled')
    ).filter(
        ItemTransfer.company_id == company_id,
        ItemTransfer.transfer_date >= start_date,
        ItemTransfer.transfer_date < end_date
    ).first()

    # ===== WAREHOUSE STATISTICS =====
    warehouse_stats = db.query(
        func.count(Warehouse.id).label('total_warehouses'),
        func.sum(case((Warehouse.is_active == True, 1), else_=0)).label('active_warehouses')
    ).filter(
        Warehouse.company_id == company_id
    ).first()

    # Stock by warehouse
    stock_by_warehouse = db.query(
        Warehouse.id,
        Warehouse.name,
        func.coalesce(func.sum(ItemStock.quantity_on_hand), 0).label('quantity'),
        func.coalesce(func.sum(ItemStock.quantity_on_hand * ItemStock.last_cost), 0).label('value')
    ).outerjoin(
        ItemStock, ItemStock.warehouse_id == Warehouse.id
    ).filter(
        Warehouse.company_id == company_id,
        Warehouse.is_active == True
    ).group_by(Warehouse.id, Warehouse.name).all()

    # ===== TRANSACTION ACTIVITY (Last 6 months) =====
    monthly_trend = []
    for i in range(5, -1, -1):
        trend_month = month - i
        trend_year = year
        if trend_month <= 0:
            trend_month += 12
            trend_year -= 1

        trend_start = datetime(trend_year, trend_month, 1)
        if trend_month == 12:
            trend_end = datetime(trend_year + 1, 1, 1)
        else:
            trend_end = datetime(trend_year, trend_month + 1, 1)

        # Count invoices and transfers for this month
        month_invoices = db.query(func.count(ProcessedImage.id)).join(
            User, User.id == ProcessedImage.user_id
        ).filter(
            User.company_id == company_id,
            ProcessedImage.created_at >= trend_start,
            ProcessedImage.created_at < trend_end
        ).scalar() or 0

        month_transfers = db.query(func.count(ItemTransfer.id)).filter(
            ItemTransfer.company_id == company_id,
            ItemTransfer.transfer_date >= trend_start,
            ItemTransfer.transfer_date < trend_end
        ).scalar() or 0

        # Get ledger transaction value for this month
        month_ledger = db.query(
            func.coalesce(func.sum(case(
                (ItemLedger.transaction_type.in_(['RECEIVE_INVOICE', 'RECEIVE_MANUAL']), ItemLedger.total_cost),
                else_=0
            )), 0).label('received_value'),
            func.coalesce(func.sum(case(
                (ItemLedger.transaction_type.in_(['ISSUE_WORK_ORDER', 'ISSUE_MANUAL']), ItemLedger.total_cost),
                else_=0
            )), 0).label('issued_value')
        ).filter(
            ItemLedger.company_id == company_id,
            ItemLedger.transaction_date >= trend_start,
            ItemLedger.transaction_date < trend_end
        ).first()

        monthly_trend.append({
            "month": trend_month,
            "year": trend_year,
            "monthName": datetime(trend_year, trend_month, 1).strftime("%b"),
            "invoices": month_invoices,
            "transfers": month_transfers,
            "receivedValue": decimal_to_float(month_ledger.received_value) or 0,
            "issuedValue": decimal_to_float(month_ledger.issued_value) or 0
        })

    # ===== TOP VENDORS BY INVOICE COUNT =====
    top_vendors = db.query(
        Vendor.id,
        Vendor.name,
        func.count(ProcessedImage.id).label('invoice_count')
    ).outerjoin(
        ProcessedImage, ProcessedImage.vendor_id == Vendor.id
    ).filter(
        Vendor.company_id == company_id,
        Vendor.is_active == True
    ).group_by(Vendor.id, Vendor.name).order_by(
        func.count(ProcessedImage.id).desc()
    ).limit(5).all()

    # ===== TOP ITEMS BY MOVEMENT =====
    top_items = db.query(
        ItemMaster.id,
        ItemMaster.item_number,
        ItemMaster.description,
        func.count(ItemLedger.id).label('transaction_count'),
        func.coalesce(func.sum(func.abs(ItemLedger.quantity)), 0).label('total_movement')
    ).join(
        ItemLedger, ItemLedger.item_id == ItemMaster.id
    ).filter(
        ItemMaster.company_id == company_id,
        ItemLedger.transaction_date >= start_date,
        ItemLedger.transaction_date < end_date
    ).group_by(ItemMaster.id, ItemMaster.item_number, ItemMaster.description).order_by(
        func.sum(func.abs(ItemLedger.quantity)).desc()
    ).limit(5).all()

    return {
        "month": month,
        "year": year,
        "vendors": {
            "total": vendor_stats.total_vendors or 0,
            "active": vendor_stats.active_vendors or 0
        },
        "invoices": {
            "total": invoice_stats.total_invoices or 0,
            "pending": invoice_stats.pending or 0,
            "completed": invoice_stats.completed or 0,
            "failed": invoice_stats.failed or 0
        },
        "inventory": {
            "totalItems": item_master_stats.total_items or 0,
            "activeItems": item_master_stats.active_items or 0,
            "quantityOnHand": decimal_to_float(stock_stats.total_on_hand) or 0,
            "quantityReserved": decimal_to_float(stock_stats.total_reserved) or 0,
            "quantityOnOrder": decimal_to_float(stock_stats.total_on_order) or 0,
            "totalValue": decimal_to_float(stock_stats.total_value) or 0,
            "lowStockCount": low_stock_count
        },
        "transfers": {
            "total": transfer_stats.total_transfers or 0,
            "draft": transfer_stats.draft or 0,
            "pending": transfer_stats.pending or 0,
            "completed": transfer_stats.completed or 0,
            "cancelled": transfer_stats.cancelled or 0
        },
        "warehouses": {
            "total": warehouse_stats.total_warehouses or 0,
            "active": warehouse_stats.active_warehouses or 0,
            "stockByWarehouse": [
                {
                    "id": row.id,
                    "name": row.name,
                    "quantity": decimal_to_float(row.quantity) or 0,
                    "value": decimal_to_float(row.value) or 0
                } for row in stock_by_warehouse
            ]
        },
        "monthlyTrend": monthly_trend,
        "topVendors": [
            {
                "id": row.id,
                "name": row.name,
                "invoiceCount": row.invoice_count
            } for row in top_vendors
        ],
        "topItems": [
            {
                "id": row.id,
                "itemNumber": row.item_number,
                "description": row.description[:50] + "..." if len(row.description) > 50 else row.description,
                "transactionCount": row.transaction_count,
                "totalMovement": decimal_to_float(row.total_movement) or 0
            } for row in top_items
        ]
    }
