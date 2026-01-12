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
from app.models import HandHeldDevice, Technician, Company, AddressBook, handheld_device_technicians
from app.utils.security import create_access_token, verify_token
from app.utils.rate_limiter import limiter, RateLimits

router = APIRouter()


class HHDLoginRequest(BaseModel):
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
    Authenticate a handheld device with device code and PIN.

    The PIN should be set on the device record in the admin portal.
    Returns tokens for authenticated API access.
    """
    # Find device by code
    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.device_code == data.device_code,
        HandHeldDevice.is_active == True
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device code or PIN"
        )

    # Check if device has assigned employee (address_book) or legacy technician(s)
    has_employee = device.address_book_id is not None
    has_legacy_technician = device.assigned_technician is not None or len(device.assigned_technicians) > 0

    if not has_employee and not has_legacy_technician:
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

    # Get assigned employee (address_book) - this is the new approach
    assigned_employee = device.address_book if has_employee else None

    # Get primary technician (legacy support)
    primary_tech = None
    if not has_employee:
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
        technician_data = {
            "id": assigned_employee.id,
            "name": assigned_employee.name,
            "email": assigned_employee.email,
            "phone": assigned_employee.phone,
            "specialization": None  # AddressBook doesn't have specialization
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

    # Get assigned employee (new approach) or primary technician (legacy)
    assigned_employee = device.address_book if device.address_book_id else None
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
