"""
API endpoints for Preventive Maintenance Checklists.
Provides the PM hierarchy and checklist data for the frontend.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Union
from pydantic import BaseModel
from datetime import datetime
import logging

from app.database import get_db
from app.models import (
    User, Company, PMEquipmentClass, PMSystemCode, PMAssetType,
    PMChecklist, PMActivity, HandHeldDevice
)
from app.api.auth import get_current_user
from app.utils.pm_seed import seed_pm_checklists_for_company
from app.config import settings
from jose import jwt

router = APIRouter()
security = HTTPBearer()
logger = logging.getLogger(__name__)


def verify_token_payload(token: str) -> Optional[dict]:
    """Verify token and return full payload"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except:
        return None


# HHD Authentication Support
class HHDContext:
    """Context object for HHD authentication - mimics User for compatibility"""
    def __init__(self, device: HandHeldDevice, technician_id: Optional[int] = None):
        self.device = device
        self.company_id = device.company_id
        self.id = technician_id
        self.email = f"hhd:{device.device_code}"
        self.name = device.device_name
        self.role = "technician"


def get_current_user_or_hhd(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """Authenticate either a regular user or an HHD device"""
    token = credentials.credentials
    payload = verify_token_payload(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    sub = payload.get("sub")
    token_type = payload.get("type")

    # Check if this is an HHD token
    if token_type == "hhd" or (sub and sub.startswith("hhd:")):
        device_id = payload.get("device_id")
        if not device_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HHD token"
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

        technician_id = payload.get("technician_id")
        return HHDContext(device, technician_id)

    # Regular user token
    user = db.query(User).filter(User.email == sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


# ============================================================================
# Pydantic Schemas
# ============================================================================

class PMActivityResponse(BaseModel):
    id: int
    sequence_order: int
    description: str
    estimated_duration_minutes: Optional[int]
    requires_measurement: bool
    measurement_unit: Optional[str]
    is_critical: bool
    safety_notes: Optional[str]

    class Config:
        from_attributes = True


class PMChecklistResponse(BaseModel):
    id: int
    frequency_code: str
    frequency_name: str
    frequency_days: int
    activities_count: int = 0

    class Config:
        from_attributes = True


class PMChecklistWithActivitiesResponse(PMChecklistResponse):
    activities: List[PMActivityResponse] = []


class PMAssetTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    pm_code: Optional[str]
    description: Optional[str]
    checklists_count: int = 0

    class Config:
        from_attributes = True


class PMAssetTypeDetailResponse(PMAssetTypeResponse):
    checklists: List[PMChecklistWithActivitiesResponse] = []
    system_code_name: str = ""
    equipment_class_name: str = ""


class PMSystemCodeResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str]
    asset_types_count: int = 0

    class Config:
        from_attributes = True


class PMSystemCodeWithAssetTypesResponse(PMSystemCodeResponse):
    asset_types: List[PMAssetTypeResponse] = []


class PMEquipmentClassResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str]
    system_codes_count: int = 0

    class Config:
        from_attributes = True


class PMEquipmentClassWithSystemCodesResponse(PMEquipmentClassResponse):
    system_codes: List[PMSystemCodeResponse] = []


class PMHierarchyResponse(BaseModel):
    equipment_classes: List[PMEquipmentClassWithSystemCodesResponse]


# ============================================================================
# Equipment Class Endpoints
# ============================================================================

@router.get("/pm/equipment-classes", response_model=List[PMEquipmentClassResponse])
async def get_equipment_classes(
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all equipment classes for the company"""
    classes = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMEquipmentClass.is_active == True
    ).order_by(PMEquipmentClass.sort_order).all()

    return [
        {
            "id": ec.id,
            "code": ec.code,
            "name": ec.name,
            "description": ec.description,
            "system_codes_count": len([sc for sc in ec.system_codes if sc.is_active])
        }
        for ec in classes
    ]


@router.get("/pm/equipment-classes/{class_id}", response_model=PMEquipmentClassWithSystemCodesResponse)
async def get_equipment_class(
    class_id: int,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get an equipment class with its system codes"""
    ec = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.id == class_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not ec:
        raise HTTPException(status_code=404, detail="Equipment class not found")

    return {
        "id": ec.id,
        "code": ec.code,
        "name": ec.name,
        "description": ec.description,
        "system_codes_count": len([sc for sc in ec.system_codes if sc.is_active]),
        "system_codes": [
            {
                "id": sc.id,
                "code": sc.code,
                "name": sc.name,
                "description": sc.description,
                "asset_types_count": len([at for at in sc.asset_types if at.is_active])
            }
            for sc in sorted(ec.system_codes, key=lambda x: x.sort_order)
            if sc.is_active
        ]
    }


# ============================================================================
# System Code Endpoints
# ============================================================================

@router.get("/pm/system-codes", response_model=List[PMSystemCodeResponse])
async def get_system_codes(
    equipment_class_id: Optional[int] = None,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all system codes, optionally filtered by equipment class"""
    query = db.query(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMSystemCode.is_active == True
    )

    if equipment_class_id:
        query = query.filter(PMSystemCode.equipment_class_id == equipment_class_id)

    system_codes = query.order_by(PMSystemCode.sort_order).all()

    return [
        {
            "id": sc.id,
            "code": sc.code,
            "name": sc.name,
            "description": sc.description,
            "asset_types_count": len([at for at in sc.asset_types if at.is_active])
        }
        for sc in system_codes
    ]


@router.get("/pm/system-codes/{system_code_id}", response_model=PMSystemCodeWithAssetTypesResponse)
async def get_system_code(
    system_code_id: int,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a system code with its asset types"""
    sc = db.query(PMSystemCode).join(PMEquipmentClass).filter(
        PMSystemCode.id == system_code_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not sc:
        raise HTTPException(status_code=404, detail="System code not found")

    return {
        "id": sc.id,
        "code": sc.code,
        "name": sc.name,
        "description": sc.description,
        "asset_types_count": len([at for at in sc.asset_types if at.is_active]),
        "asset_types": [
            {
                "id": at.id,
                "code": at.code,
                "name": at.name,
                "pm_code": at.pm_code,
                "description": at.description,
                "checklists_count": len([cl for cl in at.checklists if cl.is_active])
            }
            for at in sorted(sc.asset_types, key=lambda x: x.sort_order)
            if at.is_active
        ]
    }


# ============================================================================
# Asset Type Endpoints
# ============================================================================

@router.get("/pm/asset-types", response_model=List[PMAssetTypeResponse])
async def get_asset_types(
    system_code_id: Optional[int] = None,
    search: Optional[str] = None,
    has_checklists: bool = False,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get all asset types, optionally filtered by system code or search query"""
    query = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMAssetType.is_active == True
    )

    if system_code_id:
        query = query.filter(PMAssetType.system_code_id == system_code_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (PMAssetType.name.ilike(search_term)) |
            (PMAssetType.code.ilike(search_term)) |
            (PMAssetType.pm_code.ilike(search_term))
        )

    asset_types = query.order_by(PMAssetType.sort_order).all()

    result = []
    for at in asset_types:
        checklists_count = len([cl for cl in at.checklists if cl.is_active])
        if has_checklists and checklists_count == 0:
            continue
        result.append({
            "id": at.id,
            "code": at.code,
            "name": at.name,
            "pm_code": at.pm_code,
            "description": at.description,
            "checklists_count": checklists_count
        })

    return result


@router.get("/pm/asset-types/{asset_type_id}", response_model=PMAssetTypeDetailResponse)
async def get_asset_type(
    asset_type_id: int,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get an asset type with its checklists and activities"""
    at = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMAssetType.id == asset_type_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not at:
        raise HTTPException(status_code=404, detail="Asset type not found")

    return {
        "id": at.id,
        "code": at.code,
        "name": at.name,
        "pm_code": at.pm_code,
        "description": at.description,
        "checklists_count": len([cl for cl in at.checklists if cl.is_active]),
        "system_code_name": at.system_code.name,
        "equipment_class_name": at.system_code.equipment_class.name,
        "checklists": [
            {
                "id": cl.id,
                "frequency_code": cl.frequency_code,
                "frequency_name": cl.frequency_name,
                "frequency_days": cl.frequency_days,
                "activities_count": len([a for a in cl.activities if a.is_active]),
                "activities": [
                    {
                        "id": a.id,
                        "sequence_order": a.sequence_order,
                        "description": a.description,
                        "estimated_duration_minutes": a.estimated_duration_minutes,
                        "requires_measurement": a.requires_measurement,
                        "measurement_unit": a.measurement_unit,
                        "is_critical": a.is_critical,
                        "safety_notes": a.safety_notes
                    }
                    for a in sorted(cl.activities, key=lambda x: x.sequence_order)
                    if a.is_active
                ]
            }
            for cl in sorted(at.checklists, key=lambda x: x.frequency_days)
            if cl.is_active
        ]
    }


# ============================================================================
# Checklist Endpoints
# ============================================================================

@router.get("/pm/checklists/{checklist_id}", response_model=PMChecklistWithActivitiesResponse)
async def get_checklist(
    checklist_id: int,
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get a checklist with its activities"""
    cl = db.query(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMChecklist.id == checklist_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not cl:
        raise HTTPException(status_code=404, detail="Checklist not found")

    return {
        "id": cl.id,
        "frequency_code": cl.frequency_code,
        "frequency_name": cl.frequency_name,
        "frequency_days": cl.frequency_days,
        "activities_count": len([a for a in cl.activities if a.is_active]),
        "activities": [
            {
                "id": a.id,
                "sequence_order": a.sequence_order,
                "description": a.description,
                "estimated_duration_minutes": a.estimated_duration_minutes,
                "requires_measurement": a.requires_measurement,
                "measurement_unit": a.measurement_unit,
                "is_critical": a.is_critical,
                "safety_notes": a.safety_notes
            }
            for a in sorted(cl.activities, key=lambda x: x.sequence_order)
            if a.is_active
        ]
    }


# ============================================================================
# Hierarchy Endpoint
# ============================================================================

@router.get("/pm/hierarchy", response_model=PMHierarchyResponse)
async def get_pm_hierarchy(
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get the full PM hierarchy (equipment classes with system codes)"""
    classes = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMEquipmentClass.is_active == True
    ).order_by(PMEquipmentClass.sort_order).all()

    return {
        "equipment_classes": [
            {
                "id": ec.id,
                "code": ec.code,
                "name": ec.name,
                "description": ec.description,
                "system_codes_count": len([sc for sc in ec.system_codes if sc.is_active]),
                "system_codes": [
                    {
                        "id": sc.id,
                        "code": sc.code,
                        "name": sc.name,
                        "description": sc.description,
                        "asset_types_count": len([at for at in sc.asset_types if at.is_active])
                    }
                    for sc in sorted(ec.system_codes, key=lambda x: x.sort_order)
                    if sc.is_active
                ]
            }
            for ec in classes
        ]
    }


# ============================================================================
# Search Endpoint
# ============================================================================

@router.get("/pm/search")
async def search_pm(
    q: str = Query(..., min_length=2),
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Search across asset types and return matches with their checklists"""
    search_term = f"%{q}%"

    asset_types = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMAssetType.is_active == True,
        (PMAssetType.name.ilike(search_term)) |
        (PMAssetType.code.ilike(search_term)) |
        (PMAssetType.pm_code.ilike(search_term))
    ).limit(50).all()

    return [
        {
            "id": at.id,
            "code": at.code,
            "name": at.name,
            "pm_code": at.pm_code,
            "system_code": at.system_code.name,
            "equipment_class": at.system_code.equipment_class.name,
            "checklists": [
                {
                    "id": cl.id,
                    "frequency_code": cl.frequency_code,
                    "frequency_name": cl.frequency_name,
                    "activities_count": len([a for a in cl.activities if a.is_active])
                }
                for cl in at.checklists
                if cl.is_active
            ]
        }
        for at in asset_types
    ]


# ============================================================================
# Statistics Endpoint
# ============================================================================

@router.get("/pm/stats")
async def get_pm_stats(
    user: Union[User, HHDContext] = Depends(get_current_user_or_hhd),
    db: Session = Depends(get_db)
):
    """Get PM statistics for the dashboard"""
    equipment_classes = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMEquipmentClass.is_active == True
    ).count()

    system_codes = db.query(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMSystemCode.is_active == True
    ).count()

    asset_types = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMAssetType.is_active == True
    ).count()

    # Only count asset types that have checklists
    asset_types_with_checklists = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).join(
        PMChecklist
    ).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMAssetType.is_active == True,
        PMChecklist.is_active == True
    ).distinct().count()

    checklists = db.query(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMChecklist.is_active == True
    ).count()

    activities = db.query(PMActivity).join(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMActivity.is_active == True
    ).count()

    return {
        "equipment_classes": equipment_classes,
        "system_codes": system_codes,
        "asset_types": asset_types,
        "asset_types_with_checklists": asset_types_with_checklists,
        "checklists": checklists,
        "activities": activities
    }


# ============================================================================
# PM Seeding Endpoints
# ============================================================================

def check_company_has_pm_data(db: Session, company_id: int) -> bool:
    """Check if a company already has PM equipment classes seeded"""
    count = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == company_id
    ).count()
    return count > 0


@router.post("/pm/seed")
async def seed_pm_data_for_company(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Seed PM data for the current user's company.
    Only seeds if PM data doesn't already exist.
    """
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User has no company")

    # Check if already seeded
    if check_company_has_pm_data(db, user.company_id):
        return {
            "success": True,
            "message": "PM data already exists for this company",
            "already_seeded": True
        }

    try:
        stats = seed_pm_checklists_for_company(user.company_id, db)
        db.commit()

        if "error" in stats:
            raise HTTPException(status_code=500, detail=stats["error"])

        return {
            "success": True,
            "message": "PM data seeded successfully",
            "already_seeded": False,
            "stats": stats
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding PM data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Admin CRUD Endpoints - Equipment Classes
# ============================================================================

class PMEquipmentClassCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = 0


class PMEquipmentClassUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.post("/pm/equipment-classes", response_model=PMEquipmentClassResponse)
async def create_equipment_class(
    data: PMEquipmentClassCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new equipment class (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Check for duplicate code
    existing = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.company_id == user.company_id,
        PMEquipmentClass.code == data.code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Equipment class with code '{data.code}' already exists")

    ec = PMEquipmentClass(
        company_id=user.company_id,
        code=data.code,
        name=data.name,
        description=data.description,
        sort_order=data.sort_order or 0,
        is_active=True
    )
    db.add(ec)
    db.commit()
    db.refresh(ec)

    return {
        "id": ec.id,
        "code": ec.code,
        "name": ec.name,
        "description": ec.description,
        "system_codes_count": 0
    }


@router.put("/pm/equipment-classes/{class_id}", response_model=PMEquipmentClassResponse)
async def update_equipment_class(
    class_id: int,
    data: PMEquipmentClassUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an equipment class (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    ec = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.id == class_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not ec:
        raise HTTPException(status_code=404, detail="Equipment class not found")

    if data.code is not None:
        ec.code = data.code
    if data.name is not None:
        ec.name = data.name
    if data.description is not None:
        ec.description = data.description
    if data.sort_order is not None:
        ec.sort_order = data.sort_order
    if data.is_active is not None:
        ec.is_active = data.is_active

    db.commit()
    db.refresh(ec)

    return {
        "id": ec.id,
        "code": ec.code,
        "name": ec.name,
        "description": ec.description,
        "system_codes_count": len([sc for sc in ec.system_codes if sc.is_active])
    }


@router.delete("/pm/equipment-classes/{class_id}")
async def delete_equipment_class(
    class_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) an equipment class (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    ec = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.id == class_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not ec:
        raise HTTPException(status_code=404, detail="Equipment class not found")

    ec.is_active = False
    db.commit()

    return {"success": True, "message": "Equipment class deleted"}


# ============================================================================
# Admin CRUD Endpoints - System Codes
# ============================================================================

class PMSystemCodeCreate(BaseModel):
    equipment_class_id: int
    code: str
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = 0


class PMSystemCodeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.post("/pm/system-codes", response_model=PMSystemCodeResponse)
async def create_system_code(
    data: PMSystemCodeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new system code (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify equipment class belongs to company
    ec = db.query(PMEquipmentClass).filter(
        PMEquipmentClass.id == data.equipment_class_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()
    if not ec:
        raise HTTPException(status_code=404, detail="Equipment class not found")

    sc = PMSystemCode(
        equipment_class_id=data.equipment_class_id,
        code=data.code,
        name=data.name,
        description=data.description,
        sort_order=data.sort_order or 0,
        is_active=True
    )
    db.add(sc)
    db.commit()
    db.refresh(sc)

    return {
        "id": sc.id,
        "code": sc.code,
        "name": sc.name,
        "description": sc.description,
        "asset_types_count": 0
    }


@router.put("/pm/system-codes/{system_code_id}", response_model=PMSystemCodeResponse)
async def update_system_code(
    system_code_id: int,
    data: PMSystemCodeUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a system code (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    sc = db.query(PMSystemCode).join(PMEquipmentClass).filter(
        PMSystemCode.id == system_code_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not sc:
        raise HTTPException(status_code=404, detail="System code not found")

    if data.code is not None:
        sc.code = data.code
    if data.name is not None:
        sc.name = data.name
    if data.description is not None:
        sc.description = data.description
    if data.sort_order is not None:
        sc.sort_order = data.sort_order
    if data.is_active is not None:
        sc.is_active = data.is_active

    db.commit()
    db.refresh(sc)

    return {
        "id": sc.id,
        "code": sc.code,
        "name": sc.name,
        "description": sc.description,
        "asset_types_count": len([at for at in sc.asset_types if at.is_active])
    }


@router.delete("/pm/system-codes/{system_code_id}")
async def delete_system_code(
    system_code_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) a system code (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    sc = db.query(PMSystemCode).join(PMEquipmentClass).filter(
        PMSystemCode.id == system_code_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not sc:
        raise HTTPException(status_code=404, detail="System code not found")

    sc.is_active = False
    db.commit()

    return {"success": True, "message": "System code deleted"}


# ============================================================================
# Admin CRUD Endpoints - Asset Types
# ============================================================================

class PMAssetTypeCreate(BaseModel):
    system_code_id: int
    code: str
    name: str
    pm_code: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = 0


class PMAssetTypeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    pm_code: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.post("/pm/asset-types", response_model=PMAssetTypeResponse)
async def create_asset_type(
    data: PMAssetTypeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new asset type (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify system code belongs to company
    sc = db.query(PMSystemCode).join(PMEquipmentClass).filter(
        PMSystemCode.id == data.system_code_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail="System code not found")

    at = PMAssetType(
        system_code_id=data.system_code_id,
        code=data.code,
        name=data.name,
        pm_code=data.pm_code,
        description=data.description,
        sort_order=data.sort_order or 0,
        is_active=True
    )
    db.add(at)
    db.commit()
    db.refresh(at)

    return {
        "id": at.id,
        "code": at.code,
        "name": at.name,
        "pm_code": at.pm_code,
        "description": at.description,
        "checklists_count": 0
    }


@router.put("/pm/asset-types/{asset_type_id}", response_model=PMAssetTypeResponse)
async def update_asset_type(
    asset_type_id: int,
    data: PMAssetTypeUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an asset type (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    at = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMAssetType.id == asset_type_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not at:
        raise HTTPException(status_code=404, detail="Asset type not found")

    if data.code is not None:
        at.code = data.code
    if data.name is not None:
        at.name = data.name
    if data.pm_code is not None:
        at.pm_code = data.pm_code
    if data.description is not None:
        at.description = data.description
    if data.sort_order is not None:
        at.sort_order = data.sort_order
    if data.is_active is not None:
        at.is_active = data.is_active

    db.commit()
    db.refresh(at)

    return {
        "id": at.id,
        "code": at.code,
        "name": at.name,
        "pm_code": at.pm_code,
        "description": at.description,
        "checklists_count": len([cl for cl in at.checklists if cl.is_active])
    }


@router.delete("/pm/asset-types/{asset_type_id}")
async def delete_asset_type(
    asset_type_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) an asset type (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    at = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMAssetType.id == asset_type_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not at:
        raise HTTPException(status_code=404, detail="Asset type not found")

    at.is_active = False
    db.commit()

    return {"success": True, "message": "Asset type deleted"}


# ============================================================================
# Admin CRUD Endpoints - Checklists
# ============================================================================

class PMChecklistCreate(BaseModel):
    asset_type_id: int
    frequency_code: str
    frequency_name: str
    frequency_days: int


class PMChecklistUpdate(BaseModel):
    frequency_code: Optional[str] = None
    frequency_name: Optional[str] = None
    frequency_days: Optional[int] = None
    is_active: Optional[bool] = None


@router.post("/pm/checklists", response_model=PMChecklistResponse)
async def create_checklist(
    data: PMChecklistCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new checklist (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify asset type belongs to company
    at = db.query(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMAssetType.id == data.asset_type_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()
    if not at:
        raise HTTPException(status_code=404, detail="Asset type not found")

    cl = PMChecklist(
        asset_type_id=data.asset_type_id,
        frequency_code=data.frequency_code,
        frequency_name=data.frequency_name,
        frequency_days=data.frequency_days,
        is_active=True
    )
    db.add(cl)
    db.commit()
    db.refresh(cl)

    return {
        "id": cl.id,
        "frequency_code": cl.frequency_code,
        "frequency_name": cl.frequency_name,
        "frequency_days": cl.frequency_days,
        "activities_count": 0
    }


@router.put("/pm/checklists/{checklist_id}", response_model=PMChecklistResponse)
async def update_checklist(
    checklist_id: int,
    data: PMChecklistUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a checklist (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    cl = db.query(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMChecklist.id == checklist_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not cl:
        raise HTTPException(status_code=404, detail="Checklist not found")

    if data.frequency_code is not None:
        cl.frequency_code = data.frequency_code
    if data.frequency_name is not None:
        cl.frequency_name = data.frequency_name
    if data.frequency_days is not None:
        cl.frequency_days = data.frequency_days
    if data.is_active is not None:
        cl.is_active = data.is_active

    db.commit()
    db.refresh(cl)

    return {
        "id": cl.id,
        "frequency_code": cl.frequency_code,
        "frequency_name": cl.frequency_name,
        "frequency_days": cl.frequency_days,
        "activities_count": len([a for a in cl.activities if a.is_active])
    }


@router.delete("/pm/checklists/{checklist_id}")
async def delete_checklist(
    checklist_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) a checklist (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    cl = db.query(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMChecklist.id == checklist_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not cl:
        raise HTTPException(status_code=404, detail="Checklist not found")

    cl.is_active = False
    db.commit()

    return {"success": True, "message": "Checklist deleted"}


# ============================================================================
# Admin CRUD Endpoints - Activities
# ============================================================================

class PMActivityCreate(BaseModel):
    checklist_id: int
    sequence_order: int
    description: str
    estimated_duration_minutes: Optional[int] = None
    requires_measurement: bool = False
    measurement_unit: Optional[str] = None
    is_critical: bool = False
    safety_notes: Optional[str] = None


class PMActivityUpdate(BaseModel):
    sequence_order: Optional[int] = None
    description: Optional[str] = None
    estimated_duration_minutes: Optional[int] = None
    requires_measurement: Optional[bool] = None
    measurement_unit: Optional[str] = None
    is_critical: Optional[bool] = None
    safety_notes: Optional[str] = None
    is_active: Optional[bool] = None


@router.post("/pm/activities", response_model=PMActivityResponse)
async def create_activity(
    data: PMActivityCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new activity (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify checklist belongs to company
    cl = db.query(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMChecklist.id == data.checklist_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()
    if not cl:
        raise HTTPException(status_code=404, detail="Checklist not found")

    activity = PMActivity(
        checklist_id=data.checklist_id,
        sequence_order=data.sequence_order,
        description=data.description,
        estimated_duration_minutes=data.estimated_duration_minutes,
        requires_measurement=data.requires_measurement,
        measurement_unit=data.measurement_unit,
        is_critical=data.is_critical,
        safety_notes=data.safety_notes,
        is_active=True
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)

    return {
        "id": activity.id,
        "sequence_order": activity.sequence_order,
        "description": activity.description,
        "estimated_duration_minutes": activity.estimated_duration_minutes,
        "requires_measurement": activity.requires_measurement,
        "measurement_unit": activity.measurement_unit,
        "is_critical": activity.is_critical,
        "safety_notes": activity.safety_notes
    }


@router.put("/pm/activities/{activity_id}", response_model=PMActivityResponse)
async def update_activity(
    activity_id: int,
    data: PMActivityUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an activity (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    activity = db.query(PMActivity).join(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMActivity.id == activity_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    if data.sequence_order is not None:
        activity.sequence_order = data.sequence_order
    if data.description is not None:
        activity.description = data.description
    if data.estimated_duration_minutes is not None:
        activity.estimated_duration_minutes = data.estimated_duration_minutes
    if data.requires_measurement is not None:
        activity.requires_measurement = data.requires_measurement
    if data.measurement_unit is not None:
        activity.measurement_unit = data.measurement_unit
    if data.is_critical is not None:
        activity.is_critical = data.is_critical
    if data.safety_notes is not None:
        activity.safety_notes = data.safety_notes
    if data.is_active is not None:
        activity.is_active = data.is_active

    db.commit()
    db.refresh(activity)

    return {
        "id": activity.id,
        "sequence_order": activity.sequence_order,
        "description": activity.description,
        "estimated_duration_minutes": activity.estimated_duration_minutes,
        "requires_measurement": activity.requires_measurement,
        "measurement_unit": activity.measurement_unit,
        "is_critical": activity.is_critical,
        "safety_notes": activity.safety_notes
    }


@router.delete("/pm/activities/{activity_id}")
async def delete_activity(
    activity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete (deactivate) an activity (admin only)"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    activity = db.query(PMActivity).join(PMChecklist).join(PMAssetType).join(PMSystemCode).join(PMEquipmentClass).filter(
        PMActivity.id == activity_id,
        PMEquipmentClass.company_id == user.company_id
    ).first()

    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    activity.is_active = False
    db.commit()

    return {"success": True, "message": "Activity deleted"}


# ============================================================================
# PM Seeding Endpoints
# ============================================================================

@router.post("/pm/seed-all")
async def seed_pm_data_for_all_companies(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Seed PM data for ALL companies that don't have PM data yet.
    Admin only endpoint.
    """
    # Check if user is admin
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get all companies
    companies = db.query(Company).all()

    results = {
        "total_companies": len(companies),
        "seeded": [],
        "skipped": [],
        "errors": []
    }

    for company in companies:
        try:
            # Check if already seeded
            if check_company_has_pm_data(db, company.id):
                results["skipped"].append({
                    "company_id": company.id,
                    "company_name": company.name,
                    "reason": "Already has PM data"
                })
                continue

            # Seed PM data
            stats = seed_pm_checklists_for_company(company.id, db)
            db.commit()

            if "error" in stats:
                results["errors"].append({
                    "company_id": company.id,
                    "company_name": company.name,
                    "error": stats["error"]
                })
            else:
                results["seeded"].append({
                    "company_id": company.id,
                    "company_name": company.name,
                    "stats": stats
                })

        except Exception as e:
            db.rollback()
            results["errors"].append({
                "company_id": company.id,
                "company_name": company.name,
                "error": str(e)
            })

    return {
        "success": True,
        "message": f"Processed {len(companies)} companies",
        "results": results
    }
