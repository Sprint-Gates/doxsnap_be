from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from app.database import get_db
from app.models import ConditionReport, ConditionReportImage, User, Client, Site, Building, Floor, Space
from app.api.auth import get_current_user
from app.config import settings
from jose import jwt
import os
import uuid
import logging

logger = logging.getLogger(__name__)


def verify_token_payload(token: str) -> Optional[dict]:
    """Verify token and return full payload"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except:
        return None

router = APIRouter()

# Upload directory for condition report images
CONDITION_REPORT_IMAGES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads", "condition_report_images"
)

# Ensure upload directory exists
os.makedirs(CONDITION_REPORT_IMAGES_DIR, exist_ok=True)

# Valid issue classes
VALID_ISSUE_CLASSES = ["civil", "mechanical", "electrical", "others"]
VALID_STATUSES = ["submitted", "under_review", "approved", "rejected", "resolved"]
VALID_PRIORITIES = ["low", "medium", "high", "critical"]


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ConditionReportCreate(BaseModel):
    client_id: int
    title: str
    description: str
    issue_class: str
    estimated_cost: Optional[float] = None
    currency: Optional[str] = "USD"
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    space_id: Optional[int] = None
    location_notes: Optional[str] = None
    priority: Optional[str] = "medium"


class ConditionReportUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    issue_class: Optional[str] = None
    estimated_cost: Optional[float] = None
    currency: Optional[str] = None
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    space_id: Optional[int] = None
    location_notes: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    review_notes: Optional[str] = None


class ConditionReportImageResponse(BaseModel):
    id: int
    condition_report_id: int
    filename: str
    original_filename: str
    file_path: str
    file_size: Optional[int]
    mime_type: Optional[str]
    caption: Optional[str]
    sort_order: int
    uploaded_by: Optional[int]
    uploaded_by_name: Optional[str]
    uploaded_at: Optional[str]

    class Config:
        from_attributes = True


class ConditionReportResponse(BaseModel):
    id: int
    company_id: int
    client_id: int
    client_name: Optional[str]
    report_number: Optional[str]
    title: str
    description: str
    issue_class: str
    estimated_cost: Optional[float]
    currency: str
    site_id: Optional[int]
    site_name: Optional[str]
    building_id: Optional[int]
    building_name: Optional[str]
    floor_id: Optional[int]
    floor_name: Optional[str]
    space_id: Optional[int]
    space_name: Optional[str]
    location_notes: Optional[str]
    status: str
    priority: str
    collected_by: int
    collected_by_name: Optional[str]
    collected_at: Optional[str]
    reviewed_by: Optional[int]
    reviewed_by_name: Optional[str]
    reviewed_at: Optional[str]
    review_notes: Optional[str]
    images: List[ConditionReportImageResponse]
    image_count: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ============================================================================
# Helper Functions
# ============================================================================

def generate_report_number(db: Session, company_id: int) -> str:
    """Generate unique report number: CR-YYYYMMDD-XXX"""
    today = datetime.now()
    date_str = today.strftime("%Y%m%d")
    prefix = f"CR-{date_str}-"

    # Get count of reports today for this company
    count = db.query(ConditionReport).filter(
        ConditionReport.company_id == company_id,
        ConditionReport.report_number.like(f"{prefix}%")
    ).count()

    return f"{prefix}{str(count + 1).zfill(3)}"


def image_to_response(image: ConditionReportImage) -> ConditionReportImageResponse:
    """Convert ConditionReportImage to response"""
    return ConditionReportImageResponse(
        id=image.id,
        condition_report_id=image.condition_report_id,
        filename=image.filename,
        original_filename=image.original_filename,
        file_path=image.file_path,
        file_size=image.file_size,
        mime_type=image.mime_type,
        caption=image.caption,
        sort_order=image.sort_order,
        uploaded_by=image.uploaded_by,
        uploaded_by_name=image.uploader.name if image.uploader else None,
        uploaded_at=image.uploaded_at.isoformat() if image.uploaded_at else None
    )


def report_to_response(report: ConditionReport) -> ConditionReportResponse:
    """Convert ConditionReport to response"""
    return ConditionReportResponse(
        id=report.id,
        company_id=report.company_id,
        client_id=report.client_id,
        client_name=report.client.name if report.client else None,
        report_number=report.report_number,
        title=report.title,
        description=report.description,
        issue_class=report.issue_class,
        estimated_cost=float(report.estimated_cost) if report.estimated_cost else None,
        currency=report.currency or "USD",
        site_id=report.site_id,
        site_name=report.site.name if report.site else None,
        building_id=report.building_id,
        building_name=report.building.name if report.building else None,
        floor_id=report.floor_id,
        floor_name=report.floor.name if report.floor else None,
        space_id=report.space_id,
        space_name=report.space.name if report.space else None,
        location_notes=report.location_notes,
        status=report.status,
        priority=report.priority,
        collected_by=report.collected_by,
        collected_by_name=report.collector.name if report.collector else None,
        collected_at=report.collected_at.isoformat() if report.collected_at else None,
        reviewed_by=report.reviewed_by,
        reviewed_by_name=report.reviewer.name if report.reviewer else None,
        reviewed_at=report.reviewed_at.isoformat() if report.reviewed_at else None,
        review_notes=report.review_notes,
        images=[image_to_response(img) for img in report.images] if report.images else [],
        image_count=len(report.images) if report.images else 0,
        created_at=report.created_at.isoformat() if report.created_at else "",
        updated_at=report.updated_at.isoformat() if report.updated_at else ""
    )


# ============================================================================
# Condition Report CRUD Endpoints
# ============================================================================

@router.get("/", response_model=List[ConditionReportResponse])
async def get_condition_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_id: Optional[int] = Query(None, description="Filter by client"),
    site_id: Optional[int] = Query(None, description="Filter by site"),
    issue_class: Optional[str] = Query(None, description="Filter by issue class"),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    search: Optional[str] = Query(None, description="Search by title or description")
):
    """Get all condition reports with optional filtering"""
    query = db.query(ConditionReport).options(
        joinedload(ConditionReport.client),
        joinedload(ConditionReport.site),
        joinedload(ConditionReport.building),
        joinedload(ConditionReport.floor),
        joinedload(ConditionReport.space),
        joinedload(ConditionReport.collector),
        joinedload(ConditionReport.reviewer),
        joinedload(ConditionReport.images).joinedload(ConditionReportImage.uploader)
    ).filter(ConditionReport.company_id == current_user.company_id)

    if client_id:
        query = query.filter(ConditionReport.client_id == client_id)

    if site_id:
        query = query.filter(ConditionReport.site_id == site_id)

    if issue_class and issue_class in VALID_ISSUE_CLASSES:
        query = query.filter(ConditionReport.issue_class == issue_class)

    if status and status in VALID_STATUSES:
        query = query.filter(ConditionReport.status == status)

    if priority and priority in VALID_PRIORITIES:
        query = query.filter(ConditionReport.priority == priority)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                ConditionReport.title.ilike(search_term),
                ConditionReport.description.ilike(search_term),
                ConditionReport.report_number.ilike(search_term)
            )
        )

    reports = query.order_by(ConditionReport.created_at.desc()).all()

    return [report_to_response(r) for r in reports]


@router.get("/stats/summary")
async def get_condition_reports_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client_id: Optional[int] = Query(None, description="Filter by client")
):
    """Get summary statistics for condition reports"""
    base_query = db.query(ConditionReport).filter(
        ConditionReport.company_id == current_user.company_id
    )

    if client_id:
        base_query = base_query.filter(ConditionReport.client_id == client_id)

    # Count by status
    status_counts = {}
    for s in VALID_STATUSES:
        status_counts[s] = base_query.filter(ConditionReport.status == s).count()

    # Count by issue class
    class_counts = {}
    for c in VALID_ISSUE_CLASSES:
        class_counts[c] = base_query.filter(ConditionReport.issue_class == c).count()

    # Count by priority
    priority_counts = {}
    for p in VALID_PRIORITIES:
        priority_counts[p] = base_query.filter(ConditionReport.priority == p).count()

    # Total estimated cost
    total_cost = base_query.with_entities(
        func.sum(ConditionReport.estimated_cost)
    ).scalar() or 0

    return {
        "total": base_query.count(),
        "by_status": status_counts,
        "by_class": class_counts,
        "by_priority": priority_counts,
        "total_estimated_cost": float(total_cost)
    }


@router.get("/{report_id}", response_model=ConditionReportResponse)
async def get_condition_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific condition report by ID"""
    report = db.query(ConditionReport).options(
        joinedload(ConditionReport.client),
        joinedload(ConditionReport.site),
        joinedload(ConditionReport.building),
        joinedload(ConditionReport.floor),
        joinedload(ConditionReport.space),
        joinedload(ConditionReport.collector),
        joinedload(ConditionReport.reviewer),
        joinedload(ConditionReport.images).joinedload(ConditionReportImage.uploader)
    ).filter(
        ConditionReport.id == report_id,
        ConditionReport.company_id == current_user.company_id
    ).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition report not found"
        )

    return report_to_response(report)


