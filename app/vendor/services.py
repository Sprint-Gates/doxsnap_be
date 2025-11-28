"""
Business logic for vendor serives
"""

import logging
from typing import Dict
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from uuid import UUID

from app.models import Company, Vendor
from app.vendor.schema import VendorCreateRequest, VendorUpdateRequest

# Configure logger
logger = logging.getLogger(__name__)

def create_vendor(db: Session, company_id: str, data: VendorCreateRequest) -> JSONResponse:
    """
    Create a new vendor for a company.
    """
    try:
        company_uuid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id. Must be a valid UUID.")

    company = db.query(Company).filter(Company.company_id == company_uuid).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    # Check for duplicate vendor code in the same company
    if db.query(Vendor).filter(
        Vendor.vendor_company_id == company_uuid,
        Vendor.vendor_code == data.vendor_code
    ).first():
        raise HTTPException(status_code=409, detail="Vendor code already exists for this company")

    vendor = Vendor(
        vendor_name=data.vendor_name,
        vendor_accounting_number=data.vendor_accounting_number,
        vendor_code=data.vendor_code,
        vendor_vat_number=data.vendor_vat_number,
        vendor_payable_account=data.vendor_payable_account,
        vendor_receivable_account=data.vendor_receivable_account,
        vendor_tax_rate=data.vendor_tax_rate,
        vendor_is_active=data.vendor_is_active,
        vendor_company_id=company_uuid
    )
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    # except Exception as exc:
    #     db.rollback()
    #     logger.error("Vendor creation failed", extra={"error": str(exc), "company_id": company_uuid})
    #     raise HTTPException(status_code=500, detail="Vendor creation failed")

    return JSONResponse(
        content={
            "vendor_id": str(vendor.vendor_id),
            "vendor_name": vendor.vendor_name,
            "vendor_code": vendor.vendor_code,
            "vendor_accounting_number": vendor.vendor_accounting_number,
            "vendor_vat_number": vendor.vendor_vat_number,
            "vendor_payable_account": vendor.vendor_payable_account,
            "vendor_receivable_account": vendor.vendor_receivable_account,
            "vendor_tax_rate": vendor.vendor_tax_rate,
            "vendor_is_active": vendor.vendor_is_active,
            "message": "Vendor created successfully"
        },
        status_code=201
    )


def update_vendor(db: Session, vendor_id: str, data: VendorUpdateRequest) -> JSONResponse:
    """
    Update details of an existing vendor.
    Only provided fields in VendorUpdateRequest will be updated.
    """
    try:
        vendor_uuid = UUID(vendor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor_id. Must be a valid UUID.")

    vendor = db.query(Vendor).filter(Vendor.vendor_id == vendor_uuid).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    try:
        for field, value in data.dict(exclude_unset=True).items():
            setattr(vendor, field, value)
        db.commit()
        db.refresh(vendor)
    except Exception as exc:
        db.rollback()
        logger.error("Vendor update failed", extra={"error": str(exc), "vendor_id": vendor_uuid})
        raise HTTPException(status_code=500, detail="Vendor update failed")

    return JSONResponse(
        content={
            "vendor_id": str(vendor.vendor_id),
            "vendor_name": vendor.vendor_name,
            "vendor_code": vendor.vendor_code,
            "vendor_accounting_number": vendor.vendor_accounting_number,
            "vendor_vat_number": vendor.vendor_vat_number,
            "vendor_payable_account": vendor.vendor_payable_account,
            "vendor_receivable_account": vendor.vendor_receivable_account,
            "vendor_tax_rate": vendor.vendor_tax_rate,
            "vendor_is_active": vendor.vendor_is_active,
            "message": "Vendor updated successfully"
        }
    )


def disable_vendor(db: Session, vendor_id: str) -> JSONResponse:
    """
    Disable a vendor (soft delete) by setting vendor_status to INACTIVE.
    """
    try:
        vendor_uuid = UUID(vendor_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor_id. Must be a valid UUID.")

    vendor = db.query(Vendor).filter(Vendor.vendor_id == vendor_uuid).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    if vendor.vendor_is_active == 0:
        return JSONResponse(
            content={"message": "Vendor is already inactive"},
            status_code=200
        )

    try:
        vendor.vendor_is_active = 0
        db.commit()
        db.refresh(vendor)
    except Exception as exc:
        db.rollback()
        logger.error("Vendor disable failed", extra={"error": str(exc), "vendor_id": vendor_uuid})
        raise HTTPException(status_code=500, detail="Failed to disable vendor")

    return JSONResponse(
        content={
            "vendor_id": str(vendor.vendor_id),
            "vendor_name": vendor.vendor_name,
            "vendor_is_active": vendor.vendor_is_active,
            "message": "Vendor disabled successfully"
        },
        status_code=200
    )