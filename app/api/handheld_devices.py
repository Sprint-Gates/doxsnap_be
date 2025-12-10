from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from app.database import get_db
from app.models import User, Company, HandHeldDevice, Technician, handheld_device_technicians, Warehouse
from app.utils.security import verify_token
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """Get the current authenticated user"""
    token = credentials.credentials
    email = verify_token(token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


def require_admin(user: User = Depends(get_current_user)):
    """Require admin role"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


class HandHeldDeviceCreate(BaseModel):
    device_code: str
    device_name: Optional[str] = None
    device_model: Optional[str] = None
    serial_number: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None


class HandHeldDeviceUpdate(BaseModel):
    device_code: Optional[str] = None
    device_name: Optional[str] = None
    device_model: Optional[str] = None
    serial_number: Optional[str] = None
    os_version: Optional[str] = None
    app_version: Optional[str] = None
    warehouse_id: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class TechnicianAssignment(BaseModel):
    technician_id: Optional[int] = None  # None to unassign


class TechniciansAssignment(BaseModel):
    """Assignment of multiple technicians to a device"""
    technician_ids: List[int] = []  # List of technician IDs to assign
    primary_technician_id: Optional[int] = None  # Which one is the primary


def device_to_response(device: HandHeldDevice, db: Session) -> dict:
    """Convert HandHeldDevice model to response dict"""
    # Primary technician (legacy single assignment)
    technician_data = None
    if device.assigned_technician:
        technician_data = {
            "id": device.assigned_technician.id,
            "name": device.assigned_technician.name,
            "email": device.assigned_technician.email,
            "phone": device.assigned_technician.phone,
            "employee_id": device.assigned_technician.employee_id,
            "specialization": device.assigned_technician.specialization
        }

    # Warehouse data
    warehouse_data = None
    if device.warehouse:
        warehouse_data = {
            "id": device.warehouse.id,
            "name": device.warehouse.name,
            "code": device.warehouse.code
        }

    # All assigned technicians (many-to-many)
    assigned_technicians_data = []
    for tech in device.assigned_technicians:
        # Get assignment details from junction table
        assignment = db.execute(
            handheld_device_technicians.select().where(
                handheld_device_technicians.c.handheld_device_id == device.id,
                handheld_device_technicians.c.technician_id == tech.id
            )
        ).first()

        assigned_technicians_data.append({
            "id": tech.id,
            "name": tech.name,
            "email": tech.email,
            "phone": tech.phone,
            "employee_id": tech.employee_id,
            "specialization": tech.specialization,
            "is_primary": assignment.is_primary if assignment else False,
            "assigned_at": assignment.assigned_at.isoformat() if assignment and assignment.assigned_at else None
        })

    return {
        "id": device.id,
        "device_code": device.device_code,
        "device_name": device.device_name,
        "device_model": device.device_model,
        "serial_number": device.serial_number,
        "os_version": device.os_version,
        "app_version": device.app_version,
        "last_sync_at": device.last_sync_at.isoformat() if device.last_sync_at else None,
        "warehouse_id": device.warehouse_id,
        "warehouse": warehouse_data,
        "assigned_technician_id": device.assigned_technician_id,
        "assigned_technician": technician_data,
        "assigned_technicians": assigned_technicians_data,
        "assigned_at": device.assigned_at.isoformat() if device.assigned_at else None,
        "status": device.status,
        "notes": device.notes,
        "is_active": device.is_active,
        "created_at": device.created_at.isoformat(),
        "updated_at": device.updated_at.isoformat() if device.updated_at else None
    }


@router.get("/handheld-devices/")
async def get_handheld_devices(
    include_inactive: bool = False,
    search: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all handheld devices for the current company"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    query = db.query(HandHeldDevice).filter(HandHeldDevice.company_id == user.company_id)

    if not include_inactive:
        query = query.filter(HandHeldDevice.is_active == True)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (HandHeldDevice.device_code.ilike(search_term)) |
            (HandHeldDevice.device_name.ilike(search_term)) |
            (HandHeldDevice.serial_number.ilike(search_term))
        )

    if status:
        query = query.filter(HandHeldDevice.status == status)

    devices = query.order_by(HandHeldDevice.device_code).all()

    return [device_to_response(device, db) for device in devices]


@router.get("/handheld-devices/available-technicians")
async def get_available_technicians(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get technicians that are not assigned to any device"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Get all active technicians
    all_technicians = db.query(Technician).filter(
        Technician.company_id == user.company_id,
        Technician.is_active == True
    ).all()

    # Get technicians already assigned to a device
    assigned_ids = db.query(HandHeldDevice.assigned_technician_id).filter(
        HandHeldDevice.company_id == user.company_id,
        HandHeldDevice.assigned_technician_id.isnot(None),
        HandHeldDevice.is_active == True
    ).all()
    assigned_ids = {t[0] for t in assigned_ids}

    # Return unassigned technicians
    available = [t for t in all_technicians if t.id not in assigned_ids]

    return [{
        "id": t.id,
        "name": t.name,
        "email": t.email,
        "phone": t.phone,
        "employee_id": t.employee_id,
        "specialization": t.specialization
    } for t in available]


@router.get("/handheld-devices/{device_id}")
async def get_handheld_device(
    device_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific handheld device"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    return device_to_response(device, db)


@router.post("/handheld-devices/")
async def create_handheld_device(
    data: HandHeldDeviceCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new handheld device (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    # Check if device_code already exists within the company
    existing = db.query(HandHeldDevice).filter(
        HandHeldDevice.company_id == user.company_id,
        HandHeldDevice.device_code == data.device_code
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device code already exists"
        )

    try:
        # Validate warehouse if provided
        if data.warehouse_id:
            warehouse = db.query(Warehouse).filter(
                Warehouse.id == data.warehouse_id,
                Warehouse.company_id == user.company_id,
                Warehouse.is_active == True
            ).first()
            if not warehouse:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Warehouse not found"
                )

        device = HandHeldDevice(
            company_id=user.company_id,
            device_code=data.device_code,
            device_name=data.device_name,
            device_model=data.device_model,
            serial_number=data.serial_number,
            os_version=data.os_version,
            app_version=data.app_version,
            warehouse_id=data.warehouse_id,
            notes=data.notes,
            status="available"
        )

        db.add(device)
        db.commit()
        db.refresh(device)

        logger.info(f"HandHeldDevice '{device.device_code}' created by '{user.email}'")

        return device_to_response(device, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating handheld device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating device: {str(e)}"
        )


@router.put("/handheld-devices/{device_id}")
async def update_handheld_device(
    device_id: int,
    data: HandHeldDeviceUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a handheld device (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    # Check if device_code already exists for another device
    if data.device_code:
        existing = db.query(HandHeldDevice).filter(
            HandHeldDevice.company_id == user.company_id,
            HandHeldDevice.device_code == data.device_code,
            HandHeldDevice.id != device_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device code already exists"
            )

    # Validate warehouse if provided
    if data.warehouse_id is not None:
        if data.warehouse_id:  # Not zero/null - validate it exists
            warehouse = db.query(Warehouse).filter(
                Warehouse.id == data.warehouse_id,
                Warehouse.company_id == user.company_id,
                Warehouse.is_active == True
            ).first()
            if not warehouse:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Warehouse not found"
                )

    try:
        update_data = data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(device, field, value)

        db.commit()
        db.refresh(device)

        logger.info(f"HandHeldDevice '{device.device_code}' updated by '{user.email}'")

        return device_to_response(device, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating handheld device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating device: {str(e)}"
        )


@router.delete("/handheld-devices/{device_id}")
async def delete_handheld_device(
    device_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deactivate a handheld device (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    try:
        device.is_active = False
        device.status = "retired"
        # Unassign technician when retiring device
        device.assigned_technician_id = None
        device.assigned_at = None
        db.commit()

        logger.info(f"HandHeldDevice '{device.device_code}' deactivated by '{user.email}'")

        return {
            "success": True,
            "message": f"Device '{device.device_code}' has been deactivated"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error deactivating handheld device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deactivating device: {str(e)}"
        )


@router.patch("/handheld-devices/{device_id}/assign")
async def assign_technician_to_device(
    device_id: int,
    data: TechnicianAssignment,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Assign or unassign a technician to a handheld device (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    try:
        if data.technician_id is None:
            # Unassign technician
            old_technician_name = device.assigned_technician.name if device.assigned_technician else None
            device.assigned_technician_id = None
            device.assigned_at = None
            device.status = "available"
            db.commit()
            db.refresh(device)

            if old_technician_name:
                logger.info(f"Technician '{old_technician_name}' unassigned from device '{device.device_code}' by '{user.email}'")

            return device_to_response(device, db)
        else:
            # Verify technician exists and belongs to same company
            technician = db.query(Technician).filter(
                Technician.id == data.technician_id,
                Technician.company_id == user.company_id,
                Technician.is_active == True
            ).first()

            if not technician:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Technician not found"
                )

            # Check if technician is already assigned to another device
            existing_assignment = db.query(HandHeldDevice).filter(
                HandHeldDevice.company_id == user.company_id,
                HandHeldDevice.assigned_technician_id == data.technician_id,
                HandHeldDevice.id != device_id,
                HandHeldDevice.is_active == True
            ).first()

            if existing_assignment:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Technician is already assigned to device '{existing_assignment.device_code}'"
                )

            # Assign technician
            device.assigned_technician_id = data.technician_id
            device.assigned_at = datetime.utcnow()
            device.status = "assigned"
            db.commit()
            db.refresh(device)

            logger.info(f"Technician '{technician.name}' assigned to device '{device.device_code}' by '{user.email}'")

            return device_to_response(device, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error assigning technician to device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assigning technician: {str(e)}"
        )


@router.patch("/handheld-devices/{device_id}/assign-technicians")
async def assign_technicians_to_device(
    device_id: int,
    data: TechniciansAssignment,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Assign multiple technicians to a handheld device (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    try:
        # Verify all technicians exist and belong to the same company
        technicians = []
        if data.technician_ids:
            technicians = db.query(Technician).filter(
                Technician.id.in_(data.technician_ids),
                Technician.company_id == user.company_id,
                Technician.is_active == True
            ).all()

            if len(technicians) != len(data.technician_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more technicians not found"
                )

        # Clear existing assignments
        db.execute(
            handheld_device_technicians.delete().where(
                handheld_device_technicians.c.handheld_device_id == device_id
            )
        )

        # Add new assignments
        for tech in technicians:
            is_primary = (data.primary_technician_id == tech.id) if data.primary_technician_id else (tech == technicians[0] if technicians else False)
            db.execute(
                handheld_device_technicians.insert().values(
                    handheld_device_id=device_id,
                    technician_id=tech.id,
                    assigned_at=datetime.utcnow(),
                    is_primary=is_primary
                )
            )

        # Update device status
        if technicians:
            device.status = "assigned"
            # Set the primary technician as the legacy assigned_technician_id
            primary_id = data.primary_technician_id if data.primary_technician_id in data.technician_ids else technicians[0].id
            device.assigned_technician_id = primary_id
            device.assigned_at = datetime.utcnow()
        else:
            device.status = "available"
            device.assigned_technician_id = None
            device.assigned_at = None

        db.commit()
        db.refresh(device)

        tech_names = [t.name for t in technicians]
        logger.info(f"Technicians {tech_names} assigned to device '{device.device_code}' by '{user.email}'")

        return device_to_response(device, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error assigning technicians to device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error assigning technicians: {str(e)}"
        )


@router.post("/handheld-devices/{device_id}/add-technician")
async def add_technician_to_device(
    device_id: int,
    data: TechnicianAssignment,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Add a single technician to a device without removing existing ones (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    if not data.technician_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Technician ID is required"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    # Verify technician exists
    technician = db.query(Technician).filter(
        Technician.id == data.technician_id,
        Technician.company_id == user.company_id,
        Technician.is_active == True
    ).first()

    if not technician:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technician not found"
        )

    try:
        # Check if already assigned
        existing = db.execute(
            handheld_device_technicians.select().where(
                handheld_device_technicians.c.handheld_device_id == device_id,
                handheld_device_technicians.c.technician_id == data.technician_id
            )
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Technician is already assigned to this device"
            )

        # Check if this is the first technician (make them primary)
        is_first = len(device.assigned_technicians) == 0

        # Add technician
        db.execute(
            handheld_device_technicians.insert().values(
                handheld_device_id=device_id,
                technician_id=data.technician_id,
                assigned_at=datetime.utcnow(),
                is_primary=is_first
            )
        )

        # Update device status
        device.status = "assigned"
        if is_first:
            device.assigned_technician_id = data.technician_id
            device.assigned_at = datetime.utcnow()

        db.commit()
        db.refresh(device)

        logger.info(f"Technician '{technician.name}' added to device '{device.device_code}' by '{user.email}'")

        return device_to_response(device, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error adding technician to device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding technician: {str(e)}"
        )


@router.delete("/handheld-devices/{device_id}/remove-technician/{technician_id}")
async def remove_technician_from_device(
    device_id: int,
    technician_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Remove a single technician from a device (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    try:
        # Check if assigned
        existing = db.execute(
            handheld_device_technicians.select().where(
                handheld_device_technicians.c.handheld_device_id == device_id,
                handheld_device_technicians.c.technician_id == technician_id
            )
        ).first()

        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Technician is not assigned to this device"
            )

        was_primary = existing.is_primary

        # Remove the assignment
        db.execute(
            handheld_device_technicians.delete().where(
                handheld_device_technicians.c.handheld_device_id == device_id,
                handheld_device_technicians.c.technician_id == technician_id
            )
        )

        # Check remaining technicians
        remaining = db.execute(
            handheld_device_technicians.select().where(
                handheld_device_technicians.c.handheld_device_id == device_id
            )
        ).fetchall()

        if not remaining:
            # No more technicians - set device to available
            device.status = "available"
            device.assigned_technician_id = None
            device.assigned_at = None
        elif was_primary and remaining:
            # Assign a new primary
            new_primary = remaining[0]
            db.execute(
                handheld_device_technicians.update().where(
                    handheld_device_technicians.c.handheld_device_id == device_id,
                    handheld_device_technicians.c.technician_id == new_primary.technician_id
                ).values(is_primary=True)
            )
            device.assigned_technician_id = new_primary.technician_id

        db.commit()
        db.refresh(device)

        technician = db.query(Technician).filter(Technician.id == technician_id).first()
        tech_name = technician.name if technician else f"ID {technician_id}"
        logger.info(f"Technician '{tech_name}' removed from device '{device.device_code}' by '{user.email}'")

        return device_to_response(device, db)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing technician from device: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error removing technician: {str(e)}"
        )


@router.patch("/handheld-devices/{device_id}/toggle-status")
async def toggle_device_status(
    device_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Toggle handheld device active status (admin only)"""
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No company associated with this user"
        )

    device = db.query(HandHeldDevice).filter(
        HandHeldDevice.id == device_id,
        HandHeldDevice.company_id == user.company_id
    ).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found"
        )

    try:
        device.is_active = not device.is_active
        if not device.is_active:
            device.status = "retired"
            # Unassign technician when deactivating
            device.assigned_technician_id = None
            device.assigned_at = None
        else:
            device.status = "available"

        db.commit()
        db.refresh(device)

        status_text = "activated" if device.is_active else "deactivated"
        logger.info(f"HandHeldDevice '{device.device_code}' {status_text} by '{user.email}'")

        return device_to_response(device, db)

    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling device status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling device status: {str(e)}"
        )
