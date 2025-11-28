"""
Schema definitions for UserBranchAssignment (UBA)
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

class UserBranchAssignmentCreateRequest(BaseModel):
    """Schema for creating a user-branch assignment"""

    uba_is_active: Optional[bool] = Field(True, description="Whether the assignment is active")

    class Config:
        from_attributes = True


class UserBranchAssignmentResponse(BaseModel):
    """Schema for returning UBA info"""

    uba_id: UUID = Field(..., description="Unique identifier of the assignment")
    uba_user_id: UUID = Field(..., description="ID of the user")
    uba_branch_id: UUID = Field(..., description="ID of the branch")
    uba_is_active: bool = Field(..., description="Whether the assignment is active")

    class Config:
        from_attributes = True
