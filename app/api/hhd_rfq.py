"""
HHD (Handheld Device) RFQ API - Mobile endpoints for parts requests

Provides endpoints for mobile technicians to:
- Create parts requests (RFQs)
- View their submitted requests
- Upload images for RFQs
- Search item catalog
"""
import uuid
import os
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from pydantic import BaseModel
from jose import jwt, JWTError

from app.database import get_db
from app.config import settings
from app.models import (
    HandHeldDevice, ItemMaster, RFQ, RFQItem, RFQDocument, ProcessedImage, AddressBook
)
from app.services.rfq_service import generate_rfq_number, log_rfq_created
from app.services.s3 import upload_to_s3

router = APIRouter()


# =============================================================================
# HHD Authentication Helper (same approach as hhd_auth.py)
# =============================================================================

class HHDContext:
    """Context object for HHD authentication"""
    def __init__(self, device: HandHeldDevice, technician_id: Optional[int] = None, employee_id: Optional[int] = None):
        self.device = device
        self.company_id = device.company_id
        self.id = employee_id or technician_id  # For created_by fields
        self.technician_id = technician_id
        self.employee_id = employee_id
        self.email = f"hhd:{device.device_code}"
        self.name = device.device_name
        self.role = "technician"


def get_hhd_auth(request: Request, db: Session = Depends(get_db)) -> HHDContext:
    """
    Extract and validate HHD token from request.
    Uses the same approach as hhd_auth.py for consistency.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}"
        )

    # Check if this is an HHD token
    token_type = payload.get("type")
    sub = payload.get("sub", "")

    if token_type != "hhd" and not sub.startswith("hhd:"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This endpoint requires HHD authentication"
        )

    # Get device_id from payload
    device_id = payload.get("device_id")
    if not device_id and sub.startswith("hhd:"):
        try:
            device_id = int(sub.split(":")[1])
        except (ValueError, IndexError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HHD token format"
            )

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing device_id in token"
        )

    # Verify device exists and is active
    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.is_active == True
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device not found or inactive"
        )

    technician_id = payload.get("technician_id")
    employee_id = payload.get("employee_id")

    return HHDContext(device, technician_id, employee_id)


# =============================================================================
# Pydantic Schemas for Mobile RFQ
# =============================================================================

class MobileRFQItemCreate(BaseModel):
    """Item for mobile RFQ creation"""
    item_id: Optional[int] = None  # If from catalog
    item_number: Optional[str] = None
    description: str
    quantity_requested: float
    unit: Optional[str] = "EA"
    notes: Optional[str] = None


class MobileRFQCreate(BaseModel):
    """Create RFQ from mobile"""
    title: str
    description: Optional[str] = None
    work_order_id: Optional[int] = None
    priority: Optional[str] = "normal"
    items: List[MobileRFQItemCreate]
    image_ids: Optional[List[int]] = None


class MobileRFQListItem(BaseModel):
    """RFQ item for list view"""
    id: int
    rfq_number: str
    title: str
    status: str
    priority: str
    item_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class MobileRFQDetail(BaseModel):
    """Detailed RFQ for mobile view"""
    id: int
    rfq_number: str
    title: str
    description: Optional[str]
    status: str
    priority: str
    work_order_id: Optional[int]
    work_order_number: Optional[str]
    created_at: datetime
    submitted_at: Optional[datetime]
    items: List[dict]
    images: List[dict]

    class Config:
        from_attributes = True


class ItemSearchResult(BaseModel):
    """Item search result for mobile"""
    id: int
    item_number: str
    description: str
    unit: str




# =============================================================================
# Item Search Endpoint
# =============================================================================

@router.get("/items/search")
async def search_items(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    hhd: HHDContext = Depends(get_hhd_auth)
):
    """
    Search item catalog for mobile app.
    Returns items matching the search query by item number or description.
    """
    search_term = f"%{q}%"

    items = db.query(ItemMaster).filter(
        ItemMaster.company_id == hhd.company_id,
        ItemMaster.is_active == True,
        or_(
            ItemMaster.item_number.ilike(search_term),
            ItemMaster.description.ilike(search_term),
            ItemMaster.search_text.ilike(search_term)
        )
    ).order_by(ItemMaster.item_number).limit(limit).all()

    return [
        {
            "id": item.id,
            "item_number": item.item_number,
            "description": item.description,
            "unit": item.unit or "EA"
        }
        for item in items
    ]


# =============================================================================
# Image Upload Endpoint
# =============================================================================

@router.post("/uploads/rfq-image")
async def upload_rfq_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    hhd: HHDContext = Depends(get_hhd_auth)
):
    """
    Upload an image for RFQ from mobile.
    Returns the image ID and URL for use when creating the RFQ.
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="File must be an image"
        )

    # Validate file size (max 10MB)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Image must be less than 10MB"
        )

    # Generate unique filename
    file_extension = file.filename.split(".")[-1] if file.filename and "." in file.filename else "jpg"
    unique_filename = f"rfq_{uuid.uuid4()}.{file_extension}"

    # Save file temporarily
    temp_dir = "uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, unique_filename)

    with open(temp_file_path, "wb") as buffer:
        buffer.write(content)

    try:
        # Try to upload to S3
        try:
            s3_key, s3_url = upload_to_s3(temp_file_path, unique_filename)
            processing_status = "completed"
            # Clean up temp file after S3 upload
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        except Exception as s3_error:
            print(f"S3 upload failed, using local storage: {s3_error}")
            s3_key = f"local/{unique_filename}"
            s3_url = f"local/{unique_filename}"
            processing_status = "completed_local"

        # Create ProcessedImage record to store the image
        db_image = ProcessedImage(
            user_id=hhd.id,  # Can be technician_id or user_id
            original_filename=file.filename,
            s3_key=s3_key,
            s3_url=s3_url,
            processing_status=processing_status,
            document_type="rfq_attachment",
            has_structured_data=False,
            processing_method="upload"
        )
        db.add(db_image)
        db.commit()
        db.refresh(db_image)

        # Generate URL for the uploaded image
        if s3_key.startswith("local/"):
            url = f"/uploads/{unique_filename}"
        else:
            from app.services.s3 import generate_presigned_url
            url = generate_presigned_url(s3_key, expiration=3600) or f"/uploads/{unique_filename}"

        return {
            "id": db_image.id,
            "url": url
        }

    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(
            status_code=500,
            detail=f"Error uploading image: {str(e)}"
        )


