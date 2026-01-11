import os
import uuid
import io
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from PIL import Image

from app.database import get_db
from app.schemas import ProcessedImage, ProcessedImageList
from app.models import ProcessedImage as ProcessedImageModel, User, InvoiceItem, ItemLedger, PurchaseOrderInvoice, PurchaseOrder, InvoiceAllocation, AllocationPeriod, Company
from app.api.auth import get_current_user
from app.services.s3 import upload_to_s3, process_image, generate_presigned_url, delete_from_s3
from app.services.email import EmailService
from app.services.mock_email import MockEmailService
from app.api.admin import process_invoice_line_items

logger = logging.getLogger(__name__)

router = APIRouter()

# Supported file types
SUPPORTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"]
SUPPORTED_PDF_TYPE = "application/pdf"


def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    """Convert first page of PDF to image bytes."""
    try:
        import fitz  # PyMuPDF

        # Open PDF from bytes
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")

        if len(pdf_document) == 0:
            raise ValueError("PDF has no pages")

        # Get first page
        page = pdf_document[0]

        # Render page to image with high resolution (300 DPI)
        mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
        pix = page.get_pixmap(matrix=mat)

        # Convert to PNG bytes
        img_bytes = pix.tobytes("png")

        pdf_document.close()

        return img_bytes
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF processing is not available. Please install PyMuPDF (pip install pymupdf)."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to convert PDF to image: {str(e)}"
        )