@router.post("/", response_model=ConditionReportResponse, status_code=status.HTTP_201_CREATED)
async def create_condition_report(
    report_data: ConditionReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new condition report"""
    # Validate issue class
    if report_data.issue_class not in VALID_ISSUE_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid issue class. Must be one of: {', '.join(VALID_ISSUE_CLASSES)}"
        )

    # Validate priority if provided
    if report_data.priority and report_data.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority. Must be one of: {', '.join(VALID_PRIORITIES)}"
        )

    # Verify client exists and belongs to company
    client = db.query(Client).filter(
        Client.id == report_data.client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )

    # Verify site if provided
    if report_data.site_id:
        site = db.query(Site).filter(
            Site.id == report_data.site_id,
            Site.company_id == current_user.company_id
        ).first()
        if not site:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site not found"
            )

    # Generate report number
    report_number = generate_report_number(db, current_user.company_id)

    # Create condition report
    report = ConditionReport(
        company_id=current_user.company_id,
        client_id=report_data.client_id,
        report_number=report_number,
        title=report_data.title,
        description=report_data.description,
        issue_class=report_data.issue_class,
        estimated_cost=Decimal(str(report_data.estimated_cost)) if report_data.estimated_cost else None,
        currency=report_data.currency or "USD",
        site_id=report_data.site_id,
        building_id=report_data.building_id,
        floor_id=report_data.floor_id,
        space_id=report_data.space_id,
        location_notes=report_data.location_notes,
        priority=report_data.priority or "medium",
        status="submitted",
        collected_by=current_user.id
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    # Reload with relationships
    report = db.query(ConditionReport).options(
        joinedload(ConditionReport.client),
        joinedload(ConditionReport.site),
        joinedload(ConditionReport.building),
        joinedload(ConditionReport.floor),
        joinedload(ConditionReport.space),
        joinedload(ConditionReport.collector),
        joinedload(ConditionReport.reviewer),
        joinedload(ConditionReport.images)
    ).filter(ConditionReport.id == report.id).first()

    return report_to_response(report)


@router.put("/{report_id}", response_model=ConditionReportResponse)
async def update_condition_report(
    report_id: int,
    report_data: ConditionReportUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a condition report"""
    report = db.query(ConditionReport).filter(
        ConditionReport.id == report_id,
        ConditionReport.company_id == current_user.company_id
    ).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition report not found"
        )

    # Validate issue class if provided
    if report_data.issue_class and report_data.issue_class not in VALID_ISSUE_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid issue class. Must be one of: {', '.join(VALID_ISSUE_CLASSES)}"
        )

    # Validate status if provided
    if report_data.status and report_data.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    # Validate priority if provided
    if report_data.priority and report_data.priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority. Must be one of: {', '.join(VALID_PRIORITIES)}"
        )

    # Update fields
    update_data = report_data.model_dump(exclude_unset=True)

    # Handle estimated_cost conversion
    if "estimated_cost" in update_data and update_data["estimated_cost"] is not None:
        update_data["estimated_cost"] = Decimal(str(update_data["estimated_cost"]))

    # Track if status changed to reviewed
    if "status" in update_data and update_data["status"] in ["approved", "rejected", "under_review"]:
        if report.reviewed_by is None:
            update_data["reviewed_by"] = current_user.id
            update_data["reviewed_at"] = datetime.now()

    for field, value in update_data.items():
        setattr(report, field, value)

    db.commit()
    db.refresh(report)

    # Reload with relationships
    report = db.query(ConditionReport).options(
        joinedload(ConditionReport.client),
        joinedload(ConditionReport.site),
        joinedload(ConditionReport.building),
        joinedload(ConditionReport.floor),
        joinedload(ConditionReport.space),
        joinedload(ConditionReport.collector),
        joinedload(ConditionReport.reviewer),
        joinedload(ConditionReport.images).joinedload(ConditionReportImage.uploader)
    ).filter(ConditionReport.id == report.id).first()

    return report_to_response(report)


