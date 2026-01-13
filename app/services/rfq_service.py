"""
RFQ (Request for Quotation) Service

Provides business logic for RFQ operations including:
- RFQ number generation
- Status transitions
- Audit trail logging
- PR conversion
"""
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from fastapi import Request

from app.models import (
    RFQ, RFQItem, RFQVendor, RFQQuote, RFQQuoteLine,
    RFQAuditTrail, RFQSiteVisit, RFQComparison,
    PurchaseRequest, PurchaseRequestLine, User
)

logger = logging.getLogger(__name__)


# =============================================================================
# RFQ Number Generation
# =============================================================================

def generate_rfq_number(db: Session, company_id: int) -> str:
    """
    Generate unique RFQ number in format: RFQ-YYYY-NNNNN
    Example: RFQ-2026-00001
    """
    year = datetime.now().year

    # Get the last RFQ number for this company and year
    last_rfq = db.query(RFQ).filter(
        RFQ.company_id == company_id,
        RFQ.rfq_number.like(f"RFQ-{year}-%")
    ).order_by(RFQ.id.desc()).first()

    if last_rfq:
        # Extract the sequence number and increment
        try:
            last_seq = int(last_rfq.rfq_number.split('-')[-1])
            new_seq = last_seq + 1
        except (ValueError, IndexError):
            new_seq = 1
    else:
        new_seq = 1

    return f"RFQ-{year}-{new_seq:05d}"


# =============================================================================
# Audit Trail Logging
# =============================================================================