@router.post("/upload", response_model=ProcessedImage)
async def upload_image(
    file: UploadFile = File(...),
    document_type: str = "invoice",
    invoice_category: str = None,
    site_id: int = None,
    contract_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check if user has remaining documents to process
    if current_user.remaining_documents <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have reached your document processing limit. No documents remaining."
        )

    # Check if file type is supported
    is_image = file.content_type in SUPPORTED_IMAGE_TYPES
    is_pdf = file.content_type == SUPPORTED_PDF_TYPE

    if not is_image and not is_pdf:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File must be an image or PDF. Supported types: {', '.join(SUPPORTED_IMAGE_TYPES + [SUPPORTED_PDF_TYPE])}"
        )

    # Read file content
    content = await file.read()

    # Convert PDF to image if necessary
    if is_pdf:
        content = convert_pdf_to_image(content)
        # Use PNG extension for converted PDFs
        unique_filename = f"{uuid.uuid4()}.png"
    else:
        file_extension = file.filename.split(".")[-1]
        unique_filename = f"{uuid.uuid4()}.{file_extension}"

    # Save file temporarily
    temp_file_path = f"uploads/{unique_filename}"
    with open(temp_file_path, "wb") as buffer:
        buffer.write(content)

    try:
        # Read file content for invoice processing
        with open(temp_file_path, 'rb') as f:
            file_bytes = f.read()

        # Process image (resize, compress, OCR, AI extraction) - pass db and company_id for vendor lookup/creation
        processed_image_path, invoice_results = process_image(temp_file_path, file_bytes, db, current_user.company_id)

        # Increment company's document usage counter IMMEDIATELY after OCR processing
        # This counts the API usage regardless of whether the invoice is saved or rejected
        if current_user.company_id:
            company_for_counter = db.query(Company).filter(Company.id == current_user.company_id).first()
            if company_for_counter:
                company_for_counter.documents_used_this_month += 1
                db.commit()
                logger.info(f"[DOCUMENT_COUNTER] Upload - Company {company_for_counter.id}: incremented to {company_for_counter.documents_used_this_month}")

        # Try to upload to S3, fallback to local if it fails
        try:
            s3_key, s3_url = upload_to_s3(processed_image_path, unique_filename)
            processing_status = "completed"
            
            # For S3, store the S3 key - URL will be generated on-demand
            s3_url = s3_key
            
            # Cleanup processed file after successful S3 upload
            if os.path.exists(processed_image_path):
                os.remove(processed_image_path)
                
        except Exception as s3_error:
            print(f"S3 upload failed, using local storage: {s3_error}")
            
            # Fallback to local storage
            s3_key = f"local/{unique_filename}"
            s3_url = f"local/{unique_filename}"
            processing_status = "completed_local"
            
            # Keep processed file for local serving
            final_file_path = f"uploads/{unique_filename}"
            if processed_image_path != temp_file_path:
                import shutil
                shutil.move(processed_image_path, final_file_path)
        
        # Prepare structured data for storage
        structured_data_json = None
        extraction_confidence = 0.0
        
        if invoice_results.get("structured_data"):
            import json
            structured_data_json = json.dumps(invoice_results["structured_data"])
            
            # Extract confidence score from structured data
            if isinstance(invoice_results["structured_data"], dict):
                validation = invoice_results["structured_data"].get("validation", {})
                extraction_confidence = float(validation.get("confidence_score", 0))
        
        # Get enhancement metrics
        enhancement_features = invoice_results.get("enhancement_features", {})
        
        try:
            # Create database record with enhanced invoice processing results
            db_image = ProcessedImageModel(
                user_id=current_user.id,
                original_filename=file.filename,
                s3_key=s3_key,
                s3_url=s3_url,
                processing_status=processing_status,
                document_type=document_type,
                invoice_category=invoice_category if document_type == "invoice" else None,
                site_id=site_id,
                contract_id=contract_id,
                ocr_extracted_words=int(invoice_results.get("total_words_extracted", 0)),
                ocr_average_confidence=float(invoice_results.get("average_confidence", 0.0)),
                ocr_preprocessing_methods=int(enhancement_features.get("multiple_preprocessing", 1)),
                patterns_detected=int(enhancement_features.get("pattern_recognition", 0)),
                has_structured_data=bool(invoice_results.get("structured_data")),
                structured_data=structured_data_json,
                extraction_confidence=float(extraction_confidence),
                processing_method="enhanced"
            )
        except Exception as db_create_error:
            print(f"Database record creation error: {db_create_error}")
            # Fallback with minimal data
            db_image = ProcessedImageModel(
                user_id=current_user.id,
                original_filename=file.filename,
                s3_key=s3_key,
                s3_url=s3_url,
                processing_status=processing_status,
                document_type=document_type,
                invoice_category=invoice_category if document_type == "invoice" else None,
                ocr_extracted_words=0,
                ocr_average_confidence=0.0,
                ocr_preprocessing_methods=1,
                patterns_detected=0,
                has_structured_data=False,
                structured_data=None,
                extraction_confidence=0.0,
                processing_method="fallback"
            )
        db.add(db_image)
        db.commit()
        db.refresh(db_image)

        # Process line items: match with Item Master, create InvoiceItem records,
        # and auto-receive matched items to main warehouse
        if invoice_results.get("structured_data") and document_type == "invoice" and current_user.company_id:
            try:
                line_items_result = process_invoice_line_items(
                    db=db,
                    invoice_id=db_image.id,
                    structured_data=invoice_results["structured_data"],
                    company_id=current_user.company_id,
                    user_id=current_user.id
                )
                logger.info(f"Line items processing: {line_items_result}")
            except Exception as line_items_error:
                logger.error(f"Error processing line items: {line_items_error}")

        # Deduct one document from user's quota after successful processing
        current_user.remaining_documents -= 1
        db.commit()

        # Refresh the user object to get updated quota
        db.refresh(current_user)

        return db_image

    except Exception as e:
        # Cleanup temporary files
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing image: {str(e)}"
        )


# Pydantic models for manual document creation
from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal

class ManualLineItem(BaseModel):
    """Line item for manual document entry"""
    description: str
    item_number: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    total_price: Optional[float] = None

class ManualDocumentCreate(BaseModel):
    """Request body for creating a manual document"""
    document_type: str = "invoice"  # invoice, receipt, purchase_order, etc.
    invoice_category: Optional[str] = None  # service, spare_parts
    vendor_id: Optional[int] = None  # Legacy vendor table
    address_book_id: Optional[int] = None  # Address Book vendor (preferred)
    site_id: Optional[int] = None
    contract_id: Optional[int] = None

    # Document details
    document_number: Optional[str] = None  # Invoice/Receipt number
    document_date: Optional[str] = None  # YYYY-MM-DD format
    due_date: Optional[str] = None
    currency: Optional[str] = "USD"

    # Amounts
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    total_amount: Optional[float] = None

    # Line items
    line_items: Optional[List[ManualLineItem]] = []

    # Notes
    notes: Optional[str] = None


