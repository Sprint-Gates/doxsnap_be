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