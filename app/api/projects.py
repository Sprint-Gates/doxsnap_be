from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_
from typing import Optional, List
from datetime import date
from decimal import Decimal
from app.database import get_db
from app.models import (
    Project, Site, Client, User, Company, ProcessedImage,
    WorkOrder, WorkOrderTimeEntry, WorkOrderSparePart, Technician, AddressBook
)
from app.utils.security import verify_token
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)  # verify_token returns the email directly

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


class ProjectCreate(BaseModel):
    site_id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = "active"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    currency: Optional[str] = "USD"
    labor_markup_percent: Optional[float] = 0
    parts_markup_percent: Optional[float] = 0
    notes: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    labor_markup_percent: Optional[float] = None
    parts_markup_percent: Optional[float] = None
    notes: Optional[str] = None


def project_to_response(project: Project, db: Session) -> dict:
    """Convert Project model to response dict"""
    invoices_count = db.query(ProcessedImage).filter(ProcessedImage.project_id == project.id).count()

    # Calculate total spent from invoices
    total_spent = 0.0
    invoices = db.query(ProcessedImage).filter(ProcessedImage.project_id == project.id).all()
    for invoice in invoices:
        if invoice.structured_data:
            import json
            try:
                data = json.loads(invoice.structured_data)
                total = data.get("financial_details", {}).get("total_after_tax", 0)
                if total:
                    total_spent += float(total)
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "id": project.id,
        "site_id": project.site_id,
        "site_name": project.site.name if project.site else None,
        "client_id": project.site.client_id if project.site else None,
        "client_name": project.site.client.name if project.site and project.site.client else None,
        "name": project.name,
        "code": project.code,
        "description": project.description,
        "status": project.status,
        "start_date": project.start_date.isoformat() if project.start_date else None,
        "end_date": project.end_date.isoformat() if project.end_date else None,
        "budget": float(project.budget) if project.budget else None,
        "currency": project.currency,
        "labor_markup_percent": float(project.labor_markup_percent) if project.labor_markup_percent else 0,
        "parts_markup_percent": float(project.parts_markup_percent) if project.parts_markup_percent else 0,
        "notes": project.notes,
        "invoices_count": invoices_count,
        "total_spent": total_spent,
        "budget_remaining": float(project.budget) - total_spent if project.budget else None,
        "created_at": project.created_at.isoformat()
    }


@router.get("/projects/")
async def get_projects(
    site_id: Optional[int] = None,
    client_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all projects for the current company"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Build query based on role
    if user.role == "operator":
        # Operators only see projects from their assigned sites
        site_ids = [s.id for s in user.assigned_sites]
        query = db.query(Project).filter(Project.site_id.in_(site_ids))
    else:
        # Admins see all projects from company's sites (via client_id or address_book_id)
        client_site_ids = db.query(Site.id).join(Client).filter(
            Client.company_id == user.company_id
        ).subquery()
        ab_site_ids = db.query(Site.id).join(AddressBook, Site.address_book_id == AddressBook.id).filter(
            AddressBook.company_id == user.company_id
        ).subquery()
        query = db.query(Project).filter(
            or_(Project.site_id.in_(client_site_ids), Project.site_id.in_(ab_site_ids))
        )

    if site_id:
        query = query.filter(Project.site_id == site_id)

    if client_id:
        query = query.join(Site).filter(Site.client_id == client_id)

    if status_filter:
        query = query.filter(Project.status == status_filter)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Project.name.ilike(search_term)) |
            (Project.code.ilike(search_term)) |
            (Project.description.ilike(search_term))
        )

    projects = query.order_by(Project.created_at.desc()).all()

    return [project_to_response(project, db) for project in projects]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific project"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    project = db.query(Project).join(Site).join(Client).filter(
        Project.id == project_id,
        Client.company_id == user.company_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Operators can only access projects from their assigned sites
    if user.role == "operator":
        if project.site_id not in [s.id for s in user.assigned_sites]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this project"
            )

    return project_to_response(project, db)