@router.post("/manual", response_model=ProcessedImage)
async def create_manual_document(
    document: ManualDocumentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a document manually without scanning/OCR.
    This allows users to enter invoice/receipt data directly.
    """
    import json
    from datetime import datetime

    # Validate document type
    valid_types = ['invoice', 'receipt', 'purchase_order', 'bill_of_lading', 'packing_slip', 'contract', 'delivery_note', 'tax_document', 'other']
    if document.document_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document type. Must be one of: {', '.join(valid_types)}"
        )

    # Build structured data from the manual entry - use nested structure matching frontend expectations
    structured_data = {
        "document_info": {
            "invoice_number": document.document_number,
            "invoice_date": document.document_date,
            "due_date": document.due_date,
            "currency": document.currency or "USD"
        },
        "supplier": {
            "company_name": None,
            "company_address": None,
            "email": None,
            "phone": None,
            "vendor_id": document.vendor_id,
            "address_book_id": document.address_book_id
        },
        "customer": {
            "contact_person": None,
            "company_name": None,
            "address": None
        },
        "financial_details": {
            "subtotal": document.subtotal or 0,
            "total_tax_amount": document.tax_amount or 0,
            "discount": document.discount_amount or 0,
            "total_after_tax": document.total_amount or 0
        },
        "line_items": [],
        "notes": document.notes
    }

    # Get supplier info - prefer Address Book, fall back to legacy Vendor
    if document.address_book_id:
        from app.models import AddressBook
        ab_entry = db.query(AddressBook).filter(AddressBook.id == document.address_book_id).first()
        if ab_entry:
            structured_data["supplier"]["company_name"] = ab_entry.alpha_name
            structured_data["supplier"]["company_address"] = " ".join(filter(None, [
                ab_entry.address_line_1,
                ab_entry.address_line_2,
                ab_entry.city,
                ab_entry.country
            ]))
            structured_data["supplier"]["email"] = ab_entry.email
            structured_data["supplier"]["phone"] = ab_entry.phone_primary
            structured_data["supplier"]["tax_number"] = ab_entry.tax_id
            structured_data["supplier"]["address_book_id"] = ab_entry.id
    # Legacy vendor_id handling removed - use address_book_id instead

    # Add line items with proper structure
    for item in document.line_items or []:
        structured_data["line_items"].append({
            "description": item.description,
            "item_number": item.item_number,
            "quantity": item.quantity or 0,
            "unit": item.unit,
            "unit_price": item.unit_price or 0,
            "total_line_amount": item.total_price or 0
        })

    # Create document title based on type and number
    doc_title = f"Manual {document.document_type.replace('_', ' ').title()}"
    if document.document_number:
        doc_title += f" - {document.document_number}"

    try:
        # Create the ProcessedImage record (this is the main document record)
        db_image = ProcessedImageModel(
            user_id=current_user.id,
            original_filename=doc_title,
            s3_key=None,  # No file uploaded for manual entry
            s3_url=None,
            processing_status="completed",  # Manual entry is always "completed"
            document_type=document.document_type,
            invoice_category=document.invoice_category if document.document_type == "invoice" else None,
            site_id=document.site_id,
            contract_id=document.contract_id,
            address_book_id=document.address_book_id or document.vendor_id,  # Support legacy vendor_id
            ocr_extracted_words=0,
            ocr_average_confidence=1.0,  # Manual entry has perfect "confidence"
            ocr_preprocessing_methods=0,
            patterns_detected=0,
            has_structured_data=True,
            structured_data=json.dumps(structured_data),
            extraction_confidence=1.0,  # Manual entry has perfect confidence
            processing_method="manual"  # Mark as manually created
        )

        db.add(db_image)

        # Increment company's document usage counter for this month
        if current_user.company_id:
            company = db.query(Company).filter(Company.id == current_user.company_id).first()
            if company:
                company.documents_used_this_month += 1
                logger.info(f"[DOCUMENT_COUNTER] Manual entry - Incremented for company {company.id}: now {company.documents_used_this_month}")

        db.commit()
        db.refresh(db_image)

        # Create InvoiceItem records for line items
        if document.line_items and document.document_type in ["invoice", "receipt", "purchase_order"]:
            for item in document.line_items:
                invoice_item = InvoiceItem(
                    invoice_id=db_image.id,
                    item_description=item.description,
                    item_number=item.item_number,
                    quantity=item.quantity,
                    unit=item.unit,
                    unit_price=item.unit_price,
                    total_price=item.total_price,
                    receive_status="pending"
                )
                db.add(invoice_item)

            db.commit()

        return db_image

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating manual document: {str(e)}"
        )


@router.get("/", response_model=ProcessedImageList)
async def get_user_images(
    response: Response,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Add cache control headers to prevent caching issues
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    offset = (page - 1) * size
    
    images = db.query(ProcessedImageModel)\
        .filter(ProcessedImageModel.user_id == current_user.id)\
        .order_by(ProcessedImageModel.created_at.desc())\
        .offset(offset)\
        .limit(size)\
        .all()
    
    total = db.query(ProcessedImageModel)\
        .filter(ProcessedImageModel.user_id == current_user.id)\
        .count()
    
    return ProcessedImageList(
        images=images,
        total=total,
        page=page,
        size=size
    )


@router.get("/{image_id}", response_model=ProcessedImage)
async def get_image(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()
    
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    return image


@router.put("/{image_id}", response_model=ProcessedImage)
async def update_image(
    image_id: int,
    document_type: str = None,
    original_filename: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update image metadata (document type and filename)"""
    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()
    
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    # Update fields if provided
    if document_type is not None:
        # Validate document type
        valid_types = ['invoice', 'receipt', 'purchase_order', 'bill_of_lading', 'packing_slip', 'contract', 'delivery_note', 'tax_document', 'other']
        if document_type not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document type. Must be one of: {', '.join(valid_types)}"
            )
        image.document_type = document_type
    
    if original_filename is not None:
        image.original_filename = original_filename
    
    try:
        db.commit()
        db.refresh(image)
        return image
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating image: {str(e)}"
        )


