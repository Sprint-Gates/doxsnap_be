"""
Schema definitions for authentication (login)
"""

from pydantic import BaseModel, EmailStr, Field

class LoginRequest(BaseModel):
    """ Schema for user login request """
    user_email: EmailStr = Field(..., description="User email address")
    user_password: str = Field(..., description="User password")

class Config:
    from_attributes = True

class LoginResponse(BaseModel):
    """ Schema for login response containing access and refresh tokens """
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field("bearer", description="Token type, usually 'bearer'")

class Config:
    from_attributes = True
