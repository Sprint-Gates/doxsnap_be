from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from app.database import get_db
from app.UDC.schema import (
    UDCCreateRequest,
    UDCUpdateRequest,
    UDCResponse,
)
from app.UDC.services import (
    create_udc,
    update_udc,
    delete_udc,
    get_udc_by_company
)


router = APIRouter(
    prefix="/api",
    tags=["UDC"]
)


@router.post(
    "/{company_id}/udc",
    response_model=UDCResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create UDC",
    description="Create a new UDC record for the given company."
)
def add_udc(company_id: str, data: UDCCreateRequest, db: Session = Depends(get_db)):
    try:
        return create_udc(db, company_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"UDC creation failed: {str(e)}"
        )


@router.get("/company/{company_id}", response_model=List[UDCResponse])
def read_udc_for_company(company_id: str, db: Session = Depends(get_db)):
    """
    Get all UDC entries for a specific company.
    """
    udc_entries = get_udc_by_company(db, company_id)
    
    if not udc_entries:
        raise HTTPException(status_code=404, detail="No UDC entries found for this company")
    
    return udc_entries

@router.put(
    "/udc/{udc_id}",
    response_model=UDCResponse,
    status_code=status.HTTP_200_OK,
    summary="Update UDC",
    description="Update details of an existing UDC entry.",
)
def edit_udc(udc_id: str, data: UDCUpdateRequest, db: Session = Depends(get_db)):
    try:
        return update_udc(db, udc_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"UDC update failed: {str(e)}"
        )


@router.delete(
    "/udc/{udc_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete UDC",
    description="Delete a UDC entry permanently."
)
def remove_udc(udc_id: str, db: Session = Depends(get_db)):
    try:
        return delete_udc(db, udc_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"UDC deletion failed: {str(e)}"
        )