@router.get("/{image_id}/structured-data")
async def get_image_structured_data(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the complete structured data extracted from an invoice image."""
    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()
    
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    structured_data = None
    if image.structured_data:
        try:
            import json
            structured_data = json.loads(image.structured_data)
        except json.JSONDecodeError:
            structured_data = {"error": "Invalid JSON data stored"}
    
    return {
        "image_id": image_id,
        "original_filename": image.original_filename,
        "processing_method": image.processing_method,
        "ocr_stats": {
            "words_extracted": image.ocr_extracted_words,
            "average_confidence": image.ocr_average_confidence,
            "preprocessing_methods": image.ocr_preprocessing_methods,
            "patterns_detected": image.patterns_detected
        },
        "extraction_confidence": image.extraction_confidence,
        "has_structured_data": image.has_structured_data,
        "structured_data": structured_data,
        "created_at": image.created_at,
        "updated_at": image.updated_at
    }


@router.get("/{image_id}/vendor-lookup")
async def get_vendor_lookup_for_image(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get vendor lookup result for a processed image based on extracted supplier name.
    Uses Address Book (search_type='V') for vendor lookup.
    """
    from app.models import AddressBook
    from sqlalchemy import or_
    import json

    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    # Extract supplier name from structured data
    supplier_name = None
    if image.structured_data:
        try:
            structured_data = json.loads(image.structured_data)
            supplier_name = structured_data.get("supplier", {}).get("company_name")
        except json.JSONDecodeError:
            pass

    if not supplier_name:
        return {
            "found": False,
            "vendor": None,
            "suggestions": [],
            "extracted_name": None,
            "message": "No supplier name found in document"
        }

    # Try exact match first (case-insensitive) - using Address Book with search_type='V'
    vendor = db.query(AddressBook).filter(
        AddressBook.alpha_name.ilike(supplier_name),
        AddressBook.search_type == 'V',
        AddressBook.is_active == True,
        AddressBook.company_id == current_user.company_id
    ).first()

    if vendor:
        return {
            "found": True,
            "vendor": {
                "id": vendor.id,
                "address_number": vendor.address_number,
                "name": vendor.alpha_name,
                "display_name": vendor.alpha_name,
                "email": vendor.email,
                "phone": vendor.phone_primary,
                "address": " ".join(filter(None, [vendor.address_line_1, vendor.city, vendor.country])),
                "tax_number": vendor.tax_id
            },
            "suggestions": [],
            "extracted_name": supplier_name
        }

    # Try partial match for suggestions
    search_term = f"%{supplier_name}%"
    similar_vendors = db.query(AddressBook).filter(
        AddressBook.alpha_name.ilike(search_term),
        AddressBook.search_type == 'V',
        AddressBook.is_active == True,
        AddressBook.company_id == current_user.company_id
    ).limit(5).all()

    return {
        "found": False,
        "vendor": None,
        "suggestions": [
            {
                "id": v.id,
                "address_number": v.address_number,
                "name": v.alpha_name,
                "display_name": v.alpha_name
            }
            for v in similar_vendors
        ],
        "extracted_name": supplier_name
    }


@router.post("/{image_id}/link-vendor")
async def link_vendor_to_image(
    image_id: int,
    address_book_id: int = Query(..., description="Address Book ID (search_type='V')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Link a vendor (Address Book entry) to an image and update the structured data with vendor info."""
    from app.models import AddressBook
    import json

    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    vendor = db.query(AddressBook).filter(
        AddressBook.id == address_book_id,
        AddressBook.search_type == 'V',
        AddressBook.is_active == True,
        AddressBook.company_id == current_user.company_id
    ).first()

    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found in Address Book"
        )

    # Update structured data with vendor info
    try:
        structured_data = {}
        if image.structured_data:
            structured_data = json.loads(image.structured_data)

        # Update supplier info with Address Book data
        if "supplier" not in structured_data:
            structured_data["supplier"] = {}

        structured_data["supplier"]["company_name"] = vendor.alpha_name
        structured_data["supplier"]["address_book_id"] = vendor.id
        if vendor.email:
            structured_data["supplier"]["email"] = vendor.email
        if vendor.phone_primary:
            structured_data["supplier"]["phone"] = vendor.phone_primary
        if vendor.address_line_1:
            structured_data["supplier"]["company_address"] = " ".join(filter(None, [
                vendor.address_line_1, vendor.city, vendor.country
            ]))
        if vendor.tax_id:
            structured_data["supplier"]["tax_number"] = vendor.tax_id

        image.structured_data = json.dumps(structured_data)
        image.address_book_id = vendor.id  # Link to Address Book
        db.commit()
        db.refresh(image)

        return {
            "success": True,
            "message": f"Vendor '{vendor.alpha_name}' linked to invoice successfully",
            "vendor": {
                "id": vendor.id,
                "address_number": vendor.address_number,
                "name": vendor.alpha_name,
                "display_name": vendor.alpha_name
            },
            "image_id": image_id
        }

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error parsing structured data"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error linking vendor: {str(e)}"
        )


@router.delete("/{image_id}")
async def delete_image(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )

    # Check if invoice is linked to an active (non-cancelled) Purchase Order
    po_link = db.query(PurchaseOrderInvoice).join(
        PurchaseOrder, PurchaseOrder.id == PurchaseOrderInvoice.purchase_order_id
    ).filter(
        PurchaseOrderInvoice.invoice_id == image_id,
        PurchaseOrder.status != 'cancelled'
    ).first()

    if po_link:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete invoice - it is linked to an active Purchase Order. Please unlink the invoice from the PO first."
        )

    # Clean up any orphaned PO links (from cancelled POs)
    db.query(PurchaseOrderInvoice).filter(
        PurchaseOrderInvoice.invoice_id == image_id
    ).delete()

    errors = []

    try:
        # Delete from S3 if stored there
        if image.s3_key and not image.s3_key.startswith("local/"):
            if not delete_from_s3(image.s3_key):
                errors.append(f"Failed to delete S3 object: {image.s3_key}")

        # Delete local files if stored locally
        elif image.s3_key and image.s3_key.startswith("local/"):
            filename = image.s3_key.replace("local/", "")
            local_file_path = f"uploads/{filename}"
            if os.path.exists(local_file_path):
                os.remove(local_file_path)

        # Clear invoice reference from ledger entries (keep for audit trail)
        db.query(ItemLedger).filter(ItemLedger.invoice_id == image_id).update(
            {"invoice_id": None}, synchronize_session=False
        )

        # Get allocation ID before expunging anything
        allocation_id = None
        allocation = db.query(InvoiceAllocation).filter(InvoiceAllocation.invoice_id == image_id).first()
        if allocation:
            allocation_id = allocation.id
            # Expunge allocation from session to prevent relationship handling
            db.expunge(allocation)

        # Expunge the image from session BEFORE any deletions to prevent relationship cascade
        db.expunge(image)

        # Now delete using raw queries - session won't try to handle relationships
        if allocation_id:
            db.query(AllocationPeriod).filter(AllocationPeriod.allocation_id == allocation_id).delete(synchronize_session=False)
            db.query(InvoiceAllocation).filter(InvoiceAllocation.id == allocation_id).delete(synchronize_session=False)

        # Delete associated invoice items
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == image_id).delete(synchronize_session=False)

        # Delete the image using direct query
        db.query(ProcessedImageModel).filter(ProcessedImageModel.id == image_id).delete(synchronize_session=False)
        db.commit()
        
        return {
            "message": "Image deleted successfully",
            "errors": errors if errors else None
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting image: {str(e)}"
        )


