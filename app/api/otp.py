from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import os

from app.database import get_db
from app.schemas import OTPRequest, OTPVerification, OTPResponse
from app.services.otp import OTPService

router = APIRouter()
otp_service = OTPService()


@router.post("/send", response_model=OTPResponse)
async def send_otp(
    otp_request: OTPRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """Send OTP code to email"""
    
    # Add cache control headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    try:
        # Create OTP record
        otp_record = otp_service.create_otp(
            db=db,
            email=otp_request.email,
            purpose=otp_request.purpose
        )
        
        # Send OTP via email
        email_sent = otp_service.send_otp_email(
            email=otp_request.email,
            otp_code=otp_record.otp_code,
            purpose=otp_request.purpose
        )
        
        if not email_sent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send OTP email"
            )
        
        return OTPResponse(
            message=f"OTP sent to {otp_request.email}",
            expires_in_minutes=10,
            max_attempts=3
        )
        
    except Exception as e:
        print(f"Error sending OTP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP"
        )


@router.post("/verify")
async def verify_otp(
    otp_verification: OTPVerification,
    response: Response,
    db: Session = Depends(get_db)
):
    """Verify OTP code"""
    
    # Add cache control headers
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    try:
        result = otp_service.verify_otp(
            db=db,
            email=otp_verification.email,
            otp_code=otp_verification.otp_code,
            purpose=otp_verification.purpose
        )
        
        if not result["success"]:
            # Map error codes to appropriate HTTP status codes
            status_code_map = {
                "OTP_NOT_FOUND": status.HTTP_404_NOT_FOUND,
                "OTP_EXPIRED": status.HTTP_410_GONE,
                "MAX_ATTEMPTS_REACHED": status.HTTP_429_TOO_MANY_REQUESTS,
                "INVALID_OTP": status.HTTP_400_BAD_REQUEST
            }
            
            status_code = status_code_map.get(
                result.get("error_code"),
                status.HTTP_400_BAD_REQUEST
            )
            
            raise HTTPException(
                status_code=status_code,
                detail=result["message"]
            )
        
        return {
            "message": result["message"],
            "verified": True,
            "verified_at": result["verified_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error verifying OTP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify OTP"
        )


@router.get("/status/{email}")
async def get_otp_status(
    email: str,
    purpose: str = "email_verification",
    response: Response = None,
    db: Session = Depends(get_db)
):
    """Get OTP status for email"""
    
    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    try:
        status_info = otp_service.get_otp_status(
            db=db,
            email=email,
            purpose=purpose
        )
        
        if not status_info:
            return {
                "email": email,
                "purpose": purpose,
                "has_active_otp": False,
                "message": "No OTP found for this email"
            }
        
        return {
            "email": status_info["email"],
            "purpose": status_info["purpose"],
            "has_active_otp": True,
            "is_verified": status_info["is_verified"],
            "is_expired": status_info["is_expired"],
            "attempts": status_info["attempts"],
            "remaining_attempts": status_info["remaining_attempts"],
            "created_at": status_info["created_at"],
            "expires_at": status_info["expires_at"]
        }
        
    except Exception as e:
        print(f"Error getting OTP status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get OTP status"
        )


@router.post("/resend")
async def resend_otp(
    otp_request: OTPRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """Resend OTP code (invalidates previous OTP)"""
    
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    # This is the same as send_otp since create_otp invalidates existing OTPs
    return await send_otp(otp_request, response, db)


@router.get("/verify-page", response_class=HTMLResponse)
async def otp_verification_page():
    """Serve the OTP verification HTML page"""
    template_path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "otp_verification.html")
    
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OTP verification template not found"
        )


@router.delete("/cleanup")
async def cleanup_expired_otps(
    response: Response,
    db: Session = Depends(get_db)
):
    """Clean up expired OTP codes (admin endpoint)"""
    
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    try:
        deleted_count = otp_service.cleanup_expired_otps(db)
        
        return {
            "message": f"Cleaned up {deleted_count} expired OTP codes",
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        print(f"Error cleaning up OTPs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup expired OTPs"
        )