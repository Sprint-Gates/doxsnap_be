from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from app.database import get_db
from app.models import Site, Block, Building, Space, Floor, Unit, Room, Desk, Equipment, SubEquipment, User, Client, PMAssetType, PMEquipmentClass
from app.utils.security import verify_token
from app.schemas import (
    SiteCreate, SiteUpdate, Site as SiteSchema,
    BlockCreate, BlockUpdate, Block as BlockSchema,
    BuildingCreate, BuildingUpdate, Building as BuildingSchema,
    SpaceCreate, SpaceUpdate, Space as SpaceSchema,
    FloorCreate, FloorUpdate, Floor as FloorSchema,
    UnitCreate, UnitUpdate, Unit as UnitSchema,
    RoomCreate, RoomUpdate, Room as RoomSchema,
    DeskCreate, DeskUpdate, Desk as DeskSchema,
    EquipmentCreate, EquipmentUpdate, Equipment as EquipmentSchema,
    SubEquipmentCreate, SubEquipmentUpdate, SubEquipment as SubEquipmentSchema
)
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


def get_site_from_building(building: Building, db: Session) -> Site:
    """
    Get the site for a building - either directly or through its block.
    Buildings can be attached to a site directly OR to a block.
    """
    if building.site_id:
        return db.query(Site).filter(Site.id == building.site_id).first()
    elif building.block_id:
        block = db.query(Block).filter(Block.id == building.block_id).first()
        if block:
            return db.query(Site).filter(Site.id == block.site_id).first()
    return None


# ============================================================================
# Site Endpoints
# ============================================================================

