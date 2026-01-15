"""
HHD (Hand Held Device) Authentication API for mobile app
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
import secrets
import hashlib

from app.database import get_db
from app.models import HandHeldDevice, Technician, Company, AddressBook, handheld_device_technicians, handheld_device_technicians_ab
from app.utils.security import create_access_token, verify_token
from app.utils.rate_limiter import limiter, RateLimits

router = APIRouter()


class HHDLoginRequest(BaseModel):
    company_code: str  # Company code to identify the company
    device_code: str
    pin: str  # 4-6 digit PIN


class HHDLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    device: dict
    technician: Optional[dict] = None


class HHDTokenRefreshRequest(BaseModel):
    refresh_token: str


# Store HHD refresh tokens (in production, use Redis or database)
hhd_refresh_tokens = {}


def generate_hhd_refresh_token(device_id: int) -> str:
    """Generate a refresh token for HHD"""
    token = secrets.token_urlsafe(32)
    # Store with expiry (7 days)
    hhd_refresh_tokens[token] = {
        "device_id": device_id,
        "expires_at": datetime.utcnow() + timedelta(days=7)
    }
    return token


def verify_hhd_refresh_token(token: str) -> Optional[int]:
    """Verify HHD refresh token and return device_id"""
    data = hhd_refresh_tokens.get(token)
    if not data:
        return None
    if datetime.utcnow() > data["expires_at"]:
        del hhd_refresh_tokens[token]
        return None
    return data["device_id"]


def hash_pin(pin: str, salt: str) -> str:
    """Hash PIN with salt"""
    return hashlib.sha256(f"{pin}{salt}".encode()).hexdigest()


@router.post("/hhd/login", response_model=HHDLoginResponse)
@limiter.limit(RateLimits.HHD_LOGIN)
async def hhd_login(
    request: Request,
    data: HHDLoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate a handheld device with company code, device code and PIN.

    The PIN should be set on the device record in the admin portal.
    Returns tokens for authenticated API access.
    """
    # First, find the company by company_code
    company = db.query(Company).filter(
        Company.company_code == data.company_code.upper(),
        Company.is_active == True
    ).first()

    if not company:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid company code"
        )

    # Find device by code within the company
    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.device_code == data.device_code,
        HandHeldDevice.company_id == company.id,
        HandHeldDevice.is_active == True
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device code or PIN"
        )

    # Check for employee assignment via many-to-many table (handheld_device_technicians_ab)
    employee_assignments = db.execute(
        handheld_device_technicians_ab.select().where(
            handheld_device_technicians_ab.c.handheld_device_id == device.id
        )
    ).fetchall()

    # Check if device has assigned employee (via m2m or direct) or legacy technician(s)
    has_employee_m2m = len(employee_assignments) > 0
    has_employee_direct = device.address_book_id is not None
    has_legacy_technician = device.assigned_technician is not None or len(device.assigned_technicians) > 0

    if not has_employee_m2m and not has_employee_direct and not has_legacy_technician:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device has no assigned employee"
        )

    # Check if device has a PIN configured
    if not device.mobile_pin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device PIN not configured. Contact administrator."
        )

    # Validate PIN
    if data.pin != device.mobile_pin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device code or PIN"
        )

    # Get assigned employee - prefer many-to-many, then direct, then legacy
    assigned_employee = None

    # First try: employee from many-to-many table (new approach)
    if has_employee_m2m:
        # Find primary employee or take first one
        primary_assignment = None
        for assignment in employee_assignments:
            if assignment.is_primary:
                primary_assignment = assignment
                break
        if not primary_assignment:
            primary_assignment = employee_assignments[0]

        assigned_employee = db.query(AddressBook).filter(
            AddressBook.id == primary_assignment.address_book_id
        ).first()

    # Second try: direct address_book_id on device
    elif has_employee_direct:
        assigned_employee = device.address_book

    # Get primary technician (legacy support)
    primary_tech = None
    if not assigned_employee:
        primary_tech = device.assigned_technician
        if not primary_tech and device.assigned_technicians:
            # Find primary from many-to-many
            for tech in device.assigned_technicians:
                assignment = db.execute(
                    handheld_device_technicians.select().where(
                        handheld_device_technicians.c.handheld_device_id == device.id,
                        handheld_device_technicians.c.technician_id == tech.id
                    )
                ).first()
                if assignment and assignment.is_primary:
                    primary_tech = tech
                    break
            if not primary_tech:
                primary_tech = device.assigned_technicians[0]

    # Create access token with HHD-specific claims
    token_data = {
        "sub": f"hhd:{device.id}",
        "device_id": device.id,
        "company_id": device.company_id,
        "technician_id": primary_tech.id if primary_tech else None,
        "employee_id": assigned_employee.id if assigned_employee else None,
        "type": "hhd"
    }

    expires_in = 3600  # 1 hour for mobile
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(seconds=expires_in)
    )
    refresh_token = generate_hhd_refresh_token(device.id)

    # Update last sync time
    device.last_sync_at = datetime.utcnow()
    db.commit()

    # Build response
    device_data = {
        "id": device.id,
        "device_code": device.device_code,
        "device_name": device.device_name,
        "company_id": device.company_id,
        "warehouse_id": device.warehouse_id
    }

    # Build technician data - use assigned_employee if available, otherwise legacy technician
    technician_data = None
    if assigned_employee:
        # New approach: employee from address_book
        # AddressBook uses alpha_name, phone_primary, and has specialization for employees
        technician_data = {
            "id": assigned_employee.id,
            "name": assigned_employee.alpha_name,
            "email": assigned_employee.email,
            "phone": assigned_employee.phone_primary,
            "specialization": assigned_employee.specialization
        }
    elif primary_tech:
        # Legacy approach: technician
        technician_data = {
            "id": primary_tech.id,
            "name": primary_tech.name,
            "email": primary_tech.email,
            "phone": primary_tech.phone,
            "specialization": primary_tech.specialization
        }

    return HHDLoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        device=device_data,
        technician=technician_data
    )


