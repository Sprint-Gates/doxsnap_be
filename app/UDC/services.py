"""
Business logic for UDC services
"""

import logging
from typing import List
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from uuid import UUID

from app.models import UDC, Company
from app.UDC.schema import UDCCreateRequest, UDCUpdateRequest, UDCResponse

# Configure logger
logger = logging.getLogger(__name__)


def create_udc(db: Session, company_id: str, data: UDCCreateRequest) -> JSONResponse:
    """
    Create a new UDC record for a company.
    """
    try:
        # Convert string (with or without dashes) to UUID object
        company_uuid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id. Must be a valid UUID.")

    company = db.query(Company).filter(Company.company_id == company_uuid).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company does not exist")

    try:
        udc = UDC(
            udc_country=data.udc_country,
            udc_city=data.udc_city,
            udc_state=data.udc_state,
            udc_company_id=company_uuid
        )
        db.add(udc)
        db.commit()
        db.refresh(udc)

    except Exception as exc:
        db.rollback()
        logger.error("UDC creation failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Failed to create UDC record")

    return JSONResponse(
        content={
            "udc_id": str(udc.udc_id),
            "udc_country": udc.udc_country,
            "udc_city": udc.udc_city,
            "udc_state": udc.udc_state
        },
        status_code=201
    )


def get_udc_by_company(db: Session, company_id: str) -> List[UDC]:
    """
    Get all UDC entries for a given company.
    
    Args:
        db (Session): SQLAlchemy session
        company_id (UUID): The ID of the company

    Returns:
        List[UDC]: List of UDC objects for the company
    """
    try:
        # Convert string (with or without dashes) to UUID object
        company_uuid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id. Must be a valid UUID.")

    udc_list = db.query(UDC).filter(UDC.udc_company_id == company_uuid).all()
    return udc_list

def update_udc(db: Session, udc_id: str, data: UDCUpdateRequest) -> JSONResponse:
    """
    Update UDC fields (partial update).
    """
    try:
        udc_uuid = UUID(udc_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UDC id. Must be a valid UUID.")

    udc = db.query(UDC).filter(UDC.udc_id == udc_uuid).first()
    if not udc:
        raise HTTPException(status_code=404, detail="UDC record not found")

    try:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(udc, field, value)

        db.commit()
        db.refresh(udc)

    except Exception as exc:
        db.rollback()
        logger.error("UDC update failed", extra={"error": str(exc), "udc_id": udc_id})
        raise HTTPException(status_code=500, detail="Failed to update UDC record")

    return JSONResponse(
        content={
            "udc_id": str(udc.udc_id),
            "udc_country": udc.udc_country,
            "udc_city": udc.udc_city,
            "udc_state": udc.udc_state,
            "udc_company_id": str(udc.udc_company_id),
            "message": "UDC updated successfully"
        }
    )


def delete_udc(db: Session, udc_id: str) -> JSONResponse:
    """
    Delete a UDC record permanently.
    """
    try:
        udc_uuid = UUID(udc_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UDC id. Must be a valid UUID.")

    udc = db.query(UDC).filter(UDC.udc_id == udc_uuid).first()
    if not udc:
        raise HTTPException(status_code=404, detail="UDC record not found")

    try:
        db.delete(udc)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("UDC deletion failed", extra={"error": str(exc), "udc_id": udc_id})
        raise HTTPException(status_code=500, detail="Failed to delete UDC record")

    return JSONResponse(
        content={"message": "UDC record deleted successfully"},
        status_code=200
    )
