from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import date
from app.database import get_db
from app.models import User, Branch, Client, Floor, Room, Equipment, SubEquipment
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


# ============================================================================
# Pydantic Schemas
# ============================================================================

class FloorCreate(BaseModel):
    branch_id: int
    name: str
    code: Optional[str] = None
    level: Optional[int] = 0
    description: Optional[str] = None
    notes: Optional[str] = None


class FloorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    level: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class RoomCreate(BaseModel):
    floor_id: int
    name: str
    code: Optional[str] = None
    room_type: Optional[str] = None
    area_sqm: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    room_type: Optional[str] = None
    area_sqm: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class EquipmentCreate(BaseModel):
    room_id: int
    name: str
    code: Optional[str] = None
    category: str  # electrical, mechanical, plumbing
    equipment_type: Optional[str] = None
    pm_asset_type_id: Optional[int] = None  # Link to PM checklist hierarchy
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    status: Optional[str] = "operational"
    condition: Optional[str] = "good"
    specifications: Optional[str] = None
    location_details: Optional[str] = None
    photo_url: Optional[str] = None
    qr_code: Optional[str] = None
    notes: Optional[str] = None


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[str] = None
    equipment_type: Optional[str] = None
    pm_asset_type_id: Optional[int] = None  # Link to PM checklist hierarchy
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    status: Optional[str] = None
    condition: Optional[str] = None
    specifications: Optional[str] = None
    location_details: Optional[str] = None
    photo_url: Optional[str] = None
    qr_code: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SubEquipmentCreate(BaseModel):
    equipment_id: int
    name: str
    code: Optional[str] = None
    component_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    status: Optional[str] = "operational"
    condition: Optional[str] = "good"
    specifications: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class SubEquipmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    component_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_expiry: Optional[date] = None
    status: Optional[str] = None
    condition: Optional[str] = None
    specifications: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ============================================================================
# Helper Functions
# ============================================================================

def verify_branch_access(branch_id: int, user: User, db: Session) -> Branch:
    """Verify user has access to the branch"""
    branch = db.query(Branch).join(Client).filter(
        Branch.id == branch_id,
        Client.company_id == user.company_id
    ).first()

    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Branch not found"
        )

    return branch


def sub_equipment_to_response(sub: SubEquipment) -> dict:
    return {
        "id": sub.id,
        "equipment_id": sub.equipment_id,
        "name": sub.name,
        "code": sub.code,
        "component_type": sub.component_type,
        "manufacturer": sub.manufacturer,
        "model": sub.model,
        "serial_number": sub.serial_number,
        "installation_date": sub.installation_date.isoformat() if sub.installation_date else None,
        "warranty_expiry": sub.warranty_expiry.isoformat() if sub.warranty_expiry else None,
        "status": sub.status,
        "condition": sub.condition,
        "specifications": sub.specifications,
        "photo_url": sub.photo_url,
        "notes": sub.notes,
        "is_active": sub.is_active,
        "created_at": sub.created_at.isoformat(),
        "updated_at": sub.updated_at.isoformat() if sub.updated_at else None
    }


def equipment_to_response(equip: Equipment, include_children: bool = False) -> dict:
    # Get PM asset type info if linked
    pm_asset_type_info = None
    if equip.pm_asset_type:
        pm_asset_type_info = {
            "id": equip.pm_asset_type.id,
            "code": equip.pm_asset_type.code,
            "name": equip.pm_asset_type.name,
            "pm_code": equip.pm_asset_type.pm_code,
            "system_code_id": equip.pm_asset_type.system_code_id,
            "system_code_name": equip.pm_asset_type.system_code.name if equip.pm_asset_type.system_code else None,
            "equipment_class_id": equip.pm_asset_type.system_code.equipment_class_id if equip.pm_asset_type.system_code else None,
            "equipment_class_name": equip.pm_asset_type.system_code.equipment_class.name if equip.pm_asset_type.system_code and equip.pm_asset_type.system_code.equipment_class else None,
        }

    result = {
        "id": equip.id,
        "room_id": equip.room_id,
        "name": equip.name,
        "code": equip.code,
        "category": equip.category,
        "equipment_type": equip.equipment_type,
        "pm_asset_type_id": equip.pm_asset_type_id,
        "pm_asset_type": pm_asset_type_info,
        "manufacturer": equip.manufacturer,
        "model": equip.model,
        "serial_number": equip.serial_number,
        "installation_date": equip.installation_date.isoformat() if equip.installation_date else None,
        "warranty_expiry": equip.warranty_expiry.isoformat() if equip.warranty_expiry else None,
        "status": equip.status,
        "condition": equip.condition,
        "specifications": equip.specifications,
        "location_details": equip.location_details,
        "photo_url": equip.photo_url,
        "qr_code": equip.qr_code,
        "notes": equip.notes,
        "is_active": equip.is_active,
        "sub_equipment_count": len([s for s in equip.sub_equipment if s.is_active]),
        "created_at": equip.created_at.isoformat(),
        "updated_at": equip.updated_at.isoformat() if equip.updated_at else None
    }

    if include_children:
        result["sub_equipment"] = [
            sub_equipment_to_response(s) for s in equip.sub_equipment if s.is_active
        ]

    return result


