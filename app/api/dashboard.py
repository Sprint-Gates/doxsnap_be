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
    work_order_technicians
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