# =============================================================================
# RFQ List Endpoint
# =============================================================================

@router.get("/rfqs")
async def list_my_rfqs(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    hhd: HHDContext = Depends(get_hhd_auth)
):
    """
    List RFQs created by the current HHD/technician.
    Filters by status if provided.
    """
    query = db.query(RFQ).filter(
        RFQ.company_id == hhd.company_id,
        RFQ.deleted_at.is_(None)
    )

    # If HHD has a technician_id, filter by created_by
    # Otherwise show all company RFQs for admin users
    if isinstance(hhd, HHDContext) and hhd.id:
        # For mobile, show RFQs where items came from this technician
        # or created by this user
        query = query.filter(RFQ.created_by == hhd.id)

    # Apply status filter
    if status:
        query = query.filter(RFQ.status == status)

    # Get total count
    total = query.count()

    # Pagination
    offset = (page - 1) * size
    rfqs = query.options(
        joinedload(RFQ.items),
        joinedload(RFQ.work_order)
    ).order_by(RFQ.created_at.desc()).offset(offset).limit(size).all()

    # Serialize
    rfq_list = []
    for rfq in rfqs:
        rfq_list.append({
            "id": rfq.id,
            "rfq_number": rfq.rfq_number,
            "title": rfq.title,
            "status": rfq.status,
            "priority": rfq.priority,
            "item_count": len(rfq.items) if rfq.items else 0,
            "work_order_number": rfq.work_order.wo_number if rfq.work_order else None,
            "created_at": rfq.created_at.isoformat(),
            "submitted_at": rfq.submitted_at.isoformat() if rfq.submitted_at else None
        })

    return {
        "rfqs": rfq_list,
        "total": total,
        "page": page,
        "size": size
    }


# =============================================================================
# RFQ Detail Endpoint
# =============================================================================

