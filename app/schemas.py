from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional, List


class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class UserCreate(UserBase):
    password: str
    name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class PasswordReset(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class User(UserBase):
    id: int
    is_active: bool
    is_admin: bool = False
    remaining_documents: int
    phone: Optional[str] = None
    role: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None


class ProcessedImageBase(BaseModel):
    original_filename: str
    processing_status: str


class ProcessedImageCreate(ProcessedImageBase):
    pass


class ProcessedImage(ProcessedImageBase):
    id: int
    user_id: int
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None
    ocr_extracted_words: int = 0
    ocr_average_confidence: float = 0.0
    ocr_preprocessing_methods: int = 1
    patterns_detected: int = 0
    has_structured_data: bool = False
    structured_data: Optional[str] = None
    extraction_confidence: float = 0.0
    processing_method: str = "basic"
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProcessedImageList(BaseModel):
    images: List[ProcessedImage]
    total: int
    page: int
    size: int


class OTPRequest(BaseModel):
    email: EmailStr
    purpose: Optional[str] = "email_verification"


class OTPVerification(BaseModel):
    email: EmailStr
    otp_code: str
    purpose: Optional[str] = "email_verification"


class OTPResponse(BaseModel):
    message: str
    expires_in_minutes: int
    max_attempts: int