@router.get("/", response_model=List[SiteSchema])
async def get_sites(
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all sites, optionally filtered by client"""
    query = db.query(Site).filter(Site.client_id.in_(
        db.query(Client.id).filter(Client.company_id == current_user.company_id)
    ))

    if client_id is not None:
        query = query.filter(Site.client_id == client_id)

    if is_active is not None:
        query = query.filter(Site.is_active == is_active)

    return query.order_by(Site.name).offset(skip).limit(limit).all()


@router.get("/{site_id}", response_model=SiteSchema)
async def get_site(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific site by ID"""
    site = db.query(Site).filter(Site.id == site_id).first()

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify user has access to this site's client
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return site


@router.post("/", response_model=SiteSchema, status_code=status.HTTP_201_CREATED)
async def create_site(
    site_data: SiteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new site"""
    # Verify client belongs to user's company
    client = db.query(Client).filter(Client.id == site_data.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Client not found or access denied")

    site = Site(**site_data.model_dump())
    db.add(site)
    db.commit()
    db.refresh(site)

    logger.info(f"Site created: {site.id} - {site.name}")
    return site


@router.put("/{site_id}", response_model=SiteSchema)
async def update_site(
    site_id: int,
    site_data: SiteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a site"""
    site = db.query(Site).filter(Site.id == site_id).first()

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify access
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = site_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(site, key, value)

    db.commit()
    db.refresh(site)

    logger.info(f"Site updated: {site.id} - {site.name}")
    return site


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a site (admin only)"""
    site = db.query(Site).filter(Site.id == site_id).first()

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify access
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Clear equipment references to this site first
    db.query(Equipment).filter(Equipment.site_id == site_id).update({"site_id": None})
    db.query(SubEquipment).filter(SubEquipment.site_id == site_id).update({"site_id": None})

    # Delete the site (cascades to buildings, spaces)
    db.delete(site)
    db.commit()

    logger.info(f"Site deleted: {site_id}")


@router.get("/{site_id}/buildings", response_model=List[BuildingSchema])
async def get_site_buildings(
    site_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all buildings for a site"""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify access
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Building).filter(Building.site_id == site_id)

    if is_active is not None:
        query = query.filter(Building.is_active == is_active)

    return query.order_by(Building.name).all()


@router.post("/{site_id}/buildings", response_model=BuildingSchema, status_code=status.HTTP_201_CREATED)
async def create_site_building(
    site_id: int,
    building_data: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new building for a site"""
    # Verify site access
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Override site_id from path
    data = building_data.model_dump()
    data['site_id'] = site_id

    building = Building(**data)
    db.add(building)
    db.commit()
    db.refresh(building)

    logger.info(f"Building created: {building.id} - {building.name}")
    return building


@router.get("/{site_id}/spaces", response_model=List[SpaceSchema])
async def get_site_spaces(
    site_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all spaces directly under a site (not under buildings)"""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify access
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Space).filter(Space.site_id == site_id, Space.building_id == None)

    if is_active is not None:
        query = query.filter(Space.is_active == is_active)

    return query.order_by(Space.name).all()


@router.post("/{site_id}/spaces", response_model=SpaceSchema, status_code=status.HTTP_201_CREATED)
async def create_site_space(
    site_id: int,
    space_data: SpaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new space directly under a site"""
    # Verify site access
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Override site_id from path and ensure no building_id
    data = space_data.model_dump()
    data['site_id'] = site_id
    data['building_id'] = None

    space = Space(**data)
    db.add(space)
    db.commit()
    db.refresh(space)

    logger.info(f"Site space created: {space.id} - {space.name}")
    return space


@router.get("/{site_id}/blocks", response_model=List[BlockSchema])
async def get_site_blocks(
    site_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all blocks for a site"""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify access
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Block).filter(Block.site_id == site_id)

    if is_active is not None:
        query = query.filter(Block.is_active == is_active)

    return query.order_by(Block.name).all()


@router.post("/{site_id}/blocks", response_model=BlockSchema, status_code=status.HTTP_201_CREATED)
async def create_site_block(
    site_id: int,
    block_data: BlockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new block for a site"""
    # Verify site access
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Override site_id from path
    data = block_data.model_dump()
    data['site_id'] = site_id

    block = Block(**data)
    db.add(block)
    db.commit()
    db.refresh(block)

    logger.info(f"Block created: {block.id} - {block.name}")
    return block


# ============================================================================
# Block Endpoints
# ============================================================================

@router.get("/blocks/", response_model=List[BlockSchema])
async def get_blocks(
    site_id: Optional[int] = Query(None, description="Filter by site ID"),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all blocks accessible to the current user"""
    # Get all sites for the company's clients
    company_client_ids = db.query(Client.id).filter(Client.company_id == current_user.company_id)
    site_ids = db.query(Site.id).filter(Site.client_id.in_(company_client_ids))

    query = db.query(Block).filter(Block.site_id.in_(site_ids))

    if site_id is not None:
        query = query.filter(Block.site_id == site_id)

    if is_active is not None:
        query = query.filter(Block.is_active == is_active)

    return query.order_by(Block.name).offset(skip).limit(limit).all()


@router.get("/blocks/{block_id}", response_model=BlockSchema)
async def get_block(
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific block"""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    # Verify access
    site = db.query(Site).filter(Site.id == block.site_id).first()
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return block


@router.put("/blocks/{block_id}", response_model=BlockSchema)
async def update_block(
    block_id: int,
    block_data: BlockUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a block"""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    # Verify access
    site = db.query(Site).filter(Site.id == block.site_id).first()
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Update fields
    update_data = block_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(block, key, value)

    db.commit()
    db.refresh(block)

    logger.info(f"Block updated: {block_id}")
    return block


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a block"""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    # Verify access
    site = db.query(Site).filter(Site.id == block.site_id).first()
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Delete the block (cascades to buildings)
    db.delete(block)
    db.commit()

    logger.info(f"Block deleted: {block_id}")


@router.get("/blocks/{block_id}/buildings", response_model=List[BuildingSchema])
async def get_block_buildings(
    block_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all buildings for a block"""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    # Verify access
    site = db.query(Site).filter(Site.id == block.site_id).first()
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Building).filter(Building.block_id == block_id)

    if is_active is not None:
        query = query.filter(Building.is_active == is_active)

    return query.order_by(Building.name).all()


@router.post("/blocks/{block_id}/buildings", response_model=BuildingSchema, status_code=status.HTTP_201_CREATED)
async def create_block_building(
    block_id: int,
    building_data: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new building for a block"""
    block = db.query(Block).filter(Block.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")

    # Verify access
    site = db.query(Site).filter(Site.id == block.site_id).first()
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Override block_id from path and clear site_id
    data = building_data.model_dump()
    data['block_id'] = block_id
    data['site_id'] = None

    building = Building(**data)
    db.add(building)
    db.commit()
    db.refresh(building)

    logger.info(f"Block building created: {building.id} - {building.name}")
    return building


# ============================================================================
# Building Endpoints
# ============================================================================

@router.get("/buildings/", response_model=List[BuildingSchema])
async def get_buildings(
    site_id: Optional[int] = Query(None, description="Filter by site ID"),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all buildings"""
    # Get all site IDs for user's company
    site_ids = db.query(Site.id).join(Client).filter(
        Client.company_id == current_user.company_id
    ).subquery()

    query = db.query(Building).filter(Building.site_id.in_(site_ids))

    if site_id is not None:
        query = query.filter(Building.site_id == site_id)

    if is_active is not None:
        query = query.filter(Building.is_active == is_active)

    return query.order_by(Building.name).offset(skip).limit(limit).all()


@router.get("/buildings/{building_id}", response_model=BuildingSchema)
async def get_building(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific building"""
    building = db.query(Building).filter(Building.id == building_id).first()

    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # Verify access through site -> client -> company
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return building


@router.post("/buildings/", response_model=BuildingSchema, status_code=status.HTTP_201_CREATED)
async def create_building(
    building_data: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new building"""
    # Verify site access
    site = db.query(Site).filter(Site.id == building_data.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    building = Building(**building_data.model_dump())
    db.add(building)
    db.commit()
    db.refresh(building)

    logger.info(f"Building created: {building.id} - {building.name}")
    return building


@router.put("/buildings/{building_id}", response_model=BuildingSchema)
async def update_building(
    building_id: int,
    building_data: BuildingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a building"""
    building = db.query(Building).filter(Building.id == building_id).first()

    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # Verify access
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = building_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(building, key, value)

    db.commit()
    db.refresh(building)

    logger.info(f"Building updated: {building.id} - {building.name}")
    return building


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(
    building_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a building (admin only)"""
    building = db.query(Building).filter(Building.id == building_id).first()

    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # Verify access
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Clear equipment references to this building first
    db.query(Equipment).filter(Equipment.building_id == building_id).update({"building_id": None})
    db.query(SubEquipment).filter(SubEquipment.building_id == building_id).update({"building_id": None})

    # Clear floor references
    db.query(Floor).filter(Floor.building_id == building_id).update({"building_id": None})

    db.delete(building)
    db.commit()

    logger.info(f"Building deleted: {building_id}")


@router.get("/buildings/{building_id}/floors")
async def get_building_floors(
    building_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all floors for a building"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # Verify access
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Floor).filter(Floor.building_id == building_id)

    if is_active is not None:
        query = query.filter(Floor.is_active == is_active)

    return query.order_by(Floor.level).all()


@router.get("/buildings/{building_id}/spaces", response_model=List[SpaceSchema])
async def get_building_spaces(
    building_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all spaces for a building"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    # Verify access
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Space).filter(Space.building_id == building_id)

    if is_active is not None:
        query = query.filter(Space.is_active == is_active)

    return query.order_by(Space.name).all()


@router.post("/buildings/{building_id}/spaces", response_model=SpaceSchema, status_code=status.HTTP_201_CREATED)
async def create_building_space(
    building_id: int,
    space_data: SpaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new space for a building"""
    # Verify building access
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Override building_id from path
    data = space_data.model_dump()
    data['building_id'] = building_id

    space = Space(**data)
    db.add(space)
    db.commit()
    db.refresh(space)

    logger.info(f"Space created: {space.id} - {space.name}")
    return space


# ============================================================================
# Space Endpoints
# ============================================================================

@router.get("/spaces/", response_model=List[SpaceSchema])
async def get_spaces(
    building_id: Optional[int] = Query(None, description="Filter by building ID"),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all spaces"""
    # Get all building IDs for user's company
    building_ids = db.query(Building.id).join(Site).join(Client).filter(
        Client.company_id == current_user.company_id
    ).subquery()

    query = db.query(Space).filter(Space.building_id.in_(building_ids))

    if building_id is not None:
        query = query.filter(Space.building_id == building_id)

    if is_active is not None:
        query = query.filter(Space.is_active == is_active)

    return query.order_by(Space.name).offset(skip).limit(limit).all()


@router.get("/spaces/{space_id}", response_model=SpaceSchema)
async def get_space(
    space_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific space"""
    space = db.query(Space).filter(Space.id == space_id).first()

    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Verify access - space can be under site directly or under building
    if space.site_id and not space.building_id:
        # Site-level space
        site = db.query(Site).filter(Site.id == space.site_id).first()
    else:
        # Building-level space
        building = db.query(Building).filter(Building.id == space.building_id).first()
        site = get_site_from_building(building, db)

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return space


@router.post("/spaces/", response_model=SpaceSchema, status_code=status.HTTP_201_CREATED)
async def create_space(
    space_data: SpaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new space"""
    # Verify building access
    building = db.query(Building).filter(Building.id == space_data.building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    space = Space(**space_data.model_dump())
    db.add(space)
    db.commit()
    db.refresh(space)

    logger.info(f"Space created: {space.id} - {space.name}")
    return space


@router.put("/spaces/{space_id}", response_model=SpaceSchema)
async def update_space(
    space_id: int,
    space_data: SpaceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a space"""
    space = db.query(Space).filter(Space.id == space_id).first()

    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Verify access - space can be under site directly or under building
    if space.site_id and not space.building_id:
        # Site-level space
        site = db.query(Site).filter(Site.id == space.site_id).first()
    else:
        # Building-level space
        building = db.query(Building).filter(Building.id == space.building_id).first()
        site = get_site_from_building(building, db)

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = space_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(space, key, value)

    db.commit()
    db.refresh(space)

    logger.info(f"Space updated: {space.id} - {space.name}")
    return space


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    space_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a space (admin only)"""
    space = db.query(Space).filter(Space.id == space_id).first()

    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Verify access - space can be under site directly or under building
    if space.site_id and not space.building_id:
        # Site-level space
        site = db.query(Site).filter(Site.id == space.site_id).first()
    else:
        # Building-level space
        building = db.query(Building).filter(Building.id == space.building_id).first()
        site = get_site_from_building(building, db)

    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(space)
    db.commit()

    logger.info(f"Space deleted: {space_id}")


# ============================================================================
# Asset Tree Endpoint (Full hierarchy)
# ============================================================================

@router.get("/{site_id}/asset-tree")
async def get_site_asset_tree(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get complete asset tree for a site including:
    - Buildings
      - Spaces (with equipment)
      - Floors
        - Rooms (with equipment)
          - Equipment (with sub-equipment)
    """
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Verify access
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Build the asset tree
    buildings = db.query(Building).filter(
        Building.site_id == site_id,
        Building.is_active == True
    ).order_by(Building.name).all()

    tree = {
        "site": {
            "id": site.id,
            "name": site.name,
            "code": site.code,
            "client_id": site.client_id
        },
        "buildings": []
    }

    for building in buildings:
        building_data = {
            "id": building.id,
            "name": building.name,
            "code": building.code,
            "building_type": building.building_type,
            "spaces": [],
            "floors": []
        }

        # Get spaces for this building
        spaces = db.query(Space).filter(
            Space.building_id == building.id,
            Space.is_active == True
        ).order_by(Space.name).all()

        for space in spaces:
            space_equipment = db.query(Equipment).filter(
                Equipment.space_id == space.id,
                Equipment.is_active == True
            ).all()

            building_data["spaces"].append({
                "id": space.id,
                "name": space.name,
                "code": space.code,
                "space_type": space.space_type,
                "equipment_count": len(space_equipment),
                "equipment": [{"id": e.id, "name": e.name, "code": e.code, "category": e.category} for e in space_equipment]
            })

        # Get floors for this building
        floors = db.query(Floor).filter(
            Floor.building_id == building.id,
            Floor.is_active == True
        ).order_by(Floor.level).all()

        for floor in floors:
            floor_data = {
                "id": floor.id,
                "name": floor.name,
                "code": floor.code,
                "level": floor.level,
                "rooms": []
            }

            # Get rooms for this floor
            rooms = db.query(Room).filter(
                Room.floor_id == floor.id,
                Room.is_active == True
            ).order_by(Room.name).all()

            for room in rooms:
                room_equipment = db.query(Equipment).filter(
                    Equipment.room_id == room.id,
                    Equipment.is_active == True
                ).all()

                floor_data["rooms"].append({
                    "id": room.id,
                    "name": room.name,
                    "code": room.code,
                    "room_type": room.room_type,
                    "equipment_count": len(room_equipment),
                    "equipment": [{
                        "id": e.id,
                        "name": e.name,
                        "code": e.code,
                        "category": e.category,
                        "sub_equipment_count": db.query(SubEquipment).filter(SubEquipment.equipment_id == e.id).count()
                    } for e in room_equipment]
                })

            building_data["floors"].append(floor_data)

        tree["buildings"].append(building_data)

    return tree


# ============================================================================
# Floor Endpoints
# ============================================================================

@router.post("/buildings/{building_id}/floors", response_model=FloorSchema, status_code=status.HTTP_201_CREATED)
async def create_building_floor(
    building_id: int,
    floor_data: FloorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new floor for a building"""
    building = db.query(Building).filter(Building.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")

    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = floor_data.model_dump()
    data['building_id'] = building_id

    floor = Floor(**data)
    db.add(floor)
    db.commit()
    db.refresh(floor)

    logger.info(f"Floor created: {floor.id} - {floor.name}")
    return floor


@router.get("/floors/{floor_id}", response_model=FloorSchema)
async def get_floor(
    floor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return floor


@router.put("/floors/{floor_id}", response_model=FloorSchema)
async def update_floor(
    floor_id: int,
    floor_data: FloorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = floor_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(floor, key, value)

    db.commit()
    db.refresh(floor)

    logger.info(f"Floor updated: {floor.id} - {floor.name}")
    return floor


@router.delete("/floors/{floor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_floor(
    floor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a floor (admin only)"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Clear equipment references
    db.query(Equipment).filter(Equipment.floor_id == floor_id).update({"floor_id": None})
    db.query(SubEquipment).filter(SubEquipment.floor_id == floor_id).update({"floor_id": None})

    db.delete(floor)
    db.commit()

    logger.info(f"Floor deleted: {floor_id}")


# ============================================================================
# Unit Endpoints
# ============================================================================

@router.get("/floors/{floor_id}/units", response_model=List[UnitSchema])
async def get_floor_units(
    floor_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all units for a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Unit).filter(Unit.floor_id == floor_id)
    if is_active is not None:
        query = query.filter(Unit.is_active == is_active)

    return query.order_by(Unit.name).all()


@router.post("/floors/{floor_id}/units", response_model=UnitSchema, status_code=status.HTTP_201_CREATED)
async def create_floor_unit(
    floor_id: int,
    unit_data: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new unit for a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = unit_data.model_dump()
    data['floor_id'] = floor_id

    unit = Unit(**data)
    db.add(unit)
    db.commit()
    db.refresh(unit)

    logger.info(f"Unit created: {unit.id} - {unit.name}")
    return unit


@router.get("/units/{unit_id}", response_model=UnitSchema)
async def get_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return unit


@router.put("/units/{unit_id}", response_model=UnitSchema)
async def update_unit(
    unit_id: int,
    unit_data: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = unit_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(unit, field, value)

    db.commit()
    db.refresh(unit)

    logger.info(f"Unit updated: {unit.id} - {unit.name}")
    return unit


@router.delete("/units/{unit_id}")
async def delete_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    db.delete(unit)
    db.commit()

    logger.info(f"Unit deleted: {unit_id}")
    return {"message": "Unit deleted successfully"}


# Unit Rooms endpoints
@router.get("/units/{unit_id}/rooms", response_model=List[RoomSchema])
async def get_unit_rooms(
    unit_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all rooms for a unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Room).filter(Room.unit_id == unit_id)
    if is_active is not None:
        query = query.filter(Room.is_active == is_active)

    return query.order_by(Room.name).all()


@router.post("/units/{unit_id}/rooms", response_model=RoomSchema, status_code=status.HTTP_201_CREATED)
async def create_unit_room(
    unit_id: int,
    room_data: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new room for a unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = room_data.model_dump()
    data['unit_id'] = unit_id
    data['floor_id'] = None  # Room is under unit, not directly under floor

    room = Room(**data)
    db.add(room)
    db.commit()
    db.refresh(room)

    logger.info(f"Room created under unit: {room.id} - {room.name}")
    return room


# Unit Equipment endpoints
@router.get("/units/{unit_id}/equipment", response_model=List[EquipmentSchema])
async def get_unit_equipment(
    unit_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all equipment for a unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Equipment).filter(Equipment.unit_id == unit_id)
    if is_active is not None:
        query = query.filter(Equipment.is_active == is_active)

    return query.order_by(Equipment.name).all()


@router.post("/units/{unit_id}/equipment", response_model=EquipmentSchema, status_code=status.HTTP_201_CREATED)
async def create_unit_equipment(
    unit_id: int,
    equipment_data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create equipment for a unit"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = equipment_data.model_dump()
    data['unit_id'] = unit_id
    data['site_id'] = site.id

    equipment = Equipment(**data)
    db.add(equipment)
    db.commit()
    db.refresh(equipment)

    logger.info(f"Equipment created for unit: {equipment.id} - {equipment.name}")
    return equipment


# ============================================================================
# Room Endpoints
# ============================================================================

@router.get("/floors/{floor_id}/rooms", response_model=List[RoomSchema])
async def get_floor_rooms(
    floor_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all rooms for a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Room).filter(Room.floor_id == floor_id)
    if is_active is not None:
        query = query.filter(Room.is_active == is_active)

    return query.order_by(Room.name).all()


@router.post("/floors/{floor_id}/rooms", response_model=RoomSchema, status_code=status.HTTP_201_CREATED)
async def create_floor_room(
    floor_id: int,
    room_data: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new room for a floor"""
    floor = db.query(Floor).filter(Floor.id == floor_id).first()
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = room_data.model_dump()
    data['floor_id'] = floor_id

    room = Room(**data)
    db.add(room)
    db.commit()
    db.refresh(room)

    logger.info(f"Room created: {room.id} - {room.name}")
    return room


@router.get("/rooms/{room_id}", response_model=RoomSchema)
async def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    floor = db.query(Floor).filter(Floor.id == room.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return room


@router.put("/rooms/{room_id}", response_model=RoomSchema)
async def update_room(
    room_id: int,
    room_data: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    floor = db.query(Floor).filter(Floor.id == room.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = room_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(room, key, value)

    db.commit()
    db.refresh(room)

    logger.info(f"Room updated: {room.id} - {room.name}")
    return room


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a room (admin only)"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    floor = db.query(Floor).filter(Floor.id == room.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Clear equipment references
    db.query(Equipment).filter(Equipment.room_id == room_id).update({"room_id": None})
    db.query(SubEquipment).filter(SubEquipment.room_id == room_id).update({"room_id": None})

    db.delete(room)
    db.commit()

    logger.info(f"Room deleted: {room_id}")


# ============================================================================
# Desk Endpoints
# ============================================================================

@router.get("/rooms/{room_id}/desks", response_model=List[DeskSchema])
async def get_room_desks(
    room_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all desks for a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Desk).filter(Desk.room_id == room_id)
    if is_active is not None:
        query = query.filter(Desk.is_active == is_active)

    return query.order_by(Desk.name).all()


@router.post("/rooms/{room_id}/desks", response_model=DeskSchema, status_code=status.HTTP_201_CREATED)
async def create_room_desk(
    room_id: int,
    desk_data: DeskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new desk for a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = desk_data.model_dump()
    data['room_id'] = room_id

    desk = Desk(**data)
    db.add(desk)
    db.commit()
    db.refresh(desk)

    logger.info(f"Desk created: {desk.id} - {desk.name}")
    return desk


@router.get("/desks/{desk_id}", response_model=DeskSchema)
async def get_desk(
    desk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific desk"""
    desk = db.query(Desk).filter(Desk.id == desk_id).first()
    if not desk:
        raise HTTPException(status_code=404, detail="Desk not found")

    room = db.query(Room).filter(Room.id == desk.room_id).first()

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return desk


@router.put("/desks/{desk_id}", response_model=DeskSchema)
async def update_desk(
    desk_id: int,
    desk_data: DeskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a desk"""
    desk = db.query(Desk).filter(Desk.id == desk_id).first()
    if not desk:
        raise HTTPException(status_code=404, detail="Desk not found")

    room = db.query(Room).filter(Room.id == desk.room_id).first()

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    update_data = desk_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(desk, key, value)

    db.commit()
    db.refresh(desk)

    logger.info(f"Desk updated: {desk.id} - {desk.name}")
    return desk


@router.delete("/desks/{desk_id}")
async def delete_desk(
    desk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a desk"""
    desk = db.query(Desk).filter(Desk.id == desk_id).first()
    if not desk:
        raise HTTPException(status_code=404, detail="Desk not found")

    room = db.query(Room).filter(Room.id == desk.room_id).first()

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Clear equipment references to this desk
    db.query(Equipment).filter(Equipment.desk_id == desk_id).update({"desk_id": None})

    db.delete(desk)
    db.commit()

    logger.info(f"Desk deleted: {desk_id}")
    return {"message": "Desk deleted successfully"}


# Desk Equipment endpoints
@router.get("/desks/{desk_id}/equipment", response_model=List[EquipmentSchema])
async def get_desk_equipment(
    desk_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all equipment for a desk"""
    desk = db.query(Desk).filter(Desk.id == desk_id).first()
    if not desk:
        raise HTTPException(status_code=404, detail="Desk not found")

    room = db.query(Room).filter(Room.id == desk.room_id).first()

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Equipment).filter(Equipment.desk_id == desk_id)
    if is_active is not None:
        query = query.filter(Equipment.is_active == is_active)

    return query.order_by(Equipment.name).all()


@router.post("/desks/{desk_id}/equipment", response_model=EquipmentSchema, status_code=status.HTTP_201_CREATED)
async def create_desk_equipment(
    desk_id: int,
    equipment_data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create equipment for a desk"""
    desk = db.query(Desk).filter(Desk.id == desk_id).first()
    if not desk:
        raise HTTPException(status_code=404, detail="Desk not found")

    room = db.query(Room).filter(Room.id == desk.room_id).first()

    # Verify access - room can be under floor or unit
    if room.unit_id:
        unit = db.query(Unit).filter(Unit.id == room.unit_id).first()
        floor = db.query(Floor).filter(Floor.id == unit.floor_id).first()
    else:
        floor = db.query(Floor).filter(Floor.id == room.floor_id).first()

    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = equipment_data.model_dump()
    data['desk_id'] = desk_id
    data['site_id'] = site.id
    # Clear other parent references
    data['client_id'] = None
    data['building_id'] = None
    data['space_id'] = None
    data['floor_id'] = None
    data['unit_id'] = None
    data['room_id'] = None

    equipment = Equipment(**data)
    db.add(equipment)
    db.commit()
    db.refresh(equipment)

    logger.info(f"Equipment created for desk: {equipment.id} - {equipment.name}")
    return equipment


# ============================================================================
# Equipment Endpoints
# ============================================================================

@router.get("/equipment/", response_model=List[EquipmentSchema])
async def get_equipment_list(
    room_id: Optional[int] = Query(None),
    floor_id: Optional[int] = Query(None),
    space_id: Optional[int] = Query(None),
    building_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get equipment list with optional filters"""
    # Get all site IDs for user's company
    site_ids = db.query(Site.id).join(Client).filter(
        Client.company_id == current_user.company_id
    ).subquery()

    query = db.query(Equipment).filter(Equipment.site_id.in_(site_ids))

    if room_id is not None:
        query = query.filter(Equipment.room_id == room_id)
    if floor_id is not None:
        query = query.filter(Equipment.floor_id == floor_id)
    if space_id is not None:
        query = query.filter(Equipment.space_id == space_id)
    if building_id is not None:
        query = query.filter(Equipment.building_id == building_id)
    if site_id is not None:
        query = query.filter(Equipment.site_id == site_id)
    if category is not None:
        query = query.filter(Equipment.category == category)
    if is_active is not None:
        query = query.filter(Equipment.is_active == is_active)

    return query.order_by(Equipment.name).offset(skip).limit(limit).all()


@router.get("/rooms/{room_id}/equipment", response_model=List[EquipmentSchema])
async def get_room_equipment(
    room_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all equipment in a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    floor = db.query(Floor).filter(Floor.id == room.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Equipment).filter(Equipment.room_id == room_id)
    if is_active is not None:
        query = query.filter(Equipment.is_active == is_active)

    return query.order_by(Equipment.name).all()


@router.post("/rooms/{room_id}/equipment", response_model=EquipmentSchema, status_code=status.HTTP_201_CREATED)
async def create_room_equipment(
    room_id: int,
    equipment_data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create equipment in a room"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    floor = db.query(Floor).filter(Floor.id == room.floor_id).first()
    building = db.query(Building).filter(Building.id == floor.building_id).first()
    site = get_site_from_building(building, db)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found for building")
    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = equipment_data.model_dump()
    data['room_id'] = room_id
    data['site_id'] = site.id
    # Clear other parent references
    data['client_id'] = None
    data['building_id'] = None
    data['space_id'] = None
    data['floor_id'] = None

    equipment = Equipment(**data)
    db.add(equipment)
    db.commit()
    db.refresh(equipment)

    logger.info(f"Equipment created: {equipment.id} - {equipment.name}")
    return equipment


@router.get("/spaces/{space_id}/equipment", response_model=List[EquipmentSchema])
async def get_space_equipment(
    space_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all equipment in a space"""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Verify access
    if space.site_id and not space.building_id:
        site = db.query(Site).filter(Site.id == space.site_id).first()
    else:
        building = db.query(Building).filter(Building.id == space.building_id).first()
        site = get_site_from_building(building, db)

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Equipment).filter(Equipment.space_id == space_id)
    if is_active is not None:
        query = query.filter(Equipment.is_active == is_active)

    return query.order_by(Equipment.name).all()


@router.post("/spaces/{space_id}/equipment", response_model=EquipmentSchema, status_code=status.HTTP_201_CREATED)
async def create_space_equipment(
    space_id: int,
    equipment_data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create equipment in a space"""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Verify access
    if space.site_id and not space.building_id:
        site = db.query(Site).filter(Site.id == space.site_id).first()
    else:
        building = db.query(Building).filter(Building.id == space.building_id).first()
        site = get_site_from_building(building, db)

    client = db.query(Client).filter(Client.id == site.client_id).first()
    if not client or client.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    data = equipment_data.model_dump()
    data['space_id'] = space_id
    data['site_id'] = site.id
    # Clear other parent references
    data['client_id'] = None
    data['building_id'] = None
    data['floor_id'] = None
    data['room_id'] = None

    equipment = Equipment(**data)
    db.add(equipment)
    db.commit()
    db.refresh(equipment)

    logger.info(f"Equipment created: {equipment.id} - {equipment.name}")
    return equipment


@router.get("/equipment/{equipment_id}", response_model=EquipmentSchema)
async def get_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific equipment"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    return equipment


@router.put("/equipment/{equipment_id}", response_model=EquipmentSchema)
async def update_equipment(
    equipment_id: int,
    equipment_data: EquipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update equipment"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    update_data = equipment_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(equipment, key, value)

    db.commit()
    db.refresh(equipment)

    logger.info(f"Equipment updated: {equipment.id} - {equipment.name}")
    return equipment


@router.delete("/equipment/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete equipment (admin only)"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    # Delete sub-equipment first
    db.query(SubEquipment).filter(SubEquipment.equipment_id == equipment_id).delete()

    db.delete(equipment)
    db.commit()

    logger.info(f"Equipment deleted: {equipment_id}")


# ============================================================================
# SubEquipment Endpoints
# ============================================================================

@router.get("/equipment/{equipment_id}/sub-equipment", response_model=List[SubEquipmentSchema])
async def get_equipment_sub_equipment(
    equipment_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all sub-equipment for an equipment"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(SubEquipment).filter(SubEquipment.equipment_id == equipment_id)
    if is_active is not None:
        query = query.filter(SubEquipment.is_active == is_active)

    return query.order_by(SubEquipment.name).all()


@router.post("/equipment/{equipment_id}/sub-equipment", response_model=SubEquipmentSchema, status_code=status.HTTP_201_CREATED)
async def create_equipment_sub_equipment(
    equipment_id: int,
    sub_equipment_data: SubEquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create sub-equipment for an equipment"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    data = sub_equipment_data.model_dump()
    data['equipment_id'] = equipment_id
    data['site_id'] = equipment.site_id
    # Clear other parent references
    data['client_id'] = None
    data['building_id'] = None
    data['space_id'] = None
    data['floor_id'] = None
    data['room_id'] = None

    sub_equipment = SubEquipment(**data)
    db.add(sub_equipment)
    db.commit()
    db.refresh(sub_equipment)

    logger.info(f"SubEquipment created: {sub_equipment.id} - {sub_equipment.name}")
    return sub_equipment


@router.get("/sub-equipment/{sub_equipment_id}", response_model=SubEquipmentSchema)
async def get_sub_equipment(
    sub_equipment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific sub-equipment"""
    sub_equipment = db.query(SubEquipment).filter(SubEquipment.id == sub_equipment_id).first()
    if not sub_equipment:
        raise HTTPException(status_code=404, detail="SubEquipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == sub_equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    return sub_equipment


@router.put("/sub-equipment/{sub_equipment_id}", response_model=SubEquipmentSchema)
async def update_sub_equipment(
    sub_equipment_id: int,
    sub_equipment_data: SubEquipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update sub-equipment"""
    sub_equipment = db.query(SubEquipment).filter(SubEquipment.id == sub_equipment_id).first()
    if not sub_equipment:
        raise HTTPException(status_code=404, detail="SubEquipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == sub_equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    update_data = sub_equipment_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(sub_equipment, key, value)

    db.commit()
    db.refresh(sub_equipment)

    logger.info(f"SubEquipment updated: {sub_equipment.id} - {sub_equipment.name}")
    return sub_equipment


@router.delete("/sub-equipment/{sub_equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sub_equipment(
    sub_equipment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete sub-equipment (admin only)"""
    sub_equipment = db.query(SubEquipment).filter(SubEquipment.id == sub_equipment_id).first()
    if not sub_equipment:
        raise HTTPException(status_code=404, detail="SubEquipment not found")

    # Verify access through site
    site = db.query(Site).filter(Site.id == sub_equipment.site_id).first()
    if site:
        client = db.query(Client).filter(Client.id == site.client_id).first()
        if not client or client.company_id != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

    db.delete(sub_equipment)
    db.commit()

    logger.info(f"SubEquipment deleted: {sub_equipment_id}")


# ============================================================================
# Equipment Classes (PM Equipment Classes) Endpoint
# ============================================================================

@router.get("/equipment-classes/")
async def get_equipment_classes(
    is_active: Optional[bool] = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get equipment classes (PM Equipment Classes) for equipment selection"""
    query = db.query(PMEquipmentClass)

    if is_active is not None:
        query = query.filter(PMEquipmentClass.is_active == is_active)

    equipment_classes = query.order_by(PMEquipmentClass.code).all()

    return [{
        "id": ec.id,
        "code": ec.code,
        "name": ec.name,
        "description": ec.description
    } for ec in equipment_classes]
