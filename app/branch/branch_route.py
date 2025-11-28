from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.branch.schema import BranchResponse, BranchUpdateRequest, BranchCreateRequest
from app.branch.services import create_branch, disable_branch, update_branch
router = APIRouter(
prefix="/api",
tags=["Branch"]
)
    
@router.post(
    "{company_id}/branches",
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