def log_rfq_action(
    db: Session,
    rfq_id: int,
    action: str,
    user_id: int,
    category: str = "rfq",
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """
    Log an action to the RFQ audit trail.

    Args:
        db: Database session
        rfq_id: RFQ ID
        action: Action type (created, submitted, vendor_added, quote_received, etc.)
        user_id: User who performed the action
        category: Action category (rfq, item, vendor, quote, status)
        old_value: Previous value (for updates)
        new_value: New value (for updates)
        details: Additional context as dictionary
        request: FastAPI request for IP/user-agent logging

    Returns:
        Created audit trail entry
    """
    audit = RFQAuditTrail(
        rfq_id=rfq_id,
        action=action,
        action_category=category,
        action_by=user_id,
        old_value=old_value,
        new_value=new_value,
        details=json.dumps(details) if details else None,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None
    )
    db.add(audit)
    # Don't commit - let caller handle transaction
    return audit


def log_rfq_created(
    db: Session,
    rfq: RFQ,
    user_id: int,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log RFQ creation"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq.id,
        action="created",
        user_id=user_id,
        category="rfq",
        new_value=rfq.rfq_number,
        details={
            "rfq_type": rfq.rfq_type,
            "title": rfq.title,
            "project_id": rfq.project_id,
            "site_id": rfq.site_id,
            "priority": rfq.priority
        },
        request=request
    )


def log_rfq_submitted(
    db: Session,
    rfq: RFQ,
    user_id: int,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log RFQ submission"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq.id,
        action="submitted",
        user_id=user_id,
        category="status",
        old_value="draft",
        new_value="submitted",
        details={
            "item_count": len(rfq.items) if rfq.items else 0,
            "vendor_count": len(rfq.vendors) if rfq.vendors else 0
        },
        request=request
    )


def log_rfq_status_change(
    db: Session,
    rfq_id: int,
    user_id: int,
    old_status: str,
    new_status: str,
    reason: Optional[str] = None,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log RFQ status change"""
    details = {"reason": reason} if reason else None
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="status_changed",
        user_id=user_id,
        category="status",
        old_value=old_status,
        new_value=new_status,
        details=details,
        request=request
    )


def log_vendor_added(
    db: Session,
    rfq_id: int,
    user_id: int,
    vendor_name: str,
    vendor_id: int,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log vendor added to RFQ"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="vendor_added",
        user_id=user_id,
        category="vendor",
        new_value=vendor_name,
        details={
            "vendor_id": vendor_id,
            "vendor_name": vendor_name
        },
        request=request
    )


def log_vendor_removed(
    db: Session,
    rfq_id: int,
    user_id: int,
    vendor_name: str,
    vendor_id: int,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log vendor removed from RFQ"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="vendor_removed",
        user_id=user_id,
        category="vendor",
        old_value=vendor_name,
        details={
            "vendor_id": vendor_id,
            "vendor_name": vendor_name
        },
        request=request
    )


def log_vendor_contacted(
    db: Session,
    rfq_id: int,
    user_id: int,
    vendor_name: str,
    contact_method: str,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log vendor contacted for quote"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="vendor_contacted",
        user_id=user_id,
        category="vendor",
        new_value=f"{vendor_name} via {contact_method}",
        details={
            "vendor_name": vendor_name,
            "contact_method": contact_method
        },
        request=request
    )


def log_quote_received(
    db: Session,
    rfq_id: int,
    user_id: int,
    vendor_name: str,
    quote_total: float,
    quote_id: int,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log quote received from vendor"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="quote_received",
        user_id=user_id,
        category="quote",
        new_value=f"${quote_total:,.2f}",
        details={
            "vendor_name": vendor_name,
            "quote_id": quote_id,
            "quote_total": str(quote_total)
        },
        request=request
    )


def log_quote_evaluated(
    db: Session,
    rfq_id: int,
    user_id: int,
    vendor_name: str,
    score: float,
    quote_id: int,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log quote evaluation"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="quote_evaluated",
        user_id=user_id,
        category="quote",
        new_value=f"{score}/100",
        details={
            "vendor_name": vendor_name,
            "quote_id": quote_id,
            "evaluation_score": str(score)
        },
        request=request
    )


def log_vendor_selected(
    db: Session,
    rfq_id: int,
    user_id: int,
    vendor_name: str,
    selection_reason: Optional[str] = None,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log vendor selected as winner"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="vendor_selected",
        user_id=user_id,
        category="vendor",
        new_value=vendor_name,
        details={
            "vendor_name": vendor_name,
            "selection_reason": selection_reason
        },
        request=request
    )


def log_converted_to_pr(
    db: Session,
    rfq_id: int,
    user_id: int,
    pr_id: int,
    pr_number: str,
    vendor_name: str,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log RFQ conversion to PR"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="converted_to_pr",
        user_id=user_id,
        category="rfq",
        new_value=pr_number,
        details={
            "pr_id": pr_id,
            "pr_number": pr_number,
            "vendor_name": vendor_name
        },
        request=request
    )


def log_item_added(
    db: Session,
    rfq_id: int,
    user_id: int,
    item_description: str,
    quantity: float,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log item added to RFQ"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="item_added",
        user_id=user_id,
        category="item",
        new_value=f"{item_description} (qty: {quantity})",
        details={
            "description": item_description,
            "quantity": str(quantity)
        },
        request=request
    )


def log_item_removed(
    db: Session,
    rfq_id: int,
    user_id: int,
    item_description: str,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log item removed from RFQ"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="item_removed",
        user_id=user_id,
        category="item",
        old_value=item_description,
        request=request
    )


def log_note_added(
    db: Session,
    rfq_id: int,
    user_id: int,
    note: str,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log manual note added"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="note_added",
        user_id=user_id,
        category="rfq",
        new_value=note[:100] + "..." if len(note) > 100 else note,
        details={"full_note": note},
        request=request
    )


def log_document_uploaded(
    db: Session,
    rfq_id: int,
    user_id: int,
    document_type: str,
    title: str,
    request: Optional[Request] = None
) -> RFQAuditTrail:
    """Log document uploaded"""
    return log_rfq_action(
        db=db,
        rfq_id=rfq_id,
        action="document_uploaded",
        user_id=user_id,
        category="rfq",
        new_value=title or document_type,
        details={
            "document_type": document_type,
            "title": title
        },
        request=request
    )


# =============================================================================
# Status Transition Validation
# =============================================================================

# Valid status transitions
RFQ_STATUS_TRANSITIONS = {
    "draft": ["submitted", "cancelled"],
    "submitted": ["quote_pending", "cancelled"],
    "quote_pending": ["comparison", "cancelled"],
    "comparison": ["converted_to_pr", "quote_pending", "cancelled"],
    "converted_to_pr": [],  # Terminal state
    "cancelled": []  # Terminal state
}


def can_transition_status(current_status: str, new_status: str) -> bool:
    """Check if status transition is valid"""
    valid_transitions = RFQ_STATUS_TRANSITIONS.get(current_status, [])
    return new_status in valid_transitions


def validate_submission(rfq: RFQ) -> tuple[bool, str]:
    """
    Validate RFQ can be submitted.
    Returns (is_valid, error_message)
    """
    if rfq.status != "draft":
        return False, f"Cannot submit RFQ in '{rfq.status}' status"

    if not rfq.items or len(rfq.items) == 0:
        return False, "RFQ must have at least one item"

    if not rfq.vendors or len(rfq.vendors) == 0:
        return False, "RFQ must have at least one vendor"

    return True, ""


def validate_comparison(rfq: RFQ) -> tuple[bool, str]:
    """
    Validate RFQ can proceed to comparison.
    Returns (is_valid, error_message)
    """
    if rfq.status not in ["submitted", "quote_pending"]:
        return False, f"Cannot proceed to comparison from '{rfq.status}' status"

    received_quotes = [q for q in rfq.quotes if q.status in ["received", "under_review"]]
    if len(received_quotes) < 2:
        return False, "At least 2 quotes required for comparison"

    return True, ""


def validate_conversion(rfq: RFQ, selected_quote_id: int) -> tuple[bool, str]:
    """
    Validate RFQ can be converted to PR.
    Returns (is_valid, error_message)
    """
    if rfq.status not in ["comparison", "quote_pending"]:
        return False, f"Cannot convert to PR from '{rfq.status}' status"

    # Find selected quote
    selected_quote = None
    for quote in rfq.quotes:
        if quote.id == selected_quote_id:
            selected_quote = quote
            break

    if not selected_quote:
        return False, "Selected quote not found"

    if selected_quote.status == "rejected":
        return False, "Cannot convert rejected quote to PR"

    return True, ""


# =============================================================================
# PR Conversion
# =============================================================================

def convert_rfq_to_pr(
    db: Session,
    rfq: RFQ,
    selected_quote: RFQQuote,
    user_id: int,
    additional_notes: Optional[str] = None,
    request: Optional[Request] = None
) -> PurchaseRequest:
    """
    Convert RFQ with selected quote to Purchase Request.

    Args:
        db: Database session
        rfq: RFQ to convert
        selected_quote: Selected vendor quote
        user_id: User performing conversion
        additional_notes: Additional notes for PR
        request: FastAPI request for audit logging

    Returns:
        Created PurchaseRequest
    """
    from app.api.purchase_requests import generate_pr_number

    # Create PR
    pr = PurchaseRequest(
        company_id=rfq.company_id,
        pr_number=generate_pr_number(db, rfq.company_id),
        status="draft",
        work_order_id=rfq.work_order_id,
        rfq_id=rfq.id,
        address_book_id=selected_quote.vendor.address_book_id,
        title=rfq.title,
        description=rfq.description,
        required_date=rfq.required_date,
        priority=rfq.priority,
        currency=rfq.currency,
        created_by=user_id,
        notes=f"Converted from {rfq.rfq_number}" + (f"\n{additional_notes}" if additional_notes else "")
    )
    db.add(pr)
    db.flush()  # Get PR ID

    # Create PR lines from quote lines
    total = 0
    for quote_line in selected_quote.lines:
        pr_line = PurchaseRequestLine(
            purchase_request_id=pr.id,
            item_id=quote_line.rfq_item.item_id if quote_line.rfq_item else None,
            item_number=quote_line.rfq_item.item_number if quote_line.rfq_item else None,
            description=quote_line.item_description,
            quantity_requested=float(quote_line.quantity_quoted),
            unit=quote_line.unit,
            estimated_unit_cost=float(quote_line.unit_price),
            estimated_total=float(quote_line.total_price)
        )
        db.add(pr_line)
        total += float(quote_line.total_price)

    # Update PR total
    pr.estimated_total = total

    # Update RFQ status
    old_status = rfq.status
    rfq.status = "converted_to_pr"
    rfq.converted_to_pr_at = datetime.utcnow()
    rfq.converted_by = user_id

    # Mark vendor as selected
    selected_quote.vendor.is_selected = True
    selected_quote.status = "selected"

    # Log conversion
    vendor_name = selected_quote.vendor.address_book.display_name if selected_quote.vendor.address_book else "Unknown"
    log_converted_to_pr(
        db=db,
        rfq_id=rfq.id,
        user_id=user_id,
        pr_id=pr.id,
        pr_number=pr.pr_number,
        vendor_name=vendor_name,
        request=request
    )

    log_rfq_status_change(
        db=db,
        rfq_id=rfq.id,
        user_id=user_id,
        old_status=old_status,
        new_status="converted_to_pr",
        reason=f"Converted to PR {pr.pr_number}",
        request=request
    )

    return pr


# =============================================================================
# Timeline Formatting
# =============================================================================

def format_timeline_entry(entry: RFQAuditTrail, user: Optional[User] = None) -> dict:
    """Format audit trail entry for timeline display"""
    action_descriptions = {
        "created": "RFQ Created",
        "submitted": "RFQ Submitted",
        "status_changed": "Status Changed",
        "vendor_added": "Vendor Added",
        "vendor_removed": "Vendor Removed",
        "vendor_contacted": "Vendor Contacted",
        "quote_received": "Quote Received",
        "quote_evaluated": "Quote Evaluated",
        "vendor_selected": "Vendor Selected",
        "converted_to_pr": "Converted to PR",
        "item_added": "Item Added",
        "item_removed": "Item Removed",
        "note_added": "Note Added",
        "document_uploaded": "Document Uploaded",
        "cancelled": "RFQ Cancelled"
    }

    details = json.loads(entry.details) if entry.details else {}

    return {
        "id": entry.id,
        "action": entry.action,
        "action_title": action_descriptions.get(entry.action, entry.action.replace("_", " ").title()),
        "action_category": entry.action_category,
        "action_by": entry.action_by,
        "action_by_name": user.name if user else None,
        "action_at": entry.action_at.isoformat() if entry.action_at else None,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "details": details
    }
