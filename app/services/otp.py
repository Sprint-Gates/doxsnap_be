import random
import string
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import OTPCode
from app.services.email import EmailService
from app.services.mock_email import MockEmailService


class OTPService:
    def __init__(self):
        self.email_service = EmailService()
        self.mock_email_service = MockEmailService()
    
    def generate_otp(self, length: int = 6) -> str:
        """Generate a random OTP code"""
        return ''.join(random.choices(string.digits, k=length))
    
    def create_otp(self, db: Session, email: str, purpose: str = "email_verification") -> OTPCode:
        """Create a new OTP code for the given email"""
        
        # Invalidate any existing active OTP for this email and purpose
        self.invalidate_existing_otps(db, email, purpose)
        
        # Generate new OTP
        otp_code = self.generate_otp()
        expires_at = datetime.utcnow() + timedelta(minutes=10)  # 10 minutes expiry
        
        # Create OTP record
        db_otp = OTPCode(
            email=email,
            otp_code=otp_code,
            purpose=purpose,
            expires_at=expires_at,
            max_attempts=3
        )
        
        db.add(db_otp)
        db.commit()
        db.refresh(db_otp)
        
        return db_otp
    
    def invalidate_existing_otps(self, db: Session, email: str, purpose: str):
        """Invalidate existing active OTP codes for email and purpose"""
        db.query(OTPCode).filter(
            and_(
                OTPCode.email == email,
                OTPCode.purpose == purpose,
                OTPCode.is_verified == False
            )
        ).update({
            "is_verified": True,  # Mark as used to invalidate
            "used_at": datetime.utcnow()
        })
        db.commit()
    
    def verify_otp(self, db: Session, email: str, otp_code: str, purpose: str = "email_verification") -> dict:
        """Verify OTP code"""
        
        # Find the OTP record
        otp_record = db.query(OTPCode).filter(
            and_(
                OTPCode.email == email,
                OTPCode.purpose == purpose,
                OTPCode.is_verified == False
            )
        ).order_by(OTPCode.created_at.desc()).first()
        
        if not otp_record:
            return {
                "success": False,
                "message": "No active OTP found for this email",
                "error_code": "OTP_NOT_FOUND"
            }
        
        # Check if OTP has expired
        if datetime.utcnow() > otp_record.expires_at:
            return {
                "success": False,
                "message": "OTP has expired",
                "error_code": "OTP_EXPIRED"
            }
        
        # Check if max attempts reached
        if otp_record.attempts >= otp_record.max_attempts:
            return {
                "success": False,
                "message": "Maximum verification attempts exceeded",
                "error_code": "MAX_ATTEMPTS_REACHED"
            }
        
        # Increment attempts
        otp_record.attempts += 1
        
        # Verify the code
        if otp_record.otp_code != otp_code:
            db.commit()  # Save the incremented attempts
            
            remaining_attempts = otp_record.max_attempts - otp_record.attempts
            return {
                "success": False,
                "message": f"Invalid OTP code. {remaining_attempts} attempts remaining",
                "error_code": "INVALID_OTP",
                "remaining_attempts": remaining_attempts
            }
        
        # OTP is valid - mark as verified
        otp_record.is_verified = True
        otp_record.used_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "OTP verified successfully",
            "verified_at": otp_record.used_at
        }
    
    def send_otp_email(self, email: str, otp_code: str, purpose: str = "email_verification") -> bool:
        """Send OTP via email"""
        
        subject_map = {
            "email_verification": "Verify Your Email - CoreSRP",
            "password_reset": "Password Reset Code - CoreSRP",
            "login": "Login Verification Code - CoreSRP"
        }

        subject = subject_map.get(purpose, "Verification Code - CoreSRP")
        
        # Email content
        if purpose == "email_verification":
            message = f"""
            <h2>Email Verification</h2>
            <p>Your verification code is:</p>
            <div style="font-size: 32px; font-weight: bold; color: #4f46e5; text-align: center; padding: 20px; background: #f8fafc; border-radius: 8px; margin: 20px 0;">
                {otp_code}
            </div>
            <p>This code will expire in <strong>10 minutes</strong>.</p>
            <p>If you didn't request this verification, please ignore this email.</p>
            """
        elif purpose == "password_reset":
            message = f"""
            <h2>Password Reset</h2>
            <p>Your password reset code is:</p>
            <div style="font-size: 32px; font-weight: bold; color: #dc2626; text-align: center; padding: 20px; background: #fef2f2; border-radius: 8px; margin: 20px 0;">
                {otp_code}
            </div>
            <p>This code will expire in <strong>10 minutes</strong>.</p>
            <p>If you didn't request a password reset, please ignore this email.</p>
            """
        else:  # login
            message = f"""
            <h2>Login Verification</h2>
            <p>Your login verification code is:</p>
            <div style="font-size: 32px; font-weight: bold; color: #059669; text-align: center; padding: 20px; background: #f0fdf4; border-radius: 8px; margin: 20px 0;">
                {otp_code}
            </div>
            <p>This code will expire in <strong>10 minutes</strong>.</p>
            <p>If you didn't try to log in, please secure your account immediately.</p>
            """
        
        # Try real email service first, fallback to mock
        try:
            success = self.email_service.send_email(
                recipient_email=email,
                subject=subject,
                message=message
            )
            if success:
                return True
        except Exception as e:
            print(f"Real email service failed: {e}")
        
        # Fallback to mock email service
        try:
            return self.mock_email_service.send_email(
                recipient_email=email,
                subject=subject,
                message=message
            )
        except Exception as e:
            print(f"Mock email service failed: {e}")
            return False
    
    def cleanup_expired_otps(self, db: Session):
        """Clean up expired OTP codes (can be run periodically)"""
        expired_count = db.query(OTPCode).filter(
            OTPCode.expires_at < datetime.utcnow()
        ).delete()
        
        db.commit()
        return expired_count
    
    def get_otp_status(self, db: Session, email: str, purpose: str = "email_verification") -> Optional[dict]:
        """Get status of the latest OTP for email and purpose"""
        
        otp_record = db.query(OTPCode).filter(
            and_(
                OTPCode.email == email,
                OTPCode.purpose == purpose
            )
        ).order_by(OTPCode.created_at.desc()).first()
        
        if not otp_record:
            return None
        
        is_expired = datetime.utcnow() > otp_record.expires_at
        remaining_attempts = max(0, otp_record.max_attempts - otp_record.attempts)
        
        return {
            "email": email,
            "purpose": purpose,
            "is_verified": otp_record.is_verified,
            "is_expired": is_expired,
            "attempts": otp_record.attempts,
            "remaining_attempts": remaining_attempts,
            "created_at": otp_record.created_at,
            "expires_at": otp_record.expires_at,
            "used_at": otp_record.used_at
        }