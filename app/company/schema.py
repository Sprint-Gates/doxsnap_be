"""
Schema definitions for Company (signup)
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

class SignupRequest(BaseModel):
    """Schema for comapny signup request"""

    user_email: str = Field(..., description="User email address")
    user_password: str = Field(..., min_length=8, description="User password, minimum 8 characters")
    user_name: str = Field(..., min_length=1, description="Username for the account")
    company_name: str = Field(..., min_length=2, description="Name for the company")
    class Config:
        from_attributes = True


class SignupResponse(BaseModel):
    """Schema for signup response containing tokens and user info"""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field("bearer", description="Token type, usually 'bearer'")
    user_id: str = Field(..., description="Unique identifier of the user")

    class Config:
        from_attributes = True

# Branch creation
class BranchCreateRequest(BaseModel):
    branch_name: str = Field(
        ...,
        min_length=2,
        description="Branch name as displayed to users"
    )
    branch_code: str = Field(
        ...,
        min_length=2,
        description="Unique short code for identifying the branch"
    )
    branch_address_country: Optional[str] = Field(
        None,
        description="Country UDC code or ID for the branch location"
    )
    branch_address_city: Optional[str] = Field(
        None,
        description="City UDC code or ID for the branch location"
    )
    branch_address_street: Optional[str] = Field(
        None,
        description="Street name or detailed address information"
    )
    branch_accounting_number: str = Field(
        ...,
        description="Accounting reference number for the branch used in financial postings"
    )


# Branch update
class BranchUpdateRequest(BaseModel):
    branch_name: Optional[str] = Field(
        None,
        description="Updated branch name"
    )
    branch_address_country: Optional[str] = Field(
        None,
        description="Updated Country UDC code or ID"
    )
    branch_address_city: Optional[str] = Field(
        None,
        description="Updated City UDC code or ID"
    )
    branch_address_street: Optional[str] = Field(
        None,
        description="Updated street or location text"
    )
    branch_accounting_number: Optional[str] = Field(
        None,
        description="Updated accounting reference number"
    )
    branch_is_active: Optional[bool] = Field(
        None,
        description="Enable or disable the branch instead of deleting it"
    )


# Branch response
class BranchResponse(BaseModel):
    branch_id: UUID = Field(
        ...,
        description="Unique identifier of the branch"
    )
    branch_name: str = Field(
        ...,
        description="Branch name as stored in the system"
    )
    branch_code: str = Field(
        ...,
        description="Unique short code identifying the branch"
    )
    branch_address_country: Optional[str] = Field(
        None,
        description="Country UDC name or code resolved from reference data"
    )
    branch_address_city: Optional[str] = Field(
        None,
        description="City UDC name or code resolved from reference data"
    )
    branch_address_street: Optional[str] = Field(
        None,
        description="Street name or detailed address text"
    )
    branch_accounting_number: Optional[str] = Field(
        None,
        description="Accounting reference number associated with the branch"
    )
    branch_is_active: bool = Field(
        ...,
        description="Indicates if the branch is active (True) or disabled (False)"
    )


# Vendor creation request
class VendorCreateRequest(BaseModel):
    vendor_name: str = Field(
        ...,
        min_length=2,
        description="Full name of the vendor"
    )
    vendor_accounting_number: str = Field(
        ...,
        description="Accounting reference number for the vendor"
    )
    vendor_code: str = Field(
        ...,
        min_length=2,
        description="Unique code to identify the vendor"
    )
    vendor_vat_number: Optional[str] = Field(
        None,
        description="VAT registration number for the vendor"
    )
    vendor_payable_account: Optional[bool] = Field(
        None,
        description="Payable account reference for financial transactions"
    )
    vendor_receivable_account: Optional[bool] = Field(
        None,
        description="Receivable account reference for financial transactions"
    )
    vendor_tax_rate: Optional[float] = Field(
        None,
        description="Applicable tax rate for this vendor"
    )
    vendor_address_country: Optional[str] = Field(
        None,
        description="Country where the vendor is located"
    )
    vendor_address_city: Optional[str] = Field(
        None,
        description="City where the vendor is located"
    )
    vendor_address_street: Optional[str] = Field(
        None,
        description="Street address or location of the vendor"
    )
    vendor_is_active: bool = Field(
        ...,
        description="Indicates if the vendor is active (True) or disabled (False)"
    )
    vendor_company_id: UUID = Field(
        ...,
        description="Company ID this vendor is associated with"
    )

    class Config:
        from_attributes = True


# Vendor update request
class VendorUpdateRequest(BaseModel):
    vendor_name: Optional[str] = Field(None, description="Updated vendor name")
    vendor_accounting_number: Optional[str] = Field(None, description="Updated accounting number")
    vendor_code: Optional[str] = Field(None, description="Updated unique code")
    vendor_vat_number: Optional[str] = Field(None, description="Updated VAT number")
    vendor_payable_account: Optional[bool] = Field(None, description="Updated payable account")
    vendor_receivable_account: Optional[bool] = Field(None, description="Updated receivable account")
    vendor_tax_rate: Optional[float] = Field(None, description="Updated tax rate")
    vendor_address_country: Optional[str] = Field(None, description="Updated country")
    vendor_address_city: Optional[str] = Field(None, description="Updated city")
    vendor_address_street: Optional[str] = Field(None, description="Updated street address")
    vendor_is_active: bool = Field(
        ...,
        description="Indicates if the vendor is active (True) or disabled (False)"
    )

    class Config:
        from_attributes = True

# Vendor response schema
class VendorResponse(BaseModel):
    vendor_id: UUID = Field(..., description="Unique identifier for the vendor")
    vendor_name: str = Field(..., description="Vendor name")
    vendor_accounting_number: str = Field(..., description="Accounting reference number")
    vendor_code: str = Field(..., description="Unique code identifying the vendor")
    vendor_vat_number: Optional[str] = Field(None, description="VAT registration number")
    vendor_payable_account: Optional[str] = Field(None, description="Payable account reference")
    vendor_receivable_account: Optional[str] = Field(None, description="Receivable account reference")
    vendor_tax_rate: Optional[float] = Field(None, description="Tax rate for this vendor")
    vendor_address_country: Optional[str] = Field(None, description="Country of the vendor")
    vendor_address_city: Optional[str] = Field(None, description="City of the vendor")
    vendor_address_street: Optional[str] = Field(None, description="Street address")
    vendor_is_active: bool = Field(
        ...,
        description="Indicates if the vendor is active (True) or disabled (False)"
    )
    vendor_company_id: UUID = Field(..., description="ID of the company this vendor belongs to")

    class Config:
        from_attributes = True