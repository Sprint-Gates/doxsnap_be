"""
Business logic for company signup
"""

import logging
from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from fastapi import HTTPException, status
from secrets import token_urlsafe
from uuid import UUID

from app.models import User, Auth, RefreshToken, EmailVerification, Company, UserRole, Branch, Vendor
from app.company.schema import SignupRequest, BranchCreateRequest, BranchUpdateRequest, VendorCreateRequest, VendorUpdateRequest
from app.utils.auth_utils import (
    get_password_hash,
    validate_password_complexity,
    validate_email_format,
    create_access_token,
    create_refresh_token,
)
from app.utils.email_ver_utils import(
    send_verification_email,
    generate_verification_token
)

# Configure logger
logger = logging.getLogger(__name__)

# Service-specific constants
REFRESH_TOKEN_EXPIRE_DAYS = 7
ACTION_SIGNUP = "USER_SIGNUP"

# Signup flow

def signup_user_company(db: Session, data: SignupRequest, ip_address: str) -> JSONResponse:
    logger.info("Signup attempt", extra={"action": ACTION_SIGNUP, "email": data.user_email})

    # Existing user check
    if db.query(User).filter(User.user_email == data.user_email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Email format
    if not validate_email_format(data.user_email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Company name check
    if db.query(Company).filter(Company.company_name == data.company_name).first():
        raise HTTPException(status_code=409, detail="Company name already exists")

    # Password strength
    if not validate_password_complexity(data.user_password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain ≥8 characters, 1 uppercase letter, and 1 special character",
        )

    try:
        # Create Company
        company = Company(company_name=data.company_name)
        db.add(company)
        db.flush()

        # Create User
        user = User(
            user_email=data.user_email,
            user_name=data.user_name,
            user_company_id=company.company_id,
            user_role=UserRole.CLIENT_ADMIN,
            user_is_verified=False,
        )
        db.add(user)
        db.flush()

        # Auth record
        hashed_password = get_password_hash(data.user_password)
        db.add(Auth(auth_user_id=user.user_id, auth_password_hash=hashed_password))

        # Email verification
        verification_token = generate_verification_token()
        db.add(EmailVerification(
            emvr_user_id=user.user_id,
            emvr_token=verification_token,
            emvr_expires_at=datetime.utcnow() + timedelta(hours=24),
        ))

        send_verification_email(user.user_email, verification_token)

        # Tokens
        access_token = create_access_token({"sub": str(user.user_id)})
        refresh_token_str = create_refresh_token()

        db.add(RefreshToken(
            rftk_user_id=user.user_id,
            rftk_token=refresh_token_str,
            rftk_expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
            rftk_issued_from_ip=ip_address,
        ))

        db.commit()

    except Exception as exc:
        db.rollback()
        logger.error("Signup failed", extra={"error": str(exc), "action": ACTION_SIGNUP})
        raise HTTPException(status_code=500, detail="Signup failed")

    logger.info("User created successfully", extra={"action": ACTION_SIGNUP, "user_id": str(user.user_id)})

    response = JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": str(user.user_id),
            "is_verified": False,
            "message": "Signup successful. Please verify your email.",
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token_str,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )
    return response

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

    branch = Branch(
        branch_name=data.branch_name,
        branch_code=data.branch_code,
        branch_address_country=data.branch_address_country,
        branch_address_city=data.branch_address_city,
        branch_address_street=data.branch_address_street,
        branch_accounting_number=data.branch_accounting_number,
        branch_company_id=company_uuid,
        branch_is_active=True
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)
    # except Exception as exc:
    #     db.rollback()
    #     logger.error("Branch creation failed", extra={"error": str(exc), "company_id": company_id})
    #     raise HTTPException(status_code=500, detail="Branch creation failed")

    return JSONResponse(
        content={
            "branch_id": str(branch.branch_id),
            "branch_name": branch.branch_name,
            "branch_code": branch.branch_code,
            "branch_address_country": branch.branch_address_country,
            "branch_address_city": branch.branch_address_city,
            "branch_address_street": branch.branch_address_street,
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
            "branch_address_country": branch.branch_address_country,
            "branch_address_city": branch.branch_address_city,
            "branch_address_street": branch.branch_address_street,
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
        vendor_address_country=data.vendor_address_country,
        vendor_address_city=data.vendor_address_city,
        vendor_address_street=data.vendor_address_street,
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
            "vendor_address_country": vendor.vendor_address_country,
            "vendor_address_city": vendor.vendor_address_city,
            "vendor_address_street": vendor.vendor_address_street,
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
            "vendor_address_country": vendor.vendor_address_country,
            "vendor_address_city": vendor.vendor_address_city,
            "vendor_address_street": vendor.vendor_address_street,
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