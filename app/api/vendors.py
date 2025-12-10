from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from app.database import get_db
from app.models import Vendor, User, ProcessedImage, Project, Branch, Client
from app.api.auth import get_current_user
import json

router = APIRouter()
security = HTTPBearer()


class VendorCreate(BaseModel):
    name: str
    display_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    registration_number: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None


class VendorUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_number: Optional[str] = None
    registration_number: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class VendorResponse(BaseModel):
    id: int
    name: str
    display_name: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    tax_number: Optional[str]
    registration_number: Optional[str]
    website: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.get("/", response_model=List[VendorResponse])
async def get_vendors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False, description="Include inactive vendors"),
    search: Optional[str] = Query(None, description="Search by name, email, or tax number")
):
    """Get all vendors with optional filtering"""
    query = db.query(Vendor).filter(Vendor.company_id == current_user.company_id)

    if not include_inactive:
        query = query.filter(Vendor.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Vendor.name.ilike(search_term),
                Vendor.display_name.ilike(search_term),
                Vendor.email.ilike(search_term),
                Vendor.tax_number.ilike(search_term),
                Vendor.registration_number.ilike(search_term)
            )
        )

    vendors = query.order_by(Vendor.display_name).all()

    return [
        VendorResponse(
            id=v.id,
            name=v.name,
            display_name=v.display_name,
            email=v.email,
            phone=v.phone,
            address=v.address,
            tax_number=v.tax_number,
            registration_number=v.registration_number,
            website=v.website,
            notes=v.notes,
            is_active=v.is_active,
            created_at=v.created_at.isoformat() if v.created_at else "",
            updated_at=v.updated_at.isoformat() if v.updated_at else ""
        )
        for v in vendors
    ]


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific vendor by ID"""
    vendor = db.query(Vendor).filter(
        Vendor.id == vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found"
        )

    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        display_name=vendor.display_name,
        email=vendor.email,
        phone=vendor.phone,
        address=vendor.address,
        tax_number=vendor.tax_number,
        registration_number=vendor.registration_number,
        website=vendor.website,
        notes=vendor.notes,
        is_active=vendor.is_active,
        created_at=vendor.created_at.isoformat() if vendor.created_at else "",
        updated_at=vendor.updated_at.isoformat() if vendor.updated_at else ""
    )


@router.post("/", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    vendor_data: VendorCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new vendor"""
    # Check if vendor with same name already exists for this company
    existing = db.query(Vendor).filter(
        Vendor.name == vendor_data.name,
        Vendor.company_id == current_user.company_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A vendor with this name already exists"
        )

    vendor = Vendor(
        company_id=current_user.company_id,
        name=vendor_data.name,
        display_name=vendor_data.display_name,
        email=vendor_data.email,
        phone=vendor_data.phone,
        address=vendor_data.address,
        tax_number=vendor_data.tax_number,
        registration_number=vendor_data.registration_number,
        website=vendor_data.website,
        notes=vendor_data.notes,
        is_active=True
    )

    db.add(vendor)
    db.commit()
    db.refresh(vendor)

    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        display_name=vendor.display_name,
        email=vendor.email,
        phone=vendor.phone,
        address=vendor.address,
        tax_number=vendor.tax_number,
        registration_number=vendor.registration_number,
        website=vendor.website,
        notes=vendor.notes,
        is_active=vendor.is_active,
        created_at=vendor.created_at.isoformat() if vendor.created_at else "",
        updated_at=vendor.updated_at.isoformat() if vendor.updated_at else ""
    )


@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    vendor_data: VendorUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a vendor"""
    vendor = db.query(Vendor).filter(
        Vendor.id == vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found"
        )

    # Check for duplicate name if name is being updated
    if vendor_data.name and vendor_data.name != vendor.name:
        existing = db.query(Vendor).filter(
            Vendor.name == vendor_data.name,
            Vendor.company_id == current_user.company_id,
            Vendor.id != vendor_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A vendor with this name already exists"
            )

    # Update fields that are provided
    update_data = vendor_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(vendor, field, value)

    db.commit()
    db.refresh(vendor)

    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        display_name=vendor.display_name,
        email=vendor.email,
        phone=vendor.phone,
        address=vendor.address,
        tax_number=vendor.tax_number,
        registration_number=vendor.registration_number,
        website=vendor.website,
        notes=vendor.notes,
        is_active=vendor.is_active,
        created_at=vendor.created_at.isoformat() if vendor.created_at else "",
        updated_at=vendor.updated_at.isoformat() if vendor.updated_at else ""
    )


@router.patch("/{vendor_id}/toggle-status", response_model=VendorResponse)
async def toggle_vendor_status(
    vendor_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle vendor active status (enable/disable)"""
    vendor = db.query(Vendor).filter(
        Vendor.id == vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found"
        )

    vendor.is_active = not vendor.is_active
    db.commit()
    db.refresh(vendor)

    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        display_name=vendor.display_name,
        email=vendor.email,
        phone=vendor.phone,
        address=vendor.address,
        tax_number=vendor.tax_number,
        registration_number=vendor.registration_number,
        website=vendor.website,
        notes=vendor.notes,
        is_active=vendor.is_active,
        created_at=vendor.created_at.isoformat() if vendor.created_at else "",
        updated_at=vendor.updated_at.isoformat() if vendor.updated_at else ""
    )


