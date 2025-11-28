"""
Business logic for branch services
"""

import logging
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from uuid import UUID

from app.models import Company, Branch
from app.branch.schema import BranchCreateRequest, BranchUpdateRequest
# Configure logger
logger = logging.getLogger(__name__)


def create_branch(db: Session, company_id: str, data: BranchCreateRequest) -> JSONResponse:
    """
    Create a new branch for a company.
    """
    try:
        # Convert string (with or without dashes) to UUID object
        company_uuid = UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id. Must be a valid UUID.")


    company = db.query(Company).filter(Company.company_id == company_uuid).first()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The company does not exist")
    
    # Check for duplicate branch code in the same company
    if db.query(Branch).filter(
        Branch.branch_company_id == company_uuid,
        Branch.branch_code == data.branch_code
    ).first():
        raise HTTPException(status_code=409, detail="Branch code already exists for this company")
    try:
        branch = Branch(
            branch_name=data.branch_name,
            branch_code=data.branch_code,
            branch_accounting_number=data.branch_accounting_number,
            branch_company_id=company_uuid,
            branch_is_active=True
        )
        db.add(branch)
        db.commit()
        db.refresh(branch)
    except Exception as exc:
        db.rollback()
        logger.error("Branch creation failed", extra={"error": str(exc), "company_id": company_id})
        raise HTTPException(status_code=500, detail="Branch creation failed")

    return JSONResponse(
        content={
            "branch_id": str(branch.branch_id),
            "branch_name": branch.branch_name,
            "branch_code": branch.branch_code,
            "branch_accounting_number": branch.branch_accounting_number,
            "branch_is_active": branch.branch_is_active,
            "message": "Branch created successfully"
        },
        status_code=201
    )

def update_branch(db: Session, branch_id: str, data: BranchUpdateRequest) -> JSONResponse:
    """
    Update details of an existing branch.
    Only provided fields in BranchUpdateRequest will be updated.
    """
    try:
        # Convert string (with or without dashes) to UUID object
        branch_uuid = UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id. Must be a valid UUID.")
    
    branch = db.query(Branch).filter(Branch.branch_id == branch_uuid).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    try:
        for field, value in data.dict(exclude_unset=True).items():
            setattr(branch, field, value)

        db.commit()
        db.refresh(branch)
    except Exception as exc:
        db.rollback()
        logger.error("Branch update failed", extra={"error": str(exc), "branch_id": branch_uuid})
        raise HTTPException(status_code=500, detail="Branch update failed")

    return JSONResponse(
        content={
            "branch_id": str(branch.branch_id),
            "branch_name": branch.branch_name,
            "branch_code": branch.branch_code,
            "branch_accounting_number": branch.branch_accounting_number,
            "branch_is_active": branch.branch_is_active,
            "message": "Branch updated successfully"
        }
    )


def disable_branch(db: Session, branch_id: str) -> JSONResponse:
    """
    Disable a branch (soft delete) by setting branch_is_active to False.
    """
    try:
        # Convert string (with or without dashes) to UUID object
        branch_uuid = UUID(branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid company_id. Must be a valid UUID.")
    
    branch = db.query(Branch).filter(Branch.branch_id == branch_uuid).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    if not branch.branch_is_active:
        return JSONResponse(
            content={"message": "Branch is already disabled"},
            status_code=200
        )

    try:
        branch.branch_is_active = False
        db.commit()
        db.refresh(branch)
    except Exception as exc:
        db.rollback()
        logger.error("Branch disable failed", extra={"error": str(exc), "branch_id": branch_uuid})
        raise HTTPException(status_code=500, detail="Failed to disable branch")

    return JSONResponse(
        content={
            "branch_id": str(branch.branch_id),
            "branch_name": branch.branch_name,
            "branch_is_active": branch.branch_is_active,
            "message": "Branch disabled successfully"
        },
        status_code=200
    )