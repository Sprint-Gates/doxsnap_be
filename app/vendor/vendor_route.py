from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.vendor.schema import VendorCreateRequest, VendorUpdateRequest, VendorResponse
from app.vendor.services import create_vendor, update_vendor, disable_vendor

router = APIRouter(
prefix="/api",
tags=["Vendor"]
)

@router.post(
    "/{company_id}/vendors",
    response_model=VendorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Vendor",
    description="Create a new vendor for the given company."
)
def add_vendor(
    company_id: str,
    data: VendorCreateRequest,
    db: Session = Depends(get_db)
):
    try:
        return create_vendor(db, company_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vendor creation failed: {str(e)}"
        )

@router.put(
    "/vendors/{vendor_id}",
    response_model=VendorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Vendor",
    description="Update details of an existing vendor."
)
def edit_vendor(
    vendor_id: str,
    data: VendorUpdateRequest,
    db: Session = Depends(get_db)
):
    try:
        return update_vendor(db, vendor_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vendor update failed: {str(e)}"
        )

@router.delete(
    "/vendors/{vendor_id}",
    status_code=status.HTTP_200_OK,
    summary="Disable Vendor",
    description="Disable a vendor instead of deleting it (soft delete)."
)
def soft_delete_vendor(
    vendor_id: str,
    db: Session = Depends(get_db)
):
    try:
        return disable_vendor(db, vendor_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vendor disable failed: {str(e)}"
        )