from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.company.schema import SignupRequest, SignupResponse, BranchResponse, BranchUpdateRequest, BranchCreateRequest, VendorCreateRequest, VendorUpdateRequest, VendorResponse
from app.company.services import signup_user_company, create_branch, disable_branch, update_branch, create_vendor, update_vendor, disable_vendor

router = APIRouter(
prefix="/api",
tags=["comapny"]
)

@router.post(
"/signup",
response_model=SignupResponse,
status_code=status.HTTP_201_CREATED,
summary="User signup",
description="Register a new user admin, create company and issue access and refresh tokens. Sets HttpOnly refresh token cookie."
)
def signup_company(
request: Request,
data: SignupRequest,
db: Session = Depends(get_db)
):
    """
    Handle user signup request.
    
    Steps:
    1. Check if email is already registered
    2. Validate password complexity
    3. Create company record, user as admin record, and authentication record
    4. Issue access and refresh tokens
    5. Return access token and set refresh token in HttpOnly cookie

    Args:
        request: FastAPI request object (to get client IP)
        data: SignupRequest containing email, password, username, and company name
        db: Database session

    Returns:
        SignupResponse: Access and refresh tokens along with user info

    Raises:
        HTTPException 400: Email already exists or invalid password
        HTTPException 500: Unexpected error during signup
    """
    ip_address = request.client.host

    try:
        result = signup_user_company(db, data, ip_address)
        return result
    except HTTPException:
        # Propagate HTTPExceptions raised by service
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Signup failed: {str(e)}"
        )
    
@router.post(
    "/companies/{company_id}/branches",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Branch",
    description="Create a new branch for the given company."
)
def add_branch(
    company_id: str,
    data: BranchCreateRequest,
    db: Session = Depends(get_db)
):
    try:
        return create_branch(db, company_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Branch creation failed: {str(e)}"
        )


@router.put(
    "/branches/{branch_id}",
    response_model=BranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Branch",
    description="Update details of an existing branch."
)
def edit_branch(
    branch_id: str,
    data: BranchUpdateRequest,
    db: Session = Depends(get_db)
):
    try:
        return update_branch(db, branch_id, data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Branch update failed: {str(e)}"
        )


@router.delete(
    "/branches/{branch_id}",
    status_code=status.HTTP_200_OK,
    summary="Disable Branch",
    description="Disable a branch instead of deleting it."
)
def soft_delete_branch(
    branch_id: str,
    db: Session = Depends(get_db)
):
    try:
        return disable_branch(db, branch_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Branch disable failed: {str(e)}"
        )

@router.post(
    "/companies/{company_id}/vendors",
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