@router.post("/hhd/refresh")
@limiter.limit(RateLimits.HHD_REFRESH)
async def hhd_refresh_token(
    request: Request,
    data: HHDTokenRefreshRequest,
    db: Session = Depends(get_db)
):
    """Refresh HHD access token"""
    device_id = verify_hhd_refresh_token(data.refresh_token)

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.is_active == True
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device not found or inactive"
        )

    # Get assigned employee - check many-to-many first, then direct, then legacy
    assigned_employee = None

    # Check many-to-many employee assignments
    employee_assignments = db.execute(
        handheld_device_technicians_ab.select().where(
            handheld_device_technicians_ab.c.handheld_device_id == device.id
        )
    ).fetchall()

    if employee_assignments:
        # Find primary or take first
        primary_assignment = None
        for assignment in employee_assignments:
            if assignment.is_primary:
                primary_assignment = assignment
                break
        if not primary_assignment:
            primary_assignment = employee_assignments[0]

        assigned_employee = db.query(AddressBook).filter(
            AddressBook.id == primary_assignment.address_book_id
        ).first()
    elif device.address_book_id:
        assigned_employee = device.address_book

    # Legacy technician support
    primary_tech = None
    if not assigned_employee:
        primary_tech = device.assigned_technician
        if not primary_tech and device.assigned_technicians:
            primary_tech = device.assigned_technicians[0]

    # Create new access token
    token_data = {
        "sub": f"hhd:{device.id}",
        "device_id": device.id,
        "company_id": device.company_id,
        "technician_id": primary_tech.id if primary_tech else None,
        "employee_id": assigned_employee.id if assigned_employee else None,
        "type": "hhd"
    }

    expires_in = 3600
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(seconds=expires_in)
    )

    # Rotate refresh token
    del hhd_refresh_tokens[data.refresh_token]
    new_refresh_token = generate_hhd_refresh_token(device.id)

    device.last_sync_at = datetime.utcnow()
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in
    }


@router.post("/hhd/logout")
async def hhd_logout(
    data: HHDTokenRefreshRequest,
    db: Session = Depends(get_db)
):
    """Logout HHD and revoke refresh token"""
    if data.refresh_token in hhd_refresh_tokens:
        del hhd_refresh_tokens[data.refresh_token]

    return {"success": True, "message": "Logged out successfully"}


class FCMTokenRequest(BaseModel):
    fcm_token: str


def get_device_id_from_token(request: Request) -> Optional[int]:
    """Extract device_id from HHD JWT token"""
    from jose import jwt, JWTError
    from app.config import settings

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ")[1]

    try:
        # Decode the full payload to get device_id claim
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

        # Check if this is an HHD token
        token_type = payload.get("type")
        if token_type != "hhd":
            return None

        # Get device_id from the payload
        device_id = payload.get("device_id")
        if device_id:
            return int(device_id)

        # Fallback: extract from sub claim (format: "hhd:{device_id}")
        sub = payload.get("sub", "")
        if sub.startswith("hhd:"):
            return int(sub.split(":")[1])

        return None
    except (JWTError, ValueError, IndexError):
        return None


@router.post("/hhd/fcm-token")
async def register_fcm_token(
    request: Request,
    data: FCMTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Register FCM token for push notifications.
    Must be called with valid HHD authentication.
    """
    device_id = get_device_id_from_token(request)

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing HHD token"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.is_active == True
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    # Update FCM token
    device.fcm_token = data.fcm_token
    device.fcm_token_updated_at = datetime.utcnow()
    db.commit()

    return {"success": True, "message": "FCM token registered successfully"}


@router.delete("/hhd/fcm-token")
async def unregister_fcm_token(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Remove FCM token (e.g., on logout).
    Must be called with valid HHD authentication.
    """
    device_id = get_device_id_from_token(request)

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing HHD token"
        )

    device = db.query(HandHeldDevice).filter(HandHeldDevice.id == device_id).first()

    if device:
        device.fcm_token = None
        device.fcm_token_updated_at = datetime.utcnow()
        db.commit()

    return {"success": True, "message": "FCM token removed"}


class TestNotificationRequest(BaseModel):
    title: str = "Test Notification"
    body: str = "This is a test push notification"
    notification_type: str = "test"  # work_order_assignment, stock_transfer, or test


@router.post("/hhd/test-notification")
async def send_test_notification(
    request: Request,
    data: TestNotificationRequest,
    db: Session = Depends(get_db)
):
    """
    Send a test push notification to the authenticated HHD device.
    Useful for testing FCM integration.
    """
    device_id = get_device_id_from_token(request)

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing HHD token"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.is_active == True
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    if not device.fcm_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No FCM token registered for this device. Make sure push notifications are enabled."
        )

    try:
        from app.services.push_notification import PushNotificationService

        success = PushNotificationService.send_notification(
            fcm_token=device.fcm_token,
            title=data.title,
            body=data.body,
            notification_type=data.notification_type
        )

        if success:
            return {"success": True, "message": "Test notification sent successfully"}
        else:
            return {"success": False, "message": "Failed to send notification. Check server logs."}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sending notification: {str(e)}"
        )
