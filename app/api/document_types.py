from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import DocumentType as DocumentTypeModel, User
from app.api.auth import get_current_user

router = APIRouter()


class DocumentTypeCreate(BaseModel):
    name: str
    display_name: str
    description: str = None
    color: str = "#007bff"


class DocumentTypeUpdate(BaseModel):
    display_name: str = None
    description: str = None
    color: str = None
    is_active: bool = None


class DocumentType(BaseModel):
    id: int
    name: str
    display_name: str
    description: str = None
    color: str
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=List[DocumentType])
async def get_document_types(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all document types"""
    query = db.query(DocumentTypeModel)
    
    if not include_inactive:
        query = query.filter(DocumentTypeModel.is_active == True)
    
    document_types = query.order_by(DocumentTypeModel.display_name).all()
    return document_types


@router.get("/{doc_type_id}", response_model=DocumentType)
async def get_document_type(
    doc_type_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific document type"""
    doc_type = db.query(DocumentTypeModel).filter(DocumentTypeModel.id == doc_type_id).first()
    
    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document type not found"
        )
    
    return doc_type


@router.post("/", response_model=DocumentType)
async def create_document_type(
    doc_type: DocumentTypeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new document type"""
    # Check if name already exists
    existing = db.query(DocumentTypeModel).filter(
        DocumentTypeModel.name == doc_type.name.lower().replace(" ", "_")
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document type with this name already exists"
        )
    
    # Create the document type
    db_doc_type = DocumentTypeModel(
        name=doc_type.name.lower().replace(" ", "_"),
        display_name=doc_type.display_name,
        description=doc_type.description,
        color=doc_type.color,
        is_system=False  # User-created types are not system types
    )
    
    db.add(db_doc_type)
    db.commit()
    db.refresh(db_doc_type)
    
    return db_doc_type


@router.put("/{doc_type_id}", response_model=DocumentType)
async def update_document_type(
    doc_type_id: int,
    doc_type_update: DocumentTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a document type"""
    doc_type = db.query(DocumentTypeModel).filter(DocumentTypeModel.id == doc_type_id).first()
    
    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document type not found"
        )
    
    # Update fields if provided
    update_data = doc_type_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(doc_type, field, value)
    
    try:
        db.commit()
        db.refresh(doc_type)
        return doc_type
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating document type: {str(e)}"
        )


@router.delete("/{doc_type_id}")
async def delete_document_type(
    doc_type_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a document type (only non-system types can be deleted)"""
    doc_type = db.query(DocumentTypeModel).filter(DocumentTypeModel.id == doc_type_id).first()
    
    if not doc_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document type not found"
        )
    
    if doc_type.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete system document types"
        )
    
    try:
        db.delete(doc_type)
        db.commit()
        return {"message": "Document type deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting document type: {str(e)}"
        )


@router.post("/seed")
async def seed_document_types(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Seed default document types"""
    default_types = [
        {"name": "invoice", "display_name": "Invoice", "description": "Sales invoice document", "color": "#007bff", "is_system": True},
        {"name": "receipt", "display_name": "Receipt", "description": "Payment receipt document", "color": "#28a745", "is_system": True},
        {"name": "purchase_order", "display_name": "Purchase Order", "description": "Purchase order document", "color": "#ffc107", "is_system": True},
        {"name": "bill_of_lading", "display_name": "Bill of Lading", "description": "Shipping bill of lading", "color": "#fd7e14", "is_system": True},
        {"name": "packing_slip", "display_name": "Packing Slip", "description": "Package packing slip", "color": "#e83e8c", "is_system": True},
        {"name": "contract", "display_name": "Contract", "description": "Legal contract document", "color": "#6f42c1", "is_system": True},
        {"name": "delivery_note", "display_name": "Delivery Note", "description": "Delivery note document", "color": "#20c997", "is_system": True},
        {"name": "tax_document", "display_name": "Tax Document", "description": "Tax-related document", "color": "#17a2b8", "is_system": True},
        {"name": "other", "display_name": "Other", "description": "Other document types", "color": "#6c757d", "is_system": True}
    ]
    
    created_count = 0
    for doc_type_data in default_types:
        existing = db.query(DocumentTypeModel).filter(
            DocumentTypeModel.name == doc_type_data["name"]
        ).first()
        
        if not existing:
            db_doc_type = DocumentTypeModel(**doc_type_data)
            db.add(db_doc_type)
            created_count += 1
    
    try:
        db.commit()
        return {
            "message": f"Document types seeded successfully. Created {created_count} new types.",
            "created_count": created_count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error seeding document types: {str(e)}"
        )