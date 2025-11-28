"""
Schema definitions for Branch
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

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
    branch_accounting_number: Optional[str] = Field(
        None,
        description="Accounting reference number associated with the branch"
    )
    branch_is_active: bool = Field(
        ...,
        description="Indicates if the branch is active (True) or disabled (False)"
    )