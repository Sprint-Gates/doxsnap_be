"""
Schema definitions for Vendor
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

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
    vendor_is_active: Optional[bool] = Field(
        None,
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
    vendor_is_active: bool = Field(
        ...,
        description="Indicates if the vendor is active (True) or disabled (False)"
    )
    vendor_company_id: UUID = Field(..., description="ID of the company this vendor belongs to")

    class Config:
        from_attributes = True