@router.post("/projects/")
async def create_project(
    data: ProjectCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new project (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Verify site belongs to company (supports both client_id and address_book_id paths)
    site = db.query(Site).filter(Site.id == data.site_id).first()

    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site not found"
        )

    # Check access via client_id (legacy) or address_book_id (new)
    has_access = False
    if site.client_id:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if client and client.company_id == user.company_id:
            has_access = True
    if not has_access and site.address_book_id:
        ab_entry = db.query(AddressBook).filter(AddressBook.id == site.address_book_id).first()
        if ab_entry and ab_entry.company_id == user.company_id:
            has_access = True

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this site"
        )

    # Check plan limits (count projects from both client_id and address_book_id paths)
    company = db.query(Company).filter(Company.id == user.company_id).first()
    if company and company.plan:
        # Get all site IDs accessible to this company
        client_site_ids = db.query(Site.id).join(Client).filter(
            Client.company_id == user.company_id
        ).subquery()
        ab_site_ids = db.query(Site.id).join(AddressBook, Site.address_book_id == AddressBook.id).filter(
            AddressBook.company_id == user.company_id
        ).subquery()

        current_count = db.query(Project).filter(
            (Project.site_id.in_(client_site_ids)) | (Project.site_id.in_(ab_site_ids))
        ).count()
        if current_count >= company.plan.max_projects:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Project limit reached ({company.plan.max_projects}). Upgrade your plan to add more projects."
            )

    # Validate dates
    if data.start_date and data.end_date:
        if data.end_date < data.start_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End date cannot be before start date"
            )

    try:
        project = Project(
            site_id=data.site_id,
            name=data.name,
            code=data.code,
            description=data.description,
            status=data.status or "active",
            start_date=data.start_date,
            end_date=data.end_date,
            budget=Decimal(str(data.budget)) if data.budget else None,
            currency=data.currency or "USD",
            labor_markup_percent=Decimal(str(data.labor_markup_percent)) if data.labor_markup_percent else Decimal("0"),
            parts_markup_percent=Decimal(str(data.parts_markup_percent)) if data.parts_markup_percent else Decimal("0"),
            notes=data.notes
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        logger.info(f"Project '{project.name}' created by '{user.email}'")

        return project_to_response(project, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating project: {str(e)}"
        )


@router.put("/projects/{project_id}")
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a project (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    project = db.query(Project).join(Site).join(Client).filter(
        Project.id == project_id,
        Client.company_id == user.company_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    try:
        update_data = data.dict(exclude_unset=True)

        # Validate dates if both are being updated or exist
        start = update_data.get("start_date", project.start_date)
        end = update_data.get("end_date", project.end_date)
        if start and end and end < start:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="End date cannot be before start date"
            )

        for field, value in update_data.items():
            if value is not None:
                if field in ["budget", "labor_markup_percent", "parts_markup_percent"]:
                    setattr(project, field, Decimal(str(value)))
                else:
                    setattr(project, field, value)

        db.commit()
        db.refresh(project)

        logger.info(f"Project '{project.name}' updated by '{user.email}'")

        return project_to_response(project, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating project: {str(e)}"
        )


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Archive a project (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    project = db.query(Project).join(Site).join(Client).filter(
        Project.id == project_id,
        Client.company_id == user.company_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    try:
        project.status = "archived"
        db.commit()

        logger.info(f"Project '{project.name}' archived by '{user.email}'")

        return {
            "success": True,
            "message": f"Project '{project.name}' has been archived"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error archiving project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error archiving project: {str(e)}"
        )


@router.get("/projects/{project_id}/invoices")
async def get_project_invoices(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all invoices for a project"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    project = db.query(Project).join(Site).join(Client).filter(
        Project.id == project_id,
        Client.company_id == user.company_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Operators can only access projects from their assigned sites
    if user.role == "operator":
        if project.site_id not in [s.id for s in user.assigned_sites]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this project"
            )

    invoices = db.query(ProcessedImage).filter(ProcessedImage.project_id == project_id).order_by(ProcessedImage.created_at.desc()).all()

    import json
    results = []
    for invoice in invoices:
        structured_data = None
        if invoice.structured_data:
            try:
                structured_data = json.loads(invoice.structured_data)
            except (json.JSONDecodeError, TypeError):
                pass

        results.append({
            "id": str(invoice.id),
            "image_id": str(invoice.id),
            "original_filename": invoice.original_filename,
            "document_type": invoice.document_type,
            "processing_status": invoice.processing_status,
            "extraction_confidence": invoice.extraction_confidence,
            "created_at": invoice.created_at.isoformat(),
            "structured_data": structured_data
        })

    return results


@router.post("/projects/{project_id}/invoices/{invoice_id}")
async def link_invoice_to_project(
    project_id: int,
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Link an invoice to a project"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Verify project belongs to company
    project = db.query(Project).join(Site).join(Client).filter(
        Project.id == project_id,
        Client.company_id == user.company_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Verify invoice belongs to company's users
    invoice = db.query(ProcessedImage).join(User).filter(
        ProcessedImage.id == invoice_id,
        User.company_id == user.company_id
    ).first()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found"
        )

    try:
        invoice.project_id = project_id
        db.commit()

        logger.info(f"Invoice {invoice_id} linked to project '{project.name}' by '{user.email}'")

        return {
            "success": True,
            "message": f"Invoice linked to project '{project.name}'"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error linking invoice to project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error linking invoice to project: {str(e)}"
        )


@router.delete("/projects/{project_id}/invoices/{invoice_id}")
async def unlink_invoice_from_project(
    project_id: int,
    invoice_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Unlink an invoice from a project"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    invoice = db.query(ProcessedImage).join(User).filter(
        ProcessedImage.id == invoice_id,
        ProcessedImage.project_id == project_id,
        User.company_id == user.company_id
    ).first()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found in this project"
        )

    try:
        invoice.project_id = None
        db.commit()

        logger.info(f"Invoice {invoice_id} unlinked from project by '{user.email}'")

        return {
            "success": True,
            "message": "Invoice unlinked from project"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error unlinking invoice from project: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error unlinking invoice from project: {str(e)}"
        )


def decimal_to_float(val):
    """Convert Decimal to float for JSON serialization"""
    if val is None:
        return 0
    if isinstance(val, Decimal):
        return float(val)
    return val


@router.get("/projects/{project_id}/cost-center")
async def get_project_cost_center(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get cost center breakdown for a project"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Get project
    project = db.query(Project).join(Site).join(Client).filter(
        Project.id == project_id,
        Client.company_id == user.company_id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # Get all work orders for this project
    work_orders = db.query(WorkOrder).filter(
        WorkOrder.project_id == project_id
    ).all()

    wo_ids = [wo.id for wo in work_orders]

    # Calculate labor costs from time entries
    labor_stats = db.query(
        func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('total_hours'),
        func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('total_cost'),
        func.count(WorkOrderTimeEntry.id).label('entries_count')
    ).filter(
        WorkOrderTimeEntry.work_order_id.in_(wo_ids) if wo_ids else False
    ).first()

    # Calculate parts costs
    parts_stats = db.query(
        func.coalesce(func.sum(WorkOrderSparePart.total_cost), 0).label('total_cost'),
        func.coalesce(func.sum(WorkOrderSparePart.quantity), 0).label('total_quantity'),
        func.count(WorkOrderSparePart.id).label('parts_count')
    ).filter(
        WorkOrderSparePart.work_order_id.in_(wo_ids) if wo_ids else False
    ).first()

    # Work order stats by status
    wo_by_status = {}
    wo_by_type = {}
    total_billable_amount = 0

    for wo in work_orders:
        # Count by status
        wo_by_status[wo.status] = wo_by_status.get(wo.status, 0) + 1
        # Count by type
        wo_by_type[wo.work_order_type] = wo_by_type.get(wo.work_order_type, 0) + 1
        # Sum billable amounts
        if wo.is_billable and wo.billable_amount:
            total_billable_amount += float(wo.billable_amount)

    # Get labor breakdown by technician (using address_book_id, falling back to technician_id)
    # Query by address_book_id first (new approach)
    ab_labor = db.query(
        WorkOrderTimeEntry.address_book_id,
        func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('hours'),
        func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('cost')
    ).filter(
        WorkOrderTimeEntry.work_order_id.in_(wo_ids) if wo_ids else False,
        WorkOrderTimeEntry.address_book_id.isnot(None)
    ).group_by(WorkOrderTimeEntry.address_book_id).all()

    # Query by legacy technician_id (for old entries without address_book_id)
    legacy_labor = db.query(
        WorkOrderTimeEntry.technician_id,
        func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('hours'),
        func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('cost')
    ).filter(
        WorkOrderTimeEntry.work_order_id.in_(wo_ids) if wo_ids else False,
        WorkOrderTimeEntry.address_book_id.is_(None),
        WorkOrderTimeEntry.technician_id.isnot(None)
    ).group_by(WorkOrderTimeEntry.technician_id).all()

    # Get names for address book entries
    ab_names = {}
    if ab_labor:
        ab_ids = [t.address_book_id for t in ab_labor]
        ab_entries = db.query(AddressBook).filter(AddressBook.id.in_(ab_ids)).all()
        ab_names = {ab.id: ab.alpha_name for ab in ab_entries}

    # Get names for legacy technicians
    tech_names = {}
    if legacy_labor:
        tech_ids = [t.technician_id for t in legacy_labor]
        technicians = db.query(Technician).filter(Technician.id.in_(tech_ids)).all()
        tech_names = {t.id: t.name for t in technicians}

    # Get project markup for calculating technician billable
    project_labor_markup = decimal_to_float(project.labor_markup_percent) or 0

    labor_by_technician = []

    # Add address book entries
    for t in ab_labor:
        labor_by_technician.append({
            "technician_id": t.address_book_id,
            "technician_name": ab_names.get(t.address_book_id, "Unknown"),
            "hours": decimal_to_float(t.hours),
            "cost": decimal_to_float(t.cost),
            "billable": decimal_to_float(t.cost) * (1 + project_labor_markup / 100)
        })

    # Add legacy technician entries
    for t in legacy_labor:
        labor_by_technician.append({
            "technician_id": t.technician_id,
            "technician_name": tech_names.get(t.technician_id, "Unknown"),
            "hours": decimal_to_float(t.hours),
            "cost": decimal_to_float(t.cost),
            "billable": decimal_to_float(t.cost) * (1 + project_labor_markup / 100)
        })

    # Get work order details for breakdown
    wo_details = []
    for wo in work_orders:
        # Get labor cost for this WO
        wo_labor = db.query(
            func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('hours'),
            func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('cost')
        ).filter(WorkOrderTimeEntry.work_order_id == wo.id).first()

        # Get parts cost for this WO
        wo_parts = db.query(
            func.coalesce(func.sum(WorkOrderSparePart.total_cost), 0).label('cost')
        ).filter(WorkOrderSparePart.work_order_id == wo.id).first()

        labor_cost = decimal_to_float(wo_labor.cost) if wo_labor else 0
        parts_cost = decimal_to_float(wo_parts.cost) if wo_parts else 0
        total_cost = labor_cost + parts_cost

        # Calculate billable with markup
        labor_billable = labor_cost * (1 + decimal_to_float(wo.labor_markup_percent or 0) / 100)
        parts_billable = parts_cost * (1 + decimal_to_float(wo.parts_markup_percent or 0) / 100)
        total_billable = labor_billable + parts_billable if wo.is_billable else 0

        wo_details.append({
            "id": wo.id,
            "work_order_number": wo.wo_number,
            "title": wo.title,
            "type": wo.work_order_type,
            "status": wo.status,
            "is_billable": wo.is_billable,
            "labor_hours": decimal_to_float(wo_labor.hours) if wo_labor else 0,
            "labor_cost": labor_cost,
            "parts_cost": parts_cost,
            "total_cost": total_cost,
            "labor_markup_percent": decimal_to_float(wo.labor_markup_percent) or 0,
            "parts_markup_percent": decimal_to_float(wo.parts_markup_percent) or 0,
            "billable_amount": total_billable,
            "profit": total_billable - total_cost if wo.is_billable else 0,
            "created_at": wo.created_at.isoformat() if wo.created_at else None,
            "completed_at": wo.actual_end.isoformat() if wo.actual_end else None
        })

    # Calculate totals
    total_labor_cost = decimal_to_float(labor_stats.total_cost) if labor_stats else 0
    total_parts_cost = decimal_to_float(parts_stats.total_cost) if parts_stats else 0
    total_cost = total_labor_cost + total_parts_cost

    # Calculate billable totals with markup
    total_labor_billable = sum(wo["labor_cost"] * (1 + wo["labor_markup_percent"] / 100) for wo in wo_details if wo["is_billable"])
    total_parts_billable = sum(wo["parts_cost"] * (1 + wo["parts_markup_percent"] / 100) for wo in wo_details if wo["is_billable"])
    total_billable = total_labor_billable + total_parts_billable
    total_profit = total_billable - sum(wo["total_cost"] for wo in wo_details if wo["is_billable"])

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "code": project.code,
            "status": project.status,
            "budget": decimal_to_float(project.budget),
            "currency": project.currency,
            "labor_markup_percent": decimal_to_float(project.labor_markup_percent),
            "parts_markup_percent": decimal_to_float(project.parts_markup_percent),
            "site_name": project.site.name if project.site else None,
            "client_name": project.site.client.name if project.site and project.site.client else None
        },
        "summary": {
            "total_work_orders": len(work_orders),
            "work_orders_by_status": wo_by_status,
            "work_orders_by_type": wo_by_type,
            "total_labor_hours": decimal_to_float(labor_stats.total_hours) if labor_stats else 0,
            "labor_cost": total_labor_cost,
            "parts_cost": total_parts_cost,
            "total_cost": total_cost,
            "labor_billable": total_labor_billable,
            "parts_billable": total_parts_billable,
            "billable_amount": total_billable,
            "profit": total_profit,
            "profit_margin": round((total_profit / total_billable * 100), 1) if total_billable > 0 else 0,
            "budget_used": total_cost,
            "budget_remaining": decimal_to_float(project.budget) - total_cost if project.budget else None,
            "budget_used_percent": round((total_cost / decimal_to_float(project.budget) * 100), 1) if project.budget and decimal_to_float(project.budget) > 0 else None
        },
        "labor_by_technician": labor_by_technician,
        "work_orders": wo_details
    }
