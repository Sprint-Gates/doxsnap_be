"""
RFQ (Request for Quotation) API Endpoints

Provides endpoints for:
- RFQ CRUD operations
- Item management
- Vendor management
- Quote management
- Comparison and evaluation
- PR conversion
- Audit trail / timeline
"""
import json
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_

from app.database import get_db
from app.api.auth import get_current_user
from app.models import (
    User, Company, Project, Site, WorkOrder, AddressBook, ItemMaster,
    RFQ, RFQItem, RFQVendor, RFQQuote, RFQQuoteLine,
    RFQAuditTrail, RFQSiteVisit, RFQSiteVisitPhoto, RFQComparison, RFQDocument,
    PurchaseRequest
)
from app.schemas import (
    RFQCreate, RFQUpdate, RFQSubmit, RFQCancel, RFQ as RFQSchema,
    RFQList, RFQListResponse, RFQStats,
    RFQItemCreate, RFQItemUpdate, RFQItem as RFQItemSchema,
    RFQVendorCreate, RFQVendorUpdate, RFQVendorContact, RFQVendor as RFQVendorSchema,
    RFQQuoteCreate, RFQQuoteUpdate, RFQQuoteStatusUpdate, RFQQuote as RFQQuoteSchema,
    RFQQuoteLineCreate, RFQQuoteLineUpdate, RFQQuoteLine as RFQQuoteLineSchema,
    RFQSiteVisitCreate, RFQSiteVisitUpdate, RFQSiteVisitComplete, RFQSiteVisit as RFQSiteVisitSchema,
    RFQComparisonCreate, RFQComparisonUpdate, RFQComparisonRecommend, RFQComparison as RFQComparisonSchema,
    RFQAuditTrailEntry, RFQTimeline, RFQComparisonMatrix,
    RFQConvertToPR, RFQConvertToPRResponse, RFQAddNote
)
from app.services.rfq_service import (
    generate_rfq_number, log_rfq_action,
    log_rfq_created, log_rfq_submitted, log_rfq_status_change,
    log_vendor_added, log_vendor_removed, log_vendor_contacted,
    log_quote_received, log_quote_evaluated, log_vendor_selected,
    log_item_added, log_item_removed, log_note_added, log_document_uploaded,
    validate_submission, validate_comparison, validate_conversion,
    convert_rfq_to_pr, format_timeline_entry
)

router = APIRouter()


# =============================================================================
# Auth Helpers
# =============================================================================

def require_admin(user: User = Depends(get_current_user)):
    """Require user to be admin or accounting role"""
    if user.role not in ["admin", "accounting"]:
        raise HTTPException(
            status_code=403,
            detail="Admin or accounting role required"
        )
    return user


# =============================================================================
# Helper Functions
# =============================================================================

def get_rfq_or_404(db: Session, rfq_id: int, company_id: int) -> RFQ:
    """Get RFQ by ID or raise 404"""
    rfq = db.query(RFQ).options(
        joinedload(RFQ.items),
        joinedload(RFQ.vendors).joinedload(RFQVendor.address_book),
        joinedload(RFQ.quotes).joinedload(RFQQuote.lines),
        joinedload(RFQ.site_visit),
        joinedload(RFQ.comparison),
        joinedload(RFQ.documents)
    ).filter(
        RFQ.id == rfq_id,
        RFQ.company_id == company_id,
        RFQ.deleted_at.is_(None)
    ).first()

    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    return rfq


def serialize_rfq(rfq: RFQ) -> dict:
    """Serialize RFQ to response format"""
    return {
        "id": rfq.id,
        "company_id": rfq.company_id,
        "rfq_number": rfq.rfq_number,
        "rfq_type": rfq.rfq_type,
        "status": rfq.status,
        "priority": rfq.priority,
        "project_id": rfq.project_id,
        "project_name": rfq.project.name if rfq.project else None,
        "site_id": rfq.site_id,
        "site_name": rfq.site.name if rfq.site else None,
        "work_order_id": rfq.work_order_id,
        "work_order_number": rfq.work_order.wo_number if rfq.work_order else None,
        "title": rfq.title,
        "description": rfq.description,
        "required_date": rfq.required_date,
        "currency": rfq.currency,
        "estimated_budget": float(rfq.estimated_budget) if rfq.estimated_budget else None,
        "created_by": rfq.created_by,
        "created_by_name": rfq.creator.name if rfq.creator else None,
        "created_at": rfq.created_at,
        "updated_at": rfq.updated_at,
        "submitted_at": rfq.submitted_at,
        "submitted_by": rfq.submitted_by,
        "submitted_by_name": rfq.submitter.name if rfq.submitter else None,
        "cancelled_at": rfq.cancelled_at,
        "cancelled_by": rfq.cancelled_by,
        "cancellation_reason": rfq.cancellation_reason,
        "converted_to_pr_at": rfq.converted_to_pr_at,
        "converted_by": rfq.converted_by,
        "notes": rfq.notes,
        "items": [serialize_rfq_item(item) for item in rfq.items],
        "vendors": [serialize_rfq_vendor(vendor) for vendor in rfq.vendors],
        "quotes": [serialize_rfq_quote(quote) for quote in rfq.quotes],
        "site_visit": serialize_site_visit(rfq.site_visit) if rfq.site_visit else None,
        "comparison": serialize_comparison(rfq.comparison) if rfq.comparison else None,
        "documents": [serialize_document(doc) for doc in rfq.documents],
        "item_count": len(rfq.items),
        "vendor_count": len(rfq.vendors),
        "quote_count": len(rfq.quotes)
    }