@router.delete("/{report_id}")
async def delete_condition_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a condition report and its images"""
    report = db.query(ConditionReport).options(
        joinedload(ConditionReport.images)
    ).filter(
        ConditionReport.id == report_id,
        ConditionReport.company_id == current_user.company_id
    ).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition report not found"
        )

    # Delete image files
    for image in report.images:
        if os.path.exists(image.file_path):
            try:
                os.remove(image.file_path)
            except Exception as e:
                logger.warning(f"Failed to delete image file: {e}")

    # Delete report (cascade will delete images records)
    db.delete(report)
    db.commit()

    return {"success": True, "message": "Condition report deleted"}


# ============================================================================
# Condition Report Image Endpoints
# ============================================================================

@router.get("/{report_id}/images")
async def get_condition_report_images(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all images for a condition report"""
    # Verify report exists and belongs to user's company
    report = db.query(ConditionReport).filter(
        ConditionReport.id == report_id,
        ConditionReport.company_id == current_user.company_id
    ).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition report not found"
        )

    images = db.query(ConditionReportImage).options(
        joinedload(ConditionReportImage.uploader)
    ).filter(
        ConditionReportImage.condition_report_id == report_id
    ).order_by(ConditionReportImage.sort_order, ConditionReportImage.uploaded_at).all()

    return [image_to_response(img) for img in images]