@router.get("/{image_id}/url")
async def get_image_url(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a viewable URL for the image (authenticated endpoint)"""
    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()
    
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    # Handle S3 images
    if image.s3_key and not image.s3_key.startswith("local/"):
        presigned_url = generate_presigned_url(image.s3_key, expiration=3600)
        if presigned_url:
            return {"url": presigned_url, "type": "s3"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate image access URL"
            )
    
    # Handle local images
    elif image.s3_key and image.s3_key.startswith("local/"):
        filename = image.s3_key.replace("local/", "")
        local_url = f"/uploads/{filename}"
        return {"url": local_url, "type": "local"}
    
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image location not available"
        )


@router.delete("/flush")
async def flush_user_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Flush all user data - delete all images and associated files"""
    try:
        # Get all user images
        user_images = db.query(ProcessedImageModel)\
            .filter(ProcessedImageModel.user_id == current_user.id)\
            .all()
        
        deleted_count = len(user_images)
        s3_deleted = 0
        local_deleted = 0
        errors = []
        
        for image in user_images:
            try:
                # Delete from S3 if stored there
                if image.s3_key and not image.s3_key.startswith("local/"):
                    if delete_from_s3(image.s3_key):
                        s3_deleted += 1
                    else:
                        errors.append(f"Failed to delete S3 object: {image.s3_key}")

                # Delete local files if stored locally
                elif image.s3_key and image.s3_key.startswith("local/"):
                    filename = image.s3_key.replace("local/", "")
                    local_file_path = f"uploads/{filename}"
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                        local_deleted += 1

                # Get allocation ID and expunge objects before deletion
                image_id = image.id
                allocation_id = None
                allocation = db.query(InvoiceAllocation).filter(InvoiceAllocation.invoice_id == image_id).first()
                if allocation:
                    allocation_id = allocation.id
                    db.expunge(allocation)

                # Expunge image from session
                db.expunge(image)

                # Delete allocation and its periods
                if allocation_id:
                    db.query(AllocationPeriod).filter(AllocationPeriod.allocation_id == allocation_id).delete(synchronize_session=False)
                    db.query(InvoiceAllocation).filter(InvoiceAllocation.id == allocation_id).delete(synchronize_session=False)

                # Delete from database using direct query
                db.query(ProcessedImageModel).filter(ProcessedImageModel.id == image_id).delete(synchronize_session=False)

            except Exception as e:
                errors.append(f"Error deleting image {image.id if hasattr(image, 'id') else 'unknown'}: {str(e)}")

        # Reset user's document quota to 5 after flushing all data
        current_user.remaining_documents = 5
        
        db.commit()
        
        return {
            "message": "User data flushed successfully",
            "deleted_images": deleted_count,
            "s3_files_deleted": s3_deleted,
            "local_files_deleted": local_deleted,
            "quota_reset": "User quota reset to 5 free documents",
            "errors": errors if errors else None
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error flushing user data: {str(e)}"
        )


@router.post("/flush-processed")
async def flush_processed_invoices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Flush only successfully processed invoices and notify user"""
    try:
        # Get all processed images for the user
        processed_images = db.query(ProcessedImageModel)\
            .filter(
                ProcessedImageModel.user_id == current_user.id,
                ProcessedImageModel.processing_status == "completed"
            )\
            .all()
        
        deleted_count = len(processed_images)
        s3_deleted = 0
        local_deleted = 0
        errors = []
        
        for image in processed_images:
            try:
                # Delete from S3 if stored there
                if image.s3_key and not image.s3_key.startswith("local/"):
                    if delete_from_s3(image.s3_key):
                        s3_deleted += 1
                    else:
                        errors.append(f"Failed to delete S3 object: {image.s3_key}")

                # Delete local files if stored locally
                elif image.s3_key and image.s3_key.startswith("local/"):
                    filename = image.s3_key.replace("local/", "")
                    local_file_path = f"uploads/{filename}"
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                        local_deleted += 1

                # Get allocation ID and expunge objects before deletion
                image_id = image.id
                allocation_id = None
                allocation = db.query(InvoiceAllocation).filter(InvoiceAllocation.invoice_id == image_id).first()
                if allocation:
                    allocation_id = allocation.id
                    db.expunge(allocation)

                # Expunge image from session
                db.expunge(image)

                # Delete allocation and its periods
                if allocation_id:
                    db.query(AllocationPeriod).filter(AllocationPeriod.allocation_id == allocation_id).delete(synchronize_session=False)
                    db.query(InvoiceAllocation).filter(InvoiceAllocation.id == allocation_id).delete(synchronize_session=False)

                # Delete from database using direct query
                db.query(ProcessedImageModel).filter(ProcessedImageModel.id == image_id).delete(synchronize_session=False)

            except Exception as e:
                errors.append(f"Error deleting processed image {image.id if hasattr(image, 'id') else 'unknown'}: {str(e)}")

        db.commit()

        # Notification message
        notification_message = f"Successfully processed and removed {deleted_count} invoices from your account."
        
        return {
            "message": "Processed invoices flushed successfully",
            "notification": notification_message,
            "deleted_images": deleted_count,
            "s3_files_deleted": s3_deleted,
            "local_files_deleted": local_deleted,
            "errors": errors if errors else None
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error flushing processed invoices: {str(e)}"
        )


@router.post("/{image_id}/send-email")
async def send_invoice_email(
    image_id: int,
    recipient_email: str = Query(..., description="Email address to send the invoice data to"),
    format_type: str = Query("html", description="Email format: 'html' or 'excel'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send invoice data via email"""
    
    # Validate email format
    if not recipient_email or "@" not in recipient_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address"
        )
    
    # Get image data
    image = db.query(ProcessedImageModel)\
        .filter(
            ProcessedImageModel.id == image_id,
            ProcessedImageModel.user_id == current_user.id
        )\
        .first()
    
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    # Check if image has structured data
    if not image.structured_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No invoice data available for this image"
        )
    
    try:
        # For Excel format, get all processed documents for the user
        if format_type.lower() == "excel":
            all_images = db.query(ProcessedImageModel)\
                .filter(ProcessedImageModel.user_id == current_user.id)\
                .filter(ProcessedImageModel.has_structured_data == True)\
                .order_by(ProcessedImageModel.created_at.desc())\
                .all()
            
            if not all_images:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No processed documents with structured data found"
                )
            
            # Prepare all invoice data
            all_invoice_data = []
            for img in all_images:
                if img.structured_data:
                    import json
                    structured_data = json.loads(img.structured_data)
                    invoice_data = {
                        "image_id": img.id,
                        "original_filename": img.original_filename,
                        "processing_method": img.processing_method,
                        "extraction_confidence": img.extraction_confidence,
                        "structured_data": structured_data,
                        "ocr_stats": {
                            "words_extracted": img.ocr_extracted_words,
                            "average_confidence": img.ocr_average_confidence,
                            "preprocessing_methods": img.ocr_preprocessing_methods,
                            "patterns_detected": img.patterns_detected
                        },
                        "created_at": img.created_at.isoformat(),
                    }
                    all_invoice_data.append(invoice_data)
        else:
            # For single document (HTML format)
            import json
            structured_data = json.loads(image.structured_data)
            
            # Prepare invoice data
            invoice_data = {
                "image_id": image.id,
                "original_filename": image.original_filename,
                "processing_method": image.processing_method,
                "extraction_confidence": image.extraction_confidence,
                "structured_data": structured_data,
                "ocr_stats": {
                    "words_extracted": image.ocr_extracted_words,
                    "average_confidence": image.ocr_average_confidence,
                    "preprocessing_methods": image.ocr_preprocessing_methods,
                    "patterns_detected": image.patterns_detected
                },
                "created_at": image.created_at.isoformat(),
            }
        
        # Initialize email service and try to send
        email_service = EmailService()
        mock_service = MockEmailService()
        
        success = False
        use_mock = False
        
        # Try real email service first
        try:
            if format_type.lower() == "excel":
                success = email_service.send_invoice_excel(
                    recipient_email=recipient_email,
                    invoice_data_list=all_invoice_data,
                    user_email=current_user.email
                )
            else:  # Default to HTML format
                success = email_service.send_invoice_data(
                    recipient_email=recipient_email,
                    invoice_data=invoice_data,
                    image_filename=image.original_filename,
                    user_email=current_user.email
                )
        except Exception as email_error:
            print(f"Real email service failed: {email_error}")
            success = False
        
        # If real email fails, use mock service
        if not success:
            print("Falling back to mock email service...")
            use_mock = True
            try:
                if format_type.lower() == "excel":
                    success = mock_service.send_invoice_excel(
                        recipient_email=recipient_email,
                        invoice_data_list=all_invoice_data,
                        user_email=current_user.email
                    )
                else:  # Default to HTML format
                    success = mock_service.send_invoice_data(
                        recipient_email=recipient_email,
                        invoice_data=invoice_data,
                        image_filename=image.original_filename,
                        user_email=current_user.email
                    )
            except Exception as mock_error:
                print(f"Mock email service also failed: {mock_error}")
                success = False
        
        if success:
            if format_type.lower() == "excel":
                message = f"Excel report with {len(all_invoice_data)} processed documents sent successfully"
                if use_mock:
                    message = f"Excel report with {len(all_invoice_data)} processed documents generated successfully (using mock email service for testing)"
                
                return {
                    "message": message,
                    "recipient": recipient_email,
                    "format": format_type,
                    "document_count": len(all_invoice_data),
                    "service_used": "mock" if use_mock else "smtp"
                }
            else:
                message = "Invoice data sent successfully"
                if use_mock:
                    message = "Invoice data processed successfully (using mock email service for testing)"
                
                return {
                    "message": message,
                    "recipient": recipient_email,
                    "format": format_type,
                    "invoice_filename": image.original_filename,
                    "service_used": "mock" if use_mock else "smtp"
                }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send email. Please check your email configuration."
            )
            
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid structured data format"
        )
    except Exception as e:
        print(f"Email sending error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sending email: {str(e)}"
        )