def serialize_rfq_item(item: RFQItem) -> dict:
    """Serialize RFQ item"""
    return {
        "id": item.id,
        "rfq_id": item.rfq_id,
        "item_id": item.item_id,
        "item_number": item.item_number,
        "description": item.description,
        "quantity_requested": float(item.quantity_requested),
        "unit": item.unit,
        "estimated_unit_cost": float(item.estimated_unit_cost) if item.estimated_unit_cost else None,
        "estimated_total": float(item.estimated_total) if item.estimated_total else None,
        "service_scope": item.service_scope,
        "visit_date": item.visit_date,
        "visit_location": item.visit_location,
        "notes": item.notes,
        "created_at": item.created_at,
        "item_name": item.item.description if item.item else None
    }


def serialize_rfq_vendor(vendor: RFQVendor) -> dict:
    """Serialize RFQ vendor"""
    ab = vendor.address_book
    return {
        "id": vendor.id,
        "rfq_id": vendor.rfq_id,
        "address_book_id": vendor.address_book_id,
        "vendor_name": ab.display_name if ab else None,
        "vendor_email": ab.email if ab else None,
        "vendor_phone": ab.phone if ab else None,
        "contact_method": vendor.contact_method,
        "contact_date": vendor.contact_date,
        "contacted_by": vendor.contacted_by,
        "contacted_by_name": vendor.contacted_by_user.name if vendor.contacted_by_user else None,
        "is_contacted": vendor.is_contacted,
        "is_selected": vendor.is_selected,
        "selection_reason": vendor.selection_reason,
        "vendor_notes": vendor.vendor_notes,
        "created_at": vendor.created_at,
        "quote_count": len(vendor.quotes) if vendor.quotes else 0
    }


def serialize_rfq_quote(quote: RFQQuote) -> dict:
    """Serialize RFQ quote"""
    return {
        "id": quote.id,
        "rfq_id": quote.rfq_id,
        "rfq_vendor_id": quote.rfq_vendor_id,
        "vendor_name": quote.vendor.address_book.display_name if quote.vendor and quote.vendor.address_book else None,
        "vendor_quote_number": quote.vendor_quote_number,
        "quote_date": quote.quote_date,
        "validity_date": quote.validity_date,
        "subtotal": float(quote.subtotal),
        "tax_amount": float(quote.tax_amount),
        "quote_total": float(quote.quote_total),
        "currency": quote.currency,
        "delivery_days": quote.delivery_days,
        "delivery_date": quote.delivery_date,
        "payment_terms": quote.payment_terms,
        "warranty_terms": quote.warranty_terms,
        "status": quote.status,
        "rejection_reason": quote.rejection_reason,
        "document_id": quote.document_id,
        "evaluation_score": float(quote.evaluation_score) if quote.evaluation_score else None,
        "evaluation_notes": quote.evaluation_notes,
        "received_at": quote.received_at,
        "received_by": quote.received_by,
        "received_by_name": quote.receiver.name if quote.receiver else None,
        "updated_at": quote.updated_at,
        "notes": quote.notes,
        "lines": [serialize_quote_line(line) for line in quote.lines]
    }


def serialize_quote_line(line: RFQQuoteLine) -> dict:
    """Serialize quote line"""
    return {
        "id": line.id,
        "rfq_quote_id": line.rfq_quote_id,
        "rfq_item_id": line.rfq_item_id,
        "item_description": line.item_description,
        "quantity_quoted": float(line.quantity_quoted),
        "unit": line.unit,
        "unit_price": float(line.unit_price),
        "total_price": float(line.total_price),
        "notes": line.notes,
        "rfq_item_description": line.rfq_item.description if line.rfq_item else None
    }


