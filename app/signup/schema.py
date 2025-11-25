"""
Schema definitions for authentication (signup)
"""

from pydantic import BaseModel, EmailStr, Field

class SignupRequest(BaseModel):
    """Schema for user signup request"""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password, minimum 8 characters")
    user_name: str = Field(..., min_length=1, description="Username for the account")
    user_avatar: str = Field(None, description="URL or path to user avatar")

    class Config:
        from_attributes = True


class SignupResponse(BaseModel):
    """Schema for signup response containing tokens and user info"""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field("bearer", description="Token type, usually 'bearer'")
    user_id: str = Field(..., description="Unique identifier of the user")
    is_verified: bool = Field(..., description="Indicates if the user email is verified")

    class Config:
        from_attributes = True