@router.get("/rfqs/{rfq_id}")
async def get_rfq_detail(
    rfq_id: int,
    db: Session = Depends(get_db),
    hhd: HHDContext = Depends(get_hhd_auth)
):
    """
    Get detailed view of an RFQ for mobile.
    """
    rfq = db.query(RFQ).options(
        joinedload(RFQ.items),
        joinedload(RFQ.documents).joinedload(RFQDocument.image),
        joinedload(RFQ.work_order)
    ).filter(
        RFQ.id == rfq_id,
        RFQ.company_id == hhd.company_id,
        RFQ.deleted_at.is_(None)
    ).first()

    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")

    # Serialize items
    items = []
    for item in rfq.items:
        items.append({
            "id": item.id,
            "item_id": item.item_id,
            "item_number": item.item_number,
            "description": item.description,
            "quantity_requested": float(item.quantity_requested),
            "unit": item.unit or "EA",
            "notes": item.notes
        })

    # Serialize images
    images = []
    for doc in rfq.documents:
        if doc.image:
            if doc.image.s3_key and doc.image.s3_key.startswith("local/"):
                url = f"/uploads/{doc.image.s3_key.replace('local/', '')}"
            else:
                from app.services.s3 import generate_presigned_url
                url = generate_presigned_url(doc.image.s3_key, expiration=3600) if doc.image.s3_key else None

            if url:
                images.append({
                    "id": doc.image.id,
                    "url": url,
                    "title": doc.title
                })

    return {
        "id": rfq.id,
        "rfq_number": rfq.rfq_number,
        "title": rfq.title,
        "description": rfq.description,
        "status": rfq.status,
        "priority": rfq.priority,
        "work_order_id": rfq.work_order_id,
        "work_order_number": rfq.work_order.wo_number if rfq.work_order else None,
        "created_at": rfq.created_at.isoformat(),
        "submitted_at": rfq.submitted_at.isoformat() if rfq.submitted_at else None,
        "items": items,
        "images": images
    }


# =============================================================================
# RFQ Create Endpoint
# =============================================================================

@router.post("/rfqs")
async def create_rfq(
    rfq_data: MobileRFQCreate,
    db: Session = Depends(get_db),
    hhd: HHDContext = Depends(get_hhd_auth)
):
    """
    Create a new RFQ (parts request) from mobile.
    The RFQ is automatically submitted (not draft) since mobile users just want to request parts.
    """
    # Validate we have items
    if not rfq_data.items or len(rfq_data.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="At least one item is required"
        )

    # Validate priority
    valid_priorities = ["low", "normal", "high", "urgent"]
    if rfq_data.priority and rfq_data.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
        )

    # Create RFQ
    rfq = RFQ(
        company_id=hhd.company_id,
        rfq_number=generate_rfq_number(db, hhd.company_id),
        rfq_type="spare_parts",  # Mobile requests are always spare parts
        title=rfq_data.title,
        description=rfq_data.description,
        work_order_id=rfq_data.work_order_id,
        priority=rfq_data.priority or "normal",
        status="submitted",  # Auto-submit from mobile
        created_by=hhd.id,
        submitted_at=datetime.utcnow(),
        submitted_by=hhd.id
    )
    db.add(rfq)
    db.flush()  # Get the ID

    # Add items
    for item_data in rfq_data.items:
        item = RFQItem(
            rfq_id=rfq.id,
            item_id=item_data.item_id,
            item_number=item_data.item_number,
            description=item_data.description,
            quantity_requested=item_data.quantity_requested,
            unit=item_data.unit or "EA",
            notes=item_data.notes
        )
        db.add(item)

    # Link images as documents
    if rfq_data.image_ids:
        for image_id in rfq_data.image_ids:
            # Verify image exists
            image = db.query(ProcessedImage).filter(
                ProcessedImage.id == image_id
            ).first()

            if image:
                doc = RFQDocument(
                    rfq_id=rfq.id,
                    image_id=image_id,
                    document_type="attachment",
                    title=f"Mobile upload {image_id}",
                    uploaded_by=hhd.id
                )
                db.add(doc)

    db.commit()
    db.refresh(rfq)

    return {
        "id": rfq.id,
        "rfq_number": rfq.rfq_number,
        "title": rfq.title,
        "status": rfq.status,
        "item_count": len(rfq_data.items),
        "message": f"Parts request {rfq.rfq_number} submitted successfully"
    }