def room_to_response(room: Room, include_children: bool = False) -> dict:
    result = {
        "id": room.id,
        "floor_id": room.floor_id,
        "name": room.name,
        "code": room.code,
        "room_type": room.room_type,
        "area_sqm": room.area_sqm,
        "description": room.description,
        "notes": room.notes,
        "is_active": room.is_active,
        "equipment_count": len([e for e in room.equipment if e.is_active]),
        "created_at": room.created_at.isoformat(),
        "updated_at": room.updated_at.isoformat() if room.updated_at else None
    }

    if include_children:
        result["equipment"] = [
            equipment_to_response(e, include_children=True) for e in room.equipment if e.is_active
        ]

    return result


def floor_to_response(floor: Floor, include_children: bool = False) -> dict:
    result = {
        "id": floor.id,
        "branch_id": floor.branch_id,
        "name": floor.name,
        "code": floor.code,
        "level": floor.level,
        "description": floor.description,
        "notes": floor.notes,
        "is_active": floor.is_active,
        "rooms_count": len([r for r in floor.rooms if r.is_active]),
        "created_at": floor.created_at.isoformat(),
        "updated_at": floor.updated_at.isoformat() if floor.updated_at else None
    }

    if include_children:
        result["rooms"] = [
            room_to_response(r, include_children=True) for r in floor.rooms if r.is_active
        ]

    return result


# ============================================================================
# Asset Tree Endpoint - Get Full Hierarchy
# ============================================================================

