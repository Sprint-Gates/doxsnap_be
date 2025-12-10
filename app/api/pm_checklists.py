"""
API endpoints for Preventive Maintenance Checklists.
Provides the PM hierarchy and checklist data for the frontend.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import logging

from app.database import get_db
from app.models import (
    User, PMEquipmentClass, PMSystemCode, PMAssetType,
    PMChecklist, PMActivity
)
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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
