"""
Schema definitions for user signup
"""

from pydantic import BaseModel, Field

class SignupCompanyRequest(BaseModel):
    """Schema for user signup company request"""
    user_email: str = Field(..., description="User email address")
    user_password: str = Field(..., min_length=8, description="User password, minimum 8 characters")
    company_name: str = Field(..., min_length=2, description="Name of the company to create")

    class Config:
        from_attributes = True


class SignupCompanyResponse(BaseModel):
    """Schema for signup response containing access and refresh tokens"""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field("Bearer", description="Token type, usually 'Bearer'")

    class Config:
        from_attributes = True