def serialize_site_visit(visit: RFQSiteVisit) -> dict:
    """Serialize site visit"""
    return {
        "id": visit.id,
        "rfq_id": visit.rfq_id,
        "scheduled_date": visit.scheduled_date,
        "scheduled_time": str(visit.scheduled_time) if visit.scheduled_time else None,
        "actual_date": visit.actual_date,
        "actual_time": str(visit.actual_time) if visit.actual_time else None,
        "visit_status": visit.visit_status,
        "site_contact_person": visit.site_contact_person,
        "site_contact_phone": visit.site_contact_phone,
        "site_contact_email": visit.site_contact_email,
        "visit_notes": visit.visit_notes,
        "issues_identified": visit.issues_identified,
        "recommendations": visit.recommendations,
        "created_at": visit.created_at,
        "updated_at": visit.updated_at,
        "completed_by": visit.completed_by,
        "completed_by_name": visit.completer.name if visit.completer else None,
        "completed_at": visit.completed_at,
        "photos": []  # TODO: Add photo serialization
    }


def serialize_comparison(comparison: RFQComparison) -> dict:
    """Serialize comparison"""
    criteria = json.loads(comparison.evaluation_criteria) if comparison.evaluation_criteria else None
    return {
        "id": comparison.id,
        "rfq_id": comparison.rfq_id,
        "comparison_status": comparison.comparison_status,
        "evaluation_criteria": criteria,
        "recommended_vendor_id": comparison.recommended_vendor_id,
        "recommended_vendor_name": comparison.recommended_vendor.address_book.display_name if comparison.recommended_vendor and comparison.recommended_vendor.address_book else None,
        "recommendation_notes": comparison.recommendation_notes,
        "evaluator_notes": comparison.evaluator_notes,
        "created_by": comparison.created_by,
        "created_by_name": comparison.creator.name if comparison.creator else None,
        "created_at": comparison.created_at,
        "updated_at": comparison.updated_at,
        "completed_at": comparison.completed_at,
        "completed_by": comparison.completed_by,
        "completed_by_name": comparison.completer.name if comparison.completer else None
    }


def serialize_document(doc: RFQDocument) -> dict:
    """Serialize document"""
    return {
        "id": doc.id,
        "rfq_id": doc.rfq_id,
        "image_id": doc.image_id,
        "image_url": doc.image.file_url if doc.image else None,
        "document_type": doc.document_type,
        "title": doc.title,
        "description": doc.description,
        "uploaded_at": doc.uploaded_at,
        "uploaded_by": doc.uploaded_by,
        "uploaded_by_name": doc.uploader.name if doc.uploader else None
    }


# =============================================================================
# RFQ CRUD Endpoints
# =============================================================================

@router.get("", response_model=RFQListResponse)
async def list_rfqs(
    status: Optional[str] = None,
    rfq_type: Optional[str] = None,
    project_id: Optional[int] = None,
    site_id: Optional[int] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """List RFQs with filters"""
    query = db.query(RFQ).filter(
        RFQ.company_id == current_user.company_id,
        RFQ.deleted_at.is_(None)
    )

    # Apply filters
    if status:
        query = query.filter(RFQ.status == status)
    if rfq_type:
        query = query.filter(RFQ.rfq_type == rfq_type)
    if project_id:
        query = query.filter(RFQ.project_id == project_id)
    if site_id:
        query = query.filter(RFQ.site_id == site_id)
    if priority:
        query = query.filter(RFQ.priority == priority)
    if from_date:
        query = query.filter(RFQ.created_at >= from_date)
    if to_date:
        query = query.filter(RFQ.created_at <= to_date)
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            RFQ.rfq_number.ilike(search_term),
            RFQ.title.ilike(search_term)
        ))

    # Get total count
    total = query.count()

    # Pagination
    offset = (page - 1) * size
    rfqs = query.options(
        joinedload(RFQ.project),
        joinedload(RFQ.site),
        joinedload(RFQ.work_order),
        joinedload(RFQ.creator)
    ).order_by(RFQ.created_at.desc()).offset(offset).limit(size).all()

    # Serialize
    rfq_list = []
    for rfq in rfqs:
        rfq_list.append({
            "id": rfq.id,
            "rfq_number": rfq.rfq_number,
            "rfq_type": rfq.rfq_type,
            "status": rfq.status,
            "priority": rfq.priority,
            "title": rfq.title,
            "project_name": rfq.project.name if rfq.project else None,
            "site_name": rfq.site.name if rfq.site else None,
            "work_order_number": rfq.work_order.wo_number if rfq.work_order else None,
            "required_date": rfq.required_date,
            "estimated_budget": float(rfq.estimated_budget) if rfq.estimated_budget else None,
            "currency": rfq.currency,
            "created_by_name": rfq.creator.name if rfq.creator else "Unknown",
            "created_at": rfq.created_at,
            "submitted_at": rfq.submitted_at,
            "item_count": len(rfq.items) if rfq.items else 0,
            "vendor_count": len(rfq.vendors) if rfq.vendors else 0,
            "quote_count": len(rfq.quotes) if rfq.quotes else 0
        })

    return {
        "rfqs": rfq_list,
        "total": total,
        "page": page,
        "size": size
    }


@router.get("/stats", response_model=RFQStats)
async def get_rfq_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get RFQ statistics for dashboard"""
    base_query = db.query(RFQ).filter(
        RFQ.company_id == current_user.company_id,
        RFQ.deleted_at.is_(None)
    )

    # Status counts
    total = base_query.count()
    draft = base_query.filter(RFQ.status == "draft").count()
    submitted = base_query.filter(RFQ.status == "submitted").count()
    quote_pending = base_query.filter(RFQ.status == "quote_pending").count()
    comparison = base_query.filter(RFQ.status == "comparison").count()
    converted = base_query.filter(RFQ.status == "converted_to_pr").count()
    cancelled = base_query.filter(RFQ.status == "cancelled").count()

    # This month
    now = datetime.now()
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = base_query.filter(RFQ.created_at >= first_of_month).count()

    # Total quotes received
    total_quotes = db.query(RFQQuote).join(RFQ).filter(
        RFQ.company_id == current_user.company_id,
        RFQ.deleted_at.is_(None)
    ).count()

    return {
        "total_rfqs": total,
        "draft": draft,
        "submitted": submitted,
        "quote_pending": quote_pending,
        "comparison": comparison,
        "converted_to_pr": converted,
        "cancelled": cancelled,
        "this_month": this_month,
        "total_quotes_received": total_quotes
    }


@router.get("/{rfq_id}")
async def get_rfq(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get RFQ details"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)
    return serialize_rfq(rfq)


@router.post("")
async def create_rfq(
    rfq_data: RFQCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create new RFQ"""
    # Validate rfq_type
    if rfq_data.rfq_type not in ["spare_parts", "subcontractor_service"]:
        raise HTTPException(status_code=400, detail="Invalid RFQ type. Must be 'spare_parts' or 'subcontractor_service'")

    # Validate project/site if provided
    if rfq_data.project_id:
        project = db.query(Project).join(Site).filter(
            Project.id == rfq_data.project_id,
            Site.client.has(company_id=current_user.company_id)
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

    if rfq_data.site_id:
        site = db.query(Site).filter(
            Site.id == rfq_data.site_id,
            Site.client.has(company_id=current_user.company_id)
        ).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

    # Create RFQ
    rfq = RFQ(
        company_id=current_user.company_id,
        rfq_number=generate_rfq_number(db, current_user.company_id),
        rfq_type=rfq_data.rfq_type,
        title=rfq_data.title,
        description=rfq_data.description,
        project_id=rfq_data.project_id,
        site_id=rfq_data.site_id,
        work_order_id=rfq_data.work_order_id,
        required_date=rfq_data.required_date,
        priority=rfq_data.priority,
        currency=rfq_data.currency,
        estimated_budget=rfq_data.estimated_budget,
        notes=rfq_data.notes,
        created_by=current_user.id
    )
    db.add(rfq)
    db.flush()

    # Add items
    if rfq_data.items:
        for item_data in rfq_data.items:
            item = RFQItem(
                rfq_id=rfq.id,
                item_id=item_data.item_id,
                item_number=item_data.item_number,
                description=item_data.description,
                quantity_requested=item_data.quantity_requested,
                unit=item_data.unit,
                estimated_unit_cost=item_data.estimated_unit_cost,
                estimated_total=item_data.estimated_unit_cost * item_data.quantity_requested if item_data.estimated_unit_cost else None,
                service_scope=item_data.service_scope,
                visit_date=item_data.visit_date,
                visit_location=item_data.visit_location,
                notes=item_data.notes
            )
            db.add(item)

    # Add vendors
    if rfq_data.vendors:
        for vendor_data in rfq_data.vendors:
            # Validate vendor exists and is type V (Vendor)
            vendor_ab = db.query(AddressBook).filter(
                AddressBook.id == vendor_data.address_book_id,
                AddressBook.company_id == current_user.company_id,
                AddressBook.search_type == 'V'
            ).first()
            if not vendor_ab:
                continue  # Skip invalid vendors

            vendor = RFQVendor(
                rfq_id=rfq.id,
                address_book_id=vendor_data.address_book_id,
                vendor_notes=vendor_data.vendor_notes
            )
            db.add(vendor)

    # Log creation
    log_rfq_created(db, rfq, current_user.id, request)

    db.commit()
    db.refresh(rfq)

    return serialize_rfq(get_rfq_or_404(db, rfq.id, current_user.company_id))


@router.put("/{rfq_id}")
async def update_rfq(
    rfq_id: int,
    rfq_data: RFQUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update RFQ (only if draft)"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status != "draft":
        raise HTTPException(status_code=400, detail="Can only update RFQ in draft status")

    # Track changes for audit
    changes = []

    # Update fields
    if rfq_data.title is not None and rfq_data.title != rfq.title:
        changes.append(f"title: {rfq.title} → {rfq_data.title}")
        rfq.title = rfq_data.title

    if rfq_data.description is not None:
        rfq.description = rfq_data.description

    if rfq_data.project_id is not None:
        rfq.project_id = rfq_data.project_id

    if rfq_data.site_id is not None:
        rfq.site_id = rfq_data.site_id

    if rfq_data.work_order_id is not None:
        rfq.work_order_id = rfq_data.work_order_id

    if rfq_data.required_date is not None:
        rfq.required_date = rfq_data.required_date

    if rfq_data.priority is not None and rfq_data.priority != rfq.priority:
        changes.append(f"priority: {rfq.priority} → {rfq_data.priority}")
        rfq.priority = rfq_data.priority

    if rfq_data.currency is not None:
        rfq.currency = rfq_data.currency

    if rfq_data.estimated_budget is not None:
        rfq.estimated_budget = rfq_data.estimated_budget

    if rfq_data.notes is not None:
        rfq.notes = rfq_data.notes

    # Log update if changes made
    if changes:
        log_rfq_action(
            db=db,
            rfq_id=rfq.id,
            action="updated",
            user_id=current_user.id,
            category="rfq",
            new_value="; ".join(changes),
            request=request
        )

    db.commit()
    db.refresh(rfq)

    return serialize_rfq(get_rfq_or_404(db, rfq.id, current_user.company_id))


@router.delete("/{rfq_id}")
async def delete_rfq(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete RFQ (soft delete, only if draft)"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status != "draft":
        raise HTTPException(status_code=400, detail="Can only delete RFQ in draft status")

    rfq.deleted_at = datetime.utcnow()
    db.commit()

    return {"message": "RFQ deleted successfully"}


@router.post("/{rfq_id}/submit")
async def submit_rfq(
    rfq_id: int,
    submit_data: RFQSubmit,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Submit RFQ for processing"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    # Validate submission
    is_valid, error = validate_submission(rfq)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Update status
    rfq.status = "submitted"
    rfq.submitted_at = datetime.utcnow()
    rfq.submitted_by = current_user.id

    if submit_data.notes:
        rfq.notes = (rfq.notes or "") + f"\n[Submission note: {submit_data.notes}]"

    # Log submission
    log_rfq_submitted(db, rfq, current_user.id, request)

    db.commit()

    return {"message": "RFQ submitted successfully", "status": "submitted"}


@router.post("/{rfq_id}/cancel")
async def cancel_rfq(
    rfq_id: int,
    cancel_data: RFQCancel,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Cancel RFQ"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status in ["converted_to_pr", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel RFQ in '{rfq.status}' status")

    old_status = rfq.status
    rfq.status = "cancelled"
    rfq.cancelled_at = datetime.utcnow()
    rfq.cancelled_by = current_user.id
    rfq.cancellation_reason = cancel_data.reason

    # Log cancellation
    log_rfq_status_change(
        db=db,
        rfq_id=rfq.id,
        user_id=current_user.id,
        old_status=old_status,
        new_status="cancelled",
        reason=cancel_data.reason,
        request=request
    )

    db.commit()

    return {"message": "RFQ cancelled", "status": "cancelled"}


# =============================================================================
# Item Management
# =============================================================================

@router.post("/{rfq_id}/items")
async def add_item(
    rfq_id: int,
    item_data: RFQItemCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add item to RFQ"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status not in ["draft"]:
        raise HTTPException(status_code=400, detail="Can only add items to draft RFQ")

    item = RFQItem(
        rfq_id=rfq.id,
        item_id=item_data.item_id,
        item_number=item_data.item_number,
        description=item_data.description,
        quantity_requested=item_data.quantity_requested,
        unit=item_data.unit,
        estimated_unit_cost=item_data.estimated_unit_cost,
        estimated_total=item_data.estimated_unit_cost * item_data.quantity_requested if item_data.estimated_unit_cost else None,
        service_scope=item_data.service_scope,
        visit_date=item_data.visit_date,
        visit_location=item_data.visit_location,
        notes=item_data.notes
    )
    db.add(item)

    log_item_added(db, rfq.id, current_user.id, item_data.description, float(item_data.quantity_requested), request)

    db.commit()
    db.refresh(item)

    return serialize_rfq_item(item)


@router.put("/{rfq_id}/items/{item_id}")
async def update_item(
    rfq_id: int,
    item_id: int,
    item_data: RFQItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update RFQ item"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status not in ["draft"]:
        raise HTTPException(status_code=400, detail="Can only update items in draft RFQ")

    item = db.query(RFQItem).filter(RFQItem.id == item_id, RFQItem.rfq_id == rfq_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Update fields
    if item_data.item_id is not None:
        item.item_id = item_data.item_id
    if item_data.item_number is not None:
        item.item_number = item_data.item_number
    if item_data.description is not None:
        item.description = item_data.description
    if item_data.quantity_requested is not None:
        item.quantity_requested = item_data.quantity_requested
    if item_data.unit is not None:
        item.unit = item_data.unit
    if item_data.estimated_unit_cost is not None:
        item.estimated_unit_cost = item_data.estimated_unit_cost
        item.estimated_total = item_data.estimated_unit_cost * float(item.quantity_requested)
    if item_data.service_scope is not None:
        item.service_scope = item_data.service_scope
    if item_data.visit_date is not None:
        item.visit_date = item_data.visit_date
    if item_data.visit_location is not None:
        item.visit_location = item_data.visit_location
    if item_data.notes is not None:
        item.notes = item_data.notes

    db.commit()
    db.refresh(item)

    return serialize_rfq_item(item)


@router.delete("/{rfq_id}/items/{item_id}")
async def delete_item(
    rfq_id: int,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete RFQ item"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status not in ["draft"]:
        raise HTTPException(status_code=400, detail="Can only delete items from draft RFQ")

    item = db.query(RFQItem).filter(RFQItem.id == item_id, RFQItem.rfq_id == rfq_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    log_item_removed(db, rfq.id, current_user.id, item.description, request)

    db.delete(item)
    db.commit()

    return {"message": "Item deleted"}


# =============================================================================
# Vendor Management
# =============================================================================

@router.post("/{rfq_id}/vendors")
async def add_vendor(
    rfq_id: int,
    vendor_data: RFQVendorCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add vendor to RFQ"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status in ["converted_to_pr", "cancelled"]:
        raise HTTPException(status_code=400, detail="Cannot add vendors to this RFQ")

    # Validate vendor
    vendor_ab = db.query(AddressBook).filter(
        AddressBook.id == vendor_data.address_book_id,
        AddressBook.company_id == current_user.company_id,
        AddressBook.search_type == 'V'
    ).first()
    if not vendor_ab:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Check if vendor already added
    existing = db.query(RFQVendor).filter(
        RFQVendor.rfq_id == rfq_id,
        RFQVendor.address_book_id == vendor_data.address_book_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Vendor already added to this RFQ")

    vendor = RFQVendor(
        rfq_id=rfq.id,
        address_book_id=vendor_data.address_book_id,
        vendor_notes=vendor_data.vendor_notes
    )
    db.add(vendor)

    log_vendor_added(db, rfq.id, current_user.id, vendor_ab.display_name, vendor_ab.id, request)

    db.commit()
    db.refresh(vendor)

    return serialize_rfq_vendor(vendor)


@router.delete("/{rfq_id}/vendors/{vendor_id}")
async def remove_vendor(
    rfq_id: int,
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Remove vendor from RFQ"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status in ["converted_to_pr", "cancelled"]:
        raise HTTPException(status_code=400, detail="Cannot remove vendors from this RFQ")

    vendor = db.query(RFQVendor).filter(RFQVendor.id == vendor_id, RFQVendor.rfq_id == rfq_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Check if vendor has quotes
    if vendor.quotes and len(vendor.quotes) > 0:
        raise HTTPException(status_code=400, detail="Cannot remove vendor with existing quotes")

    vendor_name = vendor.address_book.display_name if vendor.address_book else "Unknown"
    log_vendor_removed(db, rfq.id, current_user.id, vendor_name, vendor.address_book_id, request)

    db.delete(vendor)
    db.commit()

    return {"message": "Vendor removed"}


@router.post("/{rfq_id}/vendors/{vendor_id}/contact")
async def mark_vendor_contacted(
    rfq_id: int,
    vendor_id: int,
    contact_data: RFQVendorContact,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Mark vendor as contacted"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    vendor = db.query(RFQVendor).filter(RFQVendor.id == vendor_id, RFQVendor.rfq_id == rfq_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    vendor.is_contacted = True
    vendor.contact_method = contact_data.contact_method
    vendor.contact_date = contact_data.contact_date or datetime.utcnow()
    vendor.contacted_by = current_user.id
    if contact_data.notes:
        vendor.vendor_notes = (vendor.vendor_notes or "") + f"\n[Contact: {contact_data.notes}]"

    vendor_name = vendor.address_book.display_name if vendor.address_book else "Unknown"
    log_vendor_contacted(db, rfq.id, current_user.id, vendor_name, contact_data.contact_method, request)

    # Update RFQ status if this is first vendor contacted
    if rfq.status == "submitted":
        rfq.status = "quote_pending"
        log_rfq_status_change(db, rfq.id, current_user.id, "submitted", "quote_pending", request=request)

    db.commit()

    return {"message": "Vendor marked as contacted"}


# =============================================================================
# Quote Management
# =============================================================================

@router.post("/{rfq_id}/quotes")
async def receive_quote(
    rfq_id: int,
    quote_data: RFQQuoteCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Record received quote from vendor"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    if rfq.status in ["draft", "converted_to_pr", "cancelled"]:
        raise HTTPException(status_code=400, detail="Cannot add quotes to this RFQ")

    # Validate vendor
    vendor = db.query(RFQVendor).filter(
        RFQVendor.id == quote_data.rfq_vendor_id,
        RFQVendor.rfq_id == rfq_id
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found on this RFQ")

    # Create quote
    quote = RFQQuote(
        rfq_id=rfq.id,
        rfq_vendor_id=quote_data.rfq_vendor_id,
        vendor_quote_number=quote_data.vendor_quote_number,
        quote_date=quote_data.quote_date,
        validity_date=quote_data.validity_date,
        subtotal=quote_data.subtotal,
        tax_amount=quote_data.tax_amount,
        quote_total=quote_data.quote_total,
        currency=quote_data.currency,
        delivery_days=quote_data.delivery_days,
        delivery_date=quote_data.delivery_date,
        payment_terms=quote_data.payment_terms,
        warranty_terms=quote_data.warranty_terms,
        notes=quote_data.notes,
        received_by=current_user.id
    )
    db.add(quote)
    db.flush()

    # Add quote lines
    if quote_data.lines:
        for line_data in quote_data.lines:
            line = RFQQuoteLine(
                rfq_quote_id=quote.id,
                rfq_item_id=line_data.rfq_item_id,
                item_description=line_data.item_description,
                quantity_quoted=line_data.quantity_quoted,
                unit=line_data.unit,
                unit_price=line_data.unit_price,
                total_price=line_data.quantity_quoted * line_data.unit_price,
                notes=line_data.notes
            )
            db.add(line)

    vendor_name = vendor.address_book.display_name if vendor.address_book else "Unknown"
    log_quote_received(db, rfq.id, current_user.id, vendor_name, float(quote_data.quote_total), quote.id, request)

    db.commit()
    db.refresh(quote)

    return serialize_rfq_quote(quote)


@router.put("/{rfq_id}/quotes/{quote_id}")
async def update_quote(
    rfq_id: int,
    quote_id: int,
    quote_data: RFQQuoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update quote details"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    quote = db.query(RFQQuote).filter(RFQQuote.id == quote_id, RFQQuote.rfq_id == rfq_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    # Update fields
    if quote_data.vendor_quote_number is not None:
        quote.vendor_quote_number = quote_data.vendor_quote_number
    if quote_data.quote_date is not None:
        quote.quote_date = quote_data.quote_date
    if quote_data.validity_date is not None:
        quote.validity_date = quote_data.validity_date
    if quote_data.subtotal is not None:
        quote.subtotal = quote_data.subtotal
    if quote_data.tax_amount is not None:
        quote.tax_amount = quote_data.tax_amount
    if quote_data.quote_total is not None:
        quote.quote_total = quote_data.quote_total
    if quote_data.currency is not None:
        quote.currency = quote_data.currency
    if quote_data.delivery_days is not None:
        quote.delivery_days = quote_data.delivery_days
    if quote_data.delivery_date is not None:
        quote.delivery_date = quote_data.delivery_date
    if quote_data.payment_terms is not None:
        quote.payment_terms = quote_data.payment_terms
    if quote_data.warranty_terms is not None:
        quote.warranty_terms = quote_data.warranty_terms
    if quote_data.evaluation_score is not None:
        quote.evaluation_score = quote_data.evaluation_score
    if quote_data.evaluation_notes is not None:
        quote.evaluation_notes = quote_data.evaluation_notes
    if quote_data.notes is not None:
        quote.notes = quote_data.notes

    db.commit()
    db.refresh(quote)

    return serialize_rfq_quote(quote)


@router.post("/{rfq_id}/quotes/{quote_id}/evaluate")
async def evaluate_quote(
    rfq_id: int,
    quote_id: int,
    evaluation: RFQQuoteUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add evaluation score to quote"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    quote = db.query(RFQQuote).filter(RFQQuote.id == quote_id, RFQQuote.rfq_id == rfq_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if evaluation.evaluation_score is not None:
        quote.evaluation_score = evaluation.evaluation_score
        quote.status = "under_review"

    if evaluation.evaluation_notes is not None:
        quote.evaluation_notes = evaluation.evaluation_notes

    vendor_name = quote.vendor.address_book.display_name if quote.vendor and quote.vendor.address_book else "Unknown"
    log_quote_evaluated(db, rfq.id, current_user.id, vendor_name, float(evaluation.evaluation_score or 0), quote.id, request)

    db.commit()

    return {"message": "Quote evaluated", "score": quote.evaluation_score}


# =============================================================================
# Comparison
# =============================================================================

@router.get("/{rfq_id}/comparison/matrix")
async def get_comparison_matrix(
    rfq_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get quote comparison matrix"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    # Find best prices
    best_price_quote_id = None
    best_delivery_quote_id = None
    lowest_price = None
    shortest_delivery = None

    for quote in rfq.quotes:
        if quote.status != "rejected":
            if lowest_price is None or float(quote.quote_total) < lowest_price:
                lowest_price = float(quote.quote_total)
                best_price_quote_id = quote.id

            if quote.delivery_days:
                if shortest_delivery is None or quote.delivery_days < shortest_delivery:
                    shortest_delivery = quote.delivery_days
                    best_delivery_quote_id = quote.id

    recommended_quote_id = None
    if rfq.comparison and rfq.comparison.recommended_vendor_id:
        # Find quote from recommended vendor
        for quote in rfq.quotes:
            if quote.rfq_vendor_id == rfq.comparison.recommended_vendor_id:
                recommended_quote_id = quote.id
                break

    return {
        "rfq_id": rfq.id,
        "rfq_number": rfq.rfq_number,
        "items": [serialize_rfq_item(item) for item in rfq.items],
        "vendors": [serialize_rfq_vendor(vendor) for vendor in rfq.vendors],
        "quotes": [serialize_rfq_quote(quote) for quote in rfq.quotes],
        "comparison": serialize_comparison(rfq.comparison) if rfq.comparison else None,
        "best_price_quote_id": best_price_quote_id,
        "best_delivery_quote_id": best_delivery_quote_id,
        "recommended_quote_id": recommended_quote_id
    }


@router.post("/{rfq_id}/comparison/recommend")
async def recommend_vendor(
    rfq_id: int,
    recommendation: RFQComparisonRecommend,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Recommend winning vendor"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    # Validate vendor
    vendor = db.query(RFQVendor).filter(
        RFQVendor.id == recommendation.recommended_vendor_id,
        RFQVendor.rfq_id == rfq_id
    ).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found on this RFQ")

    # Create or update comparison
    if not rfq.comparison:
        comparison = RFQComparison(
            rfq_id=rfq.id,
            comparison_status="complete",
            recommended_vendor_id=recommendation.recommended_vendor_id,
            recommendation_notes=recommendation.recommendation_notes,
            created_by=current_user.id,
            completed_at=datetime.utcnow(),
            completed_by=current_user.id
        )
        db.add(comparison)
    else:
        rfq.comparison.recommended_vendor_id = recommendation.recommended_vendor_id
        rfq.comparison.recommendation_notes = recommendation.recommendation_notes
        rfq.comparison.comparison_status = "complete"
        rfq.comparison.completed_at = datetime.utcnow()
        rfq.comparison.completed_by = current_user.id

    # Update RFQ status
    if rfq.status in ["submitted", "quote_pending"]:
        old_status = rfq.status
        rfq.status = "comparison"
        log_rfq_status_change(db, rfq.id, current_user.id, old_status, "comparison", request=request)

    vendor_name = vendor.address_book.display_name if vendor.address_book else "Unknown"
    log_vendor_selected(db, rfq.id, current_user.id, vendor_name, recommendation.recommendation_notes, request)

    db.commit()

    return {"message": "Vendor recommended", "vendor_name": vendor_name}


# =============================================================================
# PR Conversion
# =============================================================================

@router.post("/{rfq_id}/convert-to-pr", response_model=RFQConvertToPRResponse)
async def convert_to_pr(
    rfq_id: int,
    conversion_data: RFQConvertToPR,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Convert RFQ to Purchase Request"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    # Validate conversion
    is_valid, error = validate_conversion(rfq, conversion_data.selected_quote_id)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Find selected quote
    selected_quote = None
    for quote in rfq.quotes:
        if quote.id == conversion_data.selected_quote_id:
            selected_quote = quote
            break

    if not selected_quote:
        raise HTTPException(status_code=404, detail="Selected quote not found")

    # Convert to PR
    pr = convert_rfq_to_pr(
        db=db,
        rfq=rfq,
        selected_quote=selected_quote,
        user_id=current_user.id,
        additional_notes=conversion_data.additional_notes,
        request=request
    )

    db.commit()

    return {
        "success": True,
        "pr_id": pr.id,
        "pr_number": pr.pr_number,
        "rfq_number": rfq.rfq_number,
        "message": f"RFQ {rfq.rfq_number} converted to PR {pr.pr_number}"
    }


# =============================================================================
# Audit Trail / Timeline
# =============================================================================

@router.get("/{rfq_id}/timeline")
async def get_timeline(
    rfq_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get RFQ timeline / audit trail"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    query = db.query(RFQAuditTrail).filter(RFQAuditTrail.rfq_id == rfq_id)
    total = query.count()

    offset = (page - 1) * size
    entries = query.options(
        joinedload(RFQAuditTrail.user)
    ).order_by(RFQAuditTrail.action_at.desc()).offset(offset).limit(size).all()

    return {
        "entries": [format_timeline_entry(e, e.user) for e in entries],
        "total": total
    }


@router.post("/{rfq_id}/notes")
async def add_note(
    rfq_id: int,
    note_data: RFQAddNote,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Add manual note to RFQ audit trail"""
    rfq = get_rfq_or_404(db, rfq_id, current_user.company_id)

    log_note_added(db, rfq.id, current_user.id, note_data.note, request)

    db.commit()

    return {"message": "Note added"}