@router.get("/lookup/by-name")
async def lookup_vendor_by_name(
    name: str = Query(..., description="Vendor name to look up"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Look up vendor by name (used by OCR processing)"""
    # Try exact match first
    vendor = db.query(Vendor).filter(
        Vendor.name.ilike(name),
        Vendor.company_id == current_user.company_id,
        Vendor.is_active == True
    ).first()

    if vendor:
        return {
            "found": True,
            "vendor": VendorResponse(
                id=vendor.id,
                name=vendor.name,
                display_name=vendor.display_name,
                email=vendor.email,
                phone=vendor.phone,
                address=vendor.address,
                tax_number=vendor.tax_number,
                registration_number=vendor.registration_number,
                website=vendor.website,
                notes=vendor.notes,
                is_active=vendor.is_active,
                created_at=vendor.created_at.isoformat() if vendor.created_at else "",
                updated_at=vendor.updated_at.isoformat() if vendor.updated_at else ""
            )
        }

    # Try partial match
    search_term = f"%{name}%"
    similar_vendors = db.query(Vendor).filter(
        or_(
            Vendor.name.ilike(search_term),
            Vendor.display_name.ilike(search_term)
        ),
        Vendor.company_id == current_user.company_id,
        Vendor.is_active == True
    ).limit(5).all()

    return {
        "found": False,
        "suggestions": [
            {
                "id": v.id,
                "name": v.name,
                "display_name": v.display_name
            }
            for v in similar_vendors
        ],
        "extracted_name": name
    }


@router.get("/{vendor_id}/invoices")
async def get_vendor_invoices(
    vendor_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all invoices for a specific vendor with project allocation info"""
    # Verify vendor belongs to user's company
    vendor = db.query(Vendor).filter(
        Vendor.id == vendor_id,
        Vendor.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found"
        )

    # Get invoices - check both vendor_id column and structured_data
    invoices = db.query(ProcessedImage).filter(
        or_(
            ProcessedImage.vendor_id == vendor_id,
            ProcessedImage.structured_data.ilike(f'%"vendor_id": {vendor_id}%'),
            ProcessedImage.structured_data.ilike(f'%"vendor_id":{vendor_id}%')
        )
    ).order_by(ProcessedImage.created_at.desc()).all()

    result = []
    for invoice in invoices:
        # Parse structured data
        structured_data = {}
        if invoice.structured_data:
            try:
                structured_data = json.loads(invoice.structured_data)
            except:
                pass

        # Get project info
        project_info = None
        if invoice.project_id:
            project = db.query(Project).filter(Project.id == invoice.project_id).first()
            if project:
                branch = db.query(Branch).filter(Branch.id == project.branch_id).first()
                client = db.query(Client).filter(Client.id == branch.client_id).first() if branch else None
                project_info = {
                    "id": project.id,
                    "name": project.name,
                    "code": project.code,
                    "branch": {
                        "id": branch.id,
                        "name": branch.name
                    } if branch else None,
                    "client": {
                        "id": client.id,
                        "name": client.name
                    } if client else None
                }

        # Extract invoice details
        doc_info = structured_data.get("document_info", {})
        financial = structured_data.get("financial_details", {})

        result.append({
            "id": invoice.id,
            "invoice_number": doc_info.get("invoice_number"),
            "invoice_date": doc_info.get("invoice_date"),
            "document_type": invoice.document_type,
            "original_filename": invoice.original_filename,
            "total_amount": financial.get("total_after_tax", 0),
            "currency": financial.get("currency", "USD"),
            "processing_status": invoice.processing_status,
            "project": project_info,
            "created_at": invoice.created_at.isoformat() if invoice.created_at else None
        })

    return {
        "vendor": {
            "id": vendor.id,
            "name": vendor.name,
            "display_name": vendor.display_name
        },
        "total_invoices": len(result),
        "invoices": result
    }