@router.get("/branches/{branch_id}/assets")
async def get_branch_assets(
    branch_id: int,
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get complete asset tree for a branch"""
    branch = verify_branch_access(branch_id, user, db)

    query = db.query(Floor).filter(Floor.branch_id == branch_id)
    if not include_inactive:
        query = query.filter(Floor.is_active == True)

    floors = query.order_by(Floor.level).all()

    return {
        "branch_id": branch.id,
        "branch_name": branch.name,
        "client_id": branch.client_id,
        "client_name": branch.client.name if branch.client else None,
        "floors": [floor_to_response(f, include_children=True) for f in floors]
    }


@router.get("/branches/{branch_id}/assets/summary")
async def get_branch_assets_summary(
    branch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get asset summary/counts for a branch"""
    branch = verify_branch_access(branch_id, user, db)

    floors = db.query(Floor).filter(
        Floor.branch_id == branch_id,
        Floor.is_active == True
    ).all()

    total_rooms = 0
    total_equipment = 0
    total_sub_equipment = 0
    equipment_by_category = {
        "electrical": 0,
        "mechanical": 0,
        "plumbing": 0,
        "hvac": 0,
        "furniture": 0,
        "building": 0,
        "fire_safety": 0,
        "other": 0
    }
    equipment_by_status = {}

    for floor in floors:
        for room in floor.rooms:
            if room.is_active:
                total_rooms += 1
                for equip in room.equipment:
                    if equip.is_active:
                        total_equipment += 1
                        # Normalize category to lowercase
                        cat = (equip.category or "other").lower()
                        if cat in equipment_by_category:
                            equipment_by_category[cat] += 1
                        else:
                            equipment_by_category["other"] += 1
                        equipment_by_status[equip.status] = equipment_by_status.get(equip.status, 0) + 1
                        for sub in equip.sub_equipment:
                            if sub.is_active:
                                total_sub_equipment += 1

    return {
        "branch_id": branch.id,
        "branch_name": branch.name,
        "floors_count": len(floors),
        "rooms_count": total_rooms,
        "equipment_count": total_equipment,
        "sub_equipment_count": total_sub_equipment,
        "equipment_by_category": equipment_by_category,
        "equipment_by_status": equipment_by_status
    }


# ============================================================================
# Floor Endpoints
# ============================================================================

@router.get("/floors/")
async def get_floors(
    branch_id: int,
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all floors for a branch"""
    verify_branch_access(branch_id, user, db)

    query = db.query(Floor).filter(Floor.branch_id == branch_id)
    if not include_inactive:
        query = query.filter(Floor.is_active == True)

    floors = query.order_by(Floor.level).all()
    return [floor_to_response(f) for f in floors]


@router.get("/floors/{floor_id}")
async def get_floor(
    floor_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    verify_branch_access(floor.branch_id, user, db)
    return floor_to_response(floor, include_children=True)


@router.post("/floors/")
async def create_floor(
    data: FloorCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new floor"""
    verify_branch_access(data.branch_id, user, db)

    floor = Floor(
        branch_id=data.branch_id,
        name=data.name,
        code=data.code,
        level=data.level or 0,
        description=data.description,
        notes=data.notes
    )

    db.add(floor)
    db.commit()
    db.refresh(floor)

    logger.info(f"Floor '{floor.name}' created by '{user.email}'")
    return floor_to_response(floor)


@router.put("/floors/{floor_id}")
async def update_floor(
    floor_id: int,
    data: FloorUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    verify_branch_access(floor.branch_id, user, db)

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(floor, field, value)

    db.commit()
    db.refresh(floor)

    logger.info(f"Floor '{floor.name}' updated by '{user.email}'")
    return floor_to_response(floor)


@router.delete("/floors/{floor_id}")
async def delete_floor(
    floor_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    verify_branch_access(floor.branch_id, user, db)

    floor.is_active = False
    db.commit()

    logger.info(f"Floor '{floor.name}' deactivated by '{user.email}'")
    return {"success": True, "message": f"Floor '{floor.name}' has been deactivated"}


# ============================================================================
# Room Endpoints
# ============================================================================

@router.get("/rooms/")
async def get_rooms(
    floor_id: int,
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all rooms for a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    verify_branch_access(floor.branch_id, user, db)

    query = db.query(Room).filter(Room.floor_id == floor_id)
    if not include_inactive:
        query = query.filter(Room.is_active == True)

    rooms = query.order_by(Room.name).all()
    return [room_to_response(r) for r in rooms]


@router.get("/rooms/{room_id}")
async def get_room(
    room_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    verify_branch_access(room.floor.branch_id, user, db)
    return room_to_response(room, include_children=True)


@router.post("/rooms/")
async def create_room(
    data: RoomCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new room"""
    floor = db.query(Floor).filter(Floor.id == data.floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    verify_branch_access(floor.branch_id, user, db)

    room = Room(
        floor_id=data.floor_id,
        name=data.name,
        code=data.code,
        room_type=data.room_type,
        area_sqm=data.area_sqm,
        description=data.description,
        notes=data.notes
    )

    db.add(room)
    db.commit()
    db.refresh(room)

    logger.info(f"Room '{room.name}' created by '{user.email}'")
    return room_to_response(room)


@router.put("/rooms/{room_id}")
async def update_room(
    room_id: int,
    data: RoomUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    verify_branch_access(room.floor.branch_id, user, db)

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    db.commit()
    db.refresh(room)

    logger.info(f"Room '{room.name}' updated by '{user.email}'")
    return room_to_response(room)


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    verify_branch_access(room.floor.branch_id, user, db)

    room.is_active = False
    db.commit()

    logger.info(f"Room '{room.name}' deactivated by '{user.email}'")
    return {"success": True, "message": f"Room '{room.name}' has been deactivated"}


# ============================================================================
# Equipment Endpoints
# ============================================================================

@router.get("/equipment/")
async def get_equipment(
    room_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get equipment with optional filters"""
    if not user.company_id:
        raise HTTPException(status_code=404, detail="No company associated")

    if room_id:
        room = db.query(Room).filter(Room.id == room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        verify_branch_access(room.floor.branch_id, user, db)
        query = db.query(Equipment).filter(Equipment.room_id == room_id)
    elif branch_id:
        verify_branch_access(branch_id, user, db)
        query = db.query(Equipment).join(Room).join(Floor).filter(Floor.branch_id == branch_id)
    else:
        # Get all equipment for company
        query = db.query(Equipment).join(Room).join(Floor).join(Branch).join(Client).filter(
            Client.company_id == user.company_id
        )

    if not include_inactive:
        query = query.filter(Equipment.is_active == True)

    if category:
        query = query.filter(Equipment.category == category)

    if status:
        query = query.filter(Equipment.status == status)

    equipment = query.order_by(Equipment.name).all()
    return [equipment_to_response(e) for e in equipment]


@router.get("/equipment/{equipment_id}")
async def get_equipment_item(
    equipment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific equipment item"""
    equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Equipment not found")

    verify_branch_access(equip.room.floor.branch_id, user, db)
    return equipment_to_response(equip, include_children=True)


@router.post("/equipment/")
async def create_equipment(
    data: EquipmentCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create new equipment"""
    room = db.query(Room).filter(Room.id == data.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    verify_branch_access(room.floor.branch_id, user, db)

    # Validate category
    valid_categories = ["electrical", "mechanical", "plumbing", "hvac", "furniture", "building", "fire_safety", "other"]
    if data.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Category must be one of: {', '.join(valid_categories)}"
        )

    equip = Equipment(
        room_id=data.room_id,
        name=data.name,
        code=data.code,
        category=data.category,
        equipment_type=data.equipment_type,
        pm_asset_type_id=data.pm_asset_type_id,
        manufacturer=data.manufacturer,
        model=data.model,
        serial_number=data.serial_number,
        installation_date=data.installation_date,
        warranty_expiry=data.warranty_expiry,
        status=data.status or "operational",
        condition=data.condition or "good",
        specifications=data.specifications,
        location_details=data.location_details,
        photo_url=data.photo_url,
        qr_code=data.qr_code,
        notes=data.notes
    )

    db.add(equip)
    db.commit()
    db.refresh(equip)

    logger.info(f"Equipment '{equip.name}' created by '{user.email}'")
    return equipment_to_response(equip)


@router.put("/equipment/{equipment_id}")
async def update_equipment(
    equipment_id: int,
    data: EquipmentUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update equipment"""
    equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Equipment not found")

    verify_branch_access(equip.room.floor.branch_id, user, db)

    valid_categories = ["electrical", "mechanical", "plumbing", "hvac", "furniture", "building", "fire_safety", "other"]
    if data.category and data.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Category must be one of: {', '.join(valid_categories)}"
        )

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(equip, field, value)

    db.commit()
    db.refresh(equip)

    logger.info(f"Equipment '{equip.name}' updated by '{user.email}'")
    return equipment_to_response(equip)


@router.delete("/equipment/{equipment_id}")
async def delete_equipment(
    equipment_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete equipment"""
    equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Equipment not found")

    verify_branch_access(equip.room.floor.branch_id, user, db)

    equip.is_active = False
    equip.status = "retired"
    db.commit()

    logger.info(f"Equipment '{equip.name}' deactivated by '{user.email}'")
    return {"success": True, "message": f"Equipment '{equip.name}' has been deactivated"}


# ============================================================================
# Sub-Equipment Endpoints
# ============================================================================

@router.get("/sub-equipment/")
async def get_sub_equipment(
    equipment_id: int,
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all sub-equipment for an equipment item"""
    equip = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Equipment not found")

    verify_branch_access(equip.room.floor.branch_id, user, db)

    query = db.query(SubEquipment).filter(SubEquipment.equipment_id == equipment_id)
    if not include_inactive:
        query = query.filter(SubEquipment.is_active == True)

    subs = query.order_by(SubEquipment.name).all()
    return [sub_equipment_to_response(s) for s in subs]


@router.get("/sub-equipment/{sub_equipment_id}")
async def get_sub_equipment_item(
    sub_equipment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific sub-equipment item"""
    sub = db.query(SubEquipment).filter(SubEquipment.id == sub_equipment_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sub-equipment not found")

    verify_branch_access(sub.parent_equipment.room.floor.branch_id, user, db)
    return sub_equipment_to_response(sub)


@router.post("/sub-equipment/")
async def create_sub_equipment(
    data: SubEquipmentCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create new sub-equipment"""
    equip = db.query(Equipment).filter(Equipment.id == data.equipment_id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Equipment not found")

    verify_branch_access(equip.room.floor.branch_id, user, db)

    sub = SubEquipment(
        equipment_id=data.equipment_id,
        name=data.name,
        code=data.code,
        component_type=data.component_type,
        manufacturer=data.manufacturer,
        model=data.model,
        serial_number=data.serial_number,
        installation_date=data.installation_date,
        warranty_expiry=data.warranty_expiry,
        status=data.status or "operational",
        condition=data.condition or "good",
        specifications=data.specifications,
        photo_url=data.photo_url,
        notes=data.notes
    )

    db.add(sub)
    db.commit()
    db.refresh(sub)

    logger.info(f"Sub-equipment '{sub.name}' created by '{user.email}'")
    return sub_equipment_to_response(sub)


@router.put("/sub-equipment/{sub_equipment_id}")
async def update_sub_equipment(
    sub_equipment_id: int,
    data: SubEquipmentUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update sub-equipment"""
    sub = db.query(SubEquipment).filter(SubEquipment.id == sub_equipment_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sub-equipment not found")

    verify_branch_access(sub.parent_equipment.room.floor.branch_id, user, db)

    update_data = data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(sub, field, value)

    db.commit()
    db.refresh(sub)

    logger.info(f"Sub-equipment '{sub.name}' updated by '{user.email}'")
    return sub_equipment_to_response(sub)


@router.delete("/sub-equipment/{sub_equipment_id}")
async def delete_sub_equipment(
    sub_equipment_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft delete sub-equipment"""
    sub = db.query(SubEquipment).filter(SubEquipment.id == sub_equipment_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sub-equipment not found")

    verify_branch_access(sub.parent_equipment.room.floor.branch_id, user, db)

    sub.is_active = False
    sub.status = "retired"
    db.commit()

    logger.info(f"Sub-equipment '{sub.name}' deactivated by '{user.email}'")
    return {"success": True, "message": f"Sub-equipment '{sub.name}' has been deactivated"}