@router.post("/{report_id}/images")
async def upload_condition_report_image(
    report_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload an image to a condition report"""
    # Verify report exists and belongs to user's company
    report = db.query(ConditionReport).filter(
        ConditionReport.id == report_id,
        ConditionReport.company_id == current_user.company_id
    ).first()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Condition report not found"
        )

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}"
        )

    # Generate unique filename
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(CONDITION_REPORT_IMAGES_DIR, unique_filename)

    try:
        # Save file
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        file_size = os.path.getsize(file_path)

        # Get next sort order
        max_sort = db.query(func.max(ConditionReportImage.sort_order)).filter(
            ConditionReportImage.condition_report_id == report_id
        ).scalar() or 0

        # Create image record
        image = ConditionReportImage(
            condition_report_id=report_id,
            company_id=current_user.company_id,
            filename=unique_filename,
            original_filename=file.filename or "image.jpg",
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            caption=caption,
            sort_order=max_sort + 1,
            uploaded_by=current_user.id
        )
        db.add(image)
        db.commit()
        db.refresh(image)

        # Reload with relationships
        image = db.query(ConditionReportImage).options(
            joinedload(ConditionReportImage.uploader)
        ).filter(ConditionReportImage.id == image.id).first()

        return image_to_response(image)

    except Exception as e:
        # Clean up file if database operation fails
        if os.path.exists(file_path):
            os.remove(file_path)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload image: {str(e)}"
        )


@router.get("/{report_id}/images/{image_id}/file")
async def get_condition_report_image_file(
    report_id: int,
    image_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """Get condition report image file (requires token in query param for img src)"""
    # Verify token
    payload = verify_token_payload(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    company_id = payload.get("company_id")
    if not company_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    # Get image
    image = db.query(ConditionReportImage).filter(
        ConditionReportImage.id == image_id,
        ConditionReportImage.condition_report_id == report_id,
        ConditionReportImage.company_id == company_id
    ).first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    if not os.path.exists(image.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image file not found"
        )

    return FileResponse(
        image.file_path,
        media_type=image.mime_type or "image/jpeg",
        filename=image.original_filename
    )


@router.patch("/{report_id}/images/{image_id}")
async def update_condition_report_image(
    report_id: int,
    image_id: int,
    caption: Optional[str] = None,
    sort_order: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update image caption or sort order"""
    image = db.query(ConditionReportImage).filter(
        ConditionReportImage.id == image_id,
        ConditionReportImage.condition_report_id == report_id,
        ConditionReportImage.company_id == current_user.company_id
    ).first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    if caption is not None:
        image.caption = caption
    if sort_order is not None:
        image.sort_order = sort_order

    db.commit()
    db.refresh(image)

    # Reload with relationships
    image = db.query(ConditionReportImage).options(
        joinedload(ConditionReportImage.uploader)
    ).filter(ConditionReportImage.id == image.id).first()

    return image_to_response(image)


@router.delete("/{report_id}/images/{image_id}")
async def delete_condition_report_image(
    report_id: int,
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an image from a condition report"""
    image = db.query(ConditionReportImage).filter(
        ConditionReportImage.id == image_id,
        ConditionReportImage.condition_report_id == report_id,
        ConditionReportImage.company_id == current_user.company_id
    ).first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    # Delete file
    if os.path.exists(image.file_path):
        try:
            os.remove(image.file_path)
        except Exception as e:
            logger.warning(f"Failed to delete image file: {e}")

    # Delete record
    db.delete(image)
    db.commit()

    return {"success": True, "message": "Image deleted"}


