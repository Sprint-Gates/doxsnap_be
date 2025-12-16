from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal
from app.database import get_db
from app.models import (
    Contract, ContractScope, Scope, Site, Client, User, contract_sites,
    WorkOrder, WorkOrderTimeEntry, WorkOrderSparePart, Equipment, Building, Block, Floor, Room, Unit,
    Technician
)
from app.utils.security import verify_token
from app.schemas import (
    ContractCreate, ContractUpdate, Contract as ContractSchema, ContractList,
    ContractScopeCreate, ContractScopeUpdate, ContractScope as ContractScopeSchema,
    ScopeCreate, ScopeUpdate, Scope as ScopeSchema
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


# ============================================================================
# Scope Reference Endpoints (Admin only for CRUD)
# ============================================================================

@router.get("/scopes/", response_model=List[ScopeSchema])
async def get_scopes(
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all scope types for the company"""
    query = db.query(Scope).filter(Scope.company_id == current_user.company_id)

    if is_active is not None:
        query = query.filter(Scope.is_active == is_active)

    return query.order_by(Scope.sort_order, Scope.name).all()


@router.post("/scopes/", response_model=ScopeSchema, status_code=status.HTTP_201_CREATED)
async def create_scope(
    scope_data: ScopeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new scope type (admin only)"""
    # Check if scope with same name already exists
    existing = db.query(Scope).filter(
        Scope.company_id == current_user.company_id,
        Scope.name == scope_data.name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Scope with this name already exists")

    scope = Scope(
        company_id=current_user.company_id,
        **scope_data.model_dump()
    )
    db.add(scope)
    db.commit()
    db.refresh(scope)

    logger.info(f"Scope created: {scope.id} - {scope.name}")
    return scope


@router.put("/scopes/{scope_id}", response_model=ScopeSchema)
async def update_scope(
    scope_id: int,
    scope_data: ScopeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a scope type (admin only)"""
    scope = db.query(Scope).filter(
        Scope.id == scope_id,
        Scope.company_id == current_user.company_id
    ).first()

    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    update_data = scope_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(scope, key, value)

    db.commit()
    db.refresh(scope)

    logger.info(f"Scope updated: {scope.id} - {scope.name}")
    return scope


@router.delete("/scopes/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scope(
    scope_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a scope type (admin only)"""
    scope = db.query(Scope).filter(
        Scope.id == scope_id,
        Scope.company_id == current_user.company_id
    ).first()

    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    # Check if scope is used in any contracts
    used_count = db.query(ContractScope).filter(ContractScope.scope_id == scope_id).count()
    if used_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete scope. It is used in {used_count} contract(s)"
        )

    db.delete(scope)
    db.commit()

    logger.info(f"Scope deleted: {scope_id}")


@router.post("/scopes/seed", response_model=List[ScopeSchema])
async def seed_default_scopes(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Seed default scope types for the company (admin only)"""
    default_scopes = [
        {"name": "HVAC", "code": "HVAC", "sort_order": 1},
        {"name": "Spare Parts", "code": "SPARE", "sort_order": 2},
        {"name": "Labor", "code": "LABOR", "sort_order": 3},
        {"name": "Subcontractor", "code": "SUB", "sort_order": 4},
        {"name": "Electrical", "code": "ELEC", "sort_order": 5},
        {"name": "Plumbing", "code": "PLUMB", "sort_order": 6},
        {"name": "Fire Safety", "code": "FIRE", "sort_order": 7},
        {"name": "Civil", "code": "CIVIL", "sort_order": 8},
        {"name": "Mechanical", "code": "MECH", "sort_order": 9},
    ]

    created_scopes = []
    for scope_data in default_scopes:
        # Check if already exists
        existing = db.query(Scope).filter(
            Scope.company_id == current_user.company_id,
            Scope.name == scope_data["name"]
        ).first()

        if not existing:
            scope = Scope(
                company_id=current_user.company_id,
                **scope_data
            )
            db.add(scope)
            created_scopes.append(scope)

    db.commit()

    # Refresh all created scopes
    for scope in created_scopes:
        db.refresh(scope)

    logger.info(f"Seeded {len(created_scopes)} default scopes")
    return created_scopes


# ============================================================================
# Contract Endpoints
# ============================================================================

@router.get("/", response_model=List[ContractSchema])
async def get_contracts(
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    site_id: Optional[int] = Query(None, description="Filter by site ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    contract_type: Optional[str] = Query(None, description="Filter by contract type"),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all contracts for the company"""
    query = db.query(Contract).filter(Contract.company_id == current_user.company_id)

    if client_id is not None:
        query = query.filter(Contract.client_id == client_id)

    if site_id is not None:
        # Filter contracts that include the specified site
        query = query.join(contract_sites).filter(contract_sites.c.site_id == site_id)

    if status_filter is not None:
        query = query.filter(Contract.status == status_filter)

    if contract_type is not None:
        query = query.filter(Contract.contract_type == contract_type)

    if is_active is not None:
        query = query.filter(Contract.is_active == is_active)

    contracts = query.options(
        joinedload(Contract.sites),
        joinedload(Contract.scopes).joinedload(ContractScope.scope)
    ).order_by(Contract.start_date.desc()).offset(skip).limit(limit).all()

    return contracts


@router.get("/expiring")
async def get_expiring_contracts(
    days: int = Query(30, description="Number of days to check for expiring contracts"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get contracts expiring within specified days"""
    from datetime import timedelta

    end_date_threshold = date.today() + timedelta(days=days)

    contracts = db.query(Contract).filter(
        Contract.company_id == current_user.company_id,
        Contract.is_active == True,
        Contract.status == "active",
        Contract.end_date <= end_date_threshold,
        Contract.end_date >= date.today()
    ).options(
        joinedload(Contract.client),
        joinedload(Contract.sites)
    ).order_by(Contract.end_date).all()

    return [{
        "id": c.id,
        "contract_number": c.contract_number,
        "name": c.name,
        "client_name": c.client.name if c.client else None,
        "end_date": c.end_date,
        "days_remaining": (c.end_date - date.today()).days,
        "is_renewable": c.is_renewable,
        "auto_renew": c.auto_renew,
        "contract_value": float(c.contract_value) if c.contract_value else None
    } for c in contracts]


@router.get("/{contract_id}", response_model=ContractSchema)
async def get_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).options(
        joinedload(Contract.sites),
        joinedload(Contract.scopes).joinedload(ContractScope.scope)
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    return contract


@router.post("/", response_model=ContractSchema, status_code=status.HTTP_201_CREATED)
async def create_contract(
    contract_data: ContractCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new contract"""
    # Verify client belongs to company
    client = db.query(Client).filter(
        Client.id == contract_data.client_id,
        Client.company_id == current_user.company_id
    ).first()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found or access denied")

    # Validate dates
    if contract_data.end_date <= contract_data.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    # Validate contract type specific fields
    if contract_data.contract_type == "with_threshold" and not contract_data.threshold_amount:
        raise HTTPException(
            status_code=400,
            detail="Threshold amount is required for 'with_threshold' contract type"
        )

    # Extract nested data
    site_ids = contract_data.site_ids or []
    scopes_data = contract_data.scopes or []

    # Create contract (exclude nested fields)
    contract_dict = contract_data.model_dump(exclude={"site_ids", "scopes"})
    contract = Contract(
        company_id=current_user.company_id,
        created_by=current_user.id,
        **contract_dict
    )
    db.add(contract)
    db.flush()  # Get contract ID

    # Add sites
    if site_ids:
        sites = db.query(Site).filter(
            Site.id.in_(site_ids),
            Site.client_id == contract_data.client_id
        ).all()

        if len(sites) != len(site_ids):
            raise HTTPException(status_code=400, detail="Some sites not found or don't belong to the client")

        contract.sites = sites

    # Add scopes with SLA
    for scope_data in scopes_data:
        # Verify scope exists and belongs to company
        scope = db.query(Scope).filter(
            Scope.id == scope_data.scope_id,
            Scope.company_id == current_user.company_id
        ).first()

        if not scope:
            raise HTTPException(status_code=400, detail=f"Scope {scope_data.scope_id} not found")

        contract_scope = ContractScope(
            contract_id=contract.id,
            **scope_data.model_dump()
        )
        db.add(contract_scope)

    db.commit()
    db.refresh(contract)

    # Reload with relationships
    contract = db.query(Contract).filter(Contract.id == contract.id).options(
        joinedload(Contract.sites),
        joinedload(Contract.scopes).joinedload(ContractScope.scope)
    ).first()

    logger.info(f"Contract created: {contract.id} - {contract.contract_number}")
    return contract


@router.put("/{contract_id}", response_model=ContractSchema)
async def update_contract(
    contract_id: int,
    contract_data: ContractUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Get update data excluding nested fields
    update_data = contract_data.model_dump(exclude_unset=True, exclude={"site_ids", "scopes"})

    # Validate dates if both are provided
    new_start = update_data.get("start_date", contract.start_date)
    new_end = update_data.get("end_date", contract.end_date)
    if new_end <= new_start:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    # Update basic fields
    for key, value in update_data.items():
        setattr(contract, key, value)

    contract.updated_by = current_user.id

    # Update sites if provided
    if contract_data.site_ids is not None:
        sites = db.query(Site).filter(
            Site.id.in_(contract_data.site_ids),
            Site.client_id == contract.client_id
        ).all()
        contract.sites = sites

    # Update scopes if provided
    if contract_data.scopes is not None:
        # Remove existing scopes
        db.query(ContractScope).filter(ContractScope.contract_id == contract.id).delete()

        # Add new scopes
        for scope_data in contract_data.scopes:
            scope = db.query(Scope).filter(
                Scope.id == scope_data.scope_id,
                Scope.company_id == current_user.company_id
            ).first()

            if scope:
                contract_scope = ContractScope(
                    contract_id=contract.id,
                    **scope_data.model_dump()
                )
                db.add(contract_scope)

    db.commit()
    db.refresh(contract)

    # Reload with relationships
    contract = db.query(Contract).filter(Contract.id == contract.id).options(
        joinedload(Contract.sites),
        joinedload(Contract.scopes).joinedload(ContractScope.scope)
    ).first()

    logger.info(f"Contract updated: {contract.id} - {contract.contract_number}")
    return contract


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a contract (admin only)"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    db.delete(contract)
    db.commit()

    logger.info(f"Contract deleted: {contract_id}")


@router.post("/{contract_id}/activate")
async def activate_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Activate a draft contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft contracts can be activated")

    contract.status = "active"
    contract.updated_by = current_user.id
    db.commit()

    logger.info(f"Contract activated: {contract_id}")
    return {"message": "Contract activated successfully", "status": "active"}


@router.post("/{contract_id}/terminate")
async def terminate_contract(
    contract_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Terminate a contract (admin only)"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if contract.status in ["terminated", "expired"]:
        raise HTTPException(status_code=400, detail="Contract is already terminated or expired")

    contract.status = "terminated"
    contract.updated_by = current_user.id
    if reason:
        contract.notes = (contract.notes or "") + f"\n[Terminated: {reason}]"
    db.commit()

    logger.info(f"Contract terminated: {contract_id}")
    return {"message": "Contract terminated successfully", "status": "terminated"}


@router.post("/{contract_id}/renew", response_model=ContractSchema)
async def renew_contract(
    contract_id: int,
    new_end_date: date,
    new_value: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Renew a contract by extending end date and optionally updating value"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    if not contract.is_renewable:
        raise HTTPException(status_code=400, detail="Contract is not renewable")

    if new_end_date <= contract.end_date:
        raise HTTPException(status_code=400, detail="New end date must be after current end date")

    # Update contract
    old_end_date = contract.end_date
    contract.end_date = new_end_date
    contract.status = "renewed"

    if new_value is not None:
        contract.contract_value = new_value

    contract.updated_by = current_user.id
    contract.notes = (contract.notes or "") + f"\n[Renewed on {date.today()}: Extended from {old_end_date} to {new_end_date}]"

    db.commit()
    db.refresh(contract)

    logger.info(f"Contract renewed: {contract_id}")
    return contract


# ============================================================================
# Contract Scope Endpoints
# ============================================================================

@router.get("/{contract_id}/scopes", response_model=List[ContractScopeSchema])
async def get_contract_scopes(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all scopes for a contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    scopes = db.query(ContractScope).filter(
        ContractScope.contract_id == contract_id
    ).options(joinedload(ContractScope.scope)).all()

    return scopes


@router.post("/{contract_id}/scopes", response_model=ContractScopeSchema, status_code=status.HTTP_201_CREATED)
async def add_contract_scope(
    contract_id: int,
    scope_data: ContractScopeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a scope to a contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Verify scope exists
    scope = db.query(Scope).filter(
        Scope.id == scope_data.scope_id,
        Scope.company_id == current_user.company_id
    ).first()

    if not scope:
        raise HTTPException(status_code=404, detail="Scope not found")

    # Check if scope already exists in contract
    existing = db.query(ContractScope).filter(
        ContractScope.contract_id == contract_id,
        ContractScope.scope_id == scope_data.scope_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Scope already exists in this contract")

    contract_scope = ContractScope(
        contract_id=contract_id,
        **scope_data.model_dump()
    )
    db.add(contract_scope)
    db.commit()
    db.refresh(contract_scope)

    logger.info(f"Scope added to contract {contract_id}: {scope_data.scope_id}")
    return contract_scope


@router.put("/{contract_id}/scopes/{scope_id}", response_model=ContractScopeSchema)
async def update_contract_scope(
    contract_id: int,
    scope_id: int,
    scope_data: ContractScopeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a scope's SLA within a contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract_scope = db.query(ContractScope).filter(
        ContractScope.contract_id == contract_id,
        ContractScope.scope_id == scope_id
    ).first()

    if not contract_scope:
        raise HTTPException(status_code=404, detail="Scope not found in this contract")

    update_data = scope_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(contract_scope, key, value)

    db.commit()
    db.refresh(contract_scope)

    logger.info(f"Contract scope updated: contract {contract_id}, scope {scope_id}")
    return contract_scope


@router.delete("/{contract_id}/scopes/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_contract_scope(
    contract_id: int,
    scope_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove a scope from a contract"""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    contract_scope = db.query(ContractScope).filter(
        ContractScope.contract_id == contract_id,
        ContractScope.scope_id == scope_id
    ).first()

    if not contract_scope:
        raise HTTPException(status_code=404, detail="Scope not found in this contract")

    db.delete(contract_scope)
    db.commit()

    logger.info(f"Scope removed from contract {contract_id}: {scope_id}")


# ============================================================================
# Cost Center Breakdown Endpoint
# ============================================================================

def decimal_to_float(val):
    """Convert Decimal to float safely"""
    if val is None:
        return 0
    if isinstance(val, Decimal):
        return float(val)
    return val


def get_equipment_ids_for_sites(db: Session, site_ids: List[int]) -> List[int]:
    """Get all equipment IDs belonging to sites through any hierarchy path"""
    if not site_ids:
        return []

    # Direct equipment on sites
    direct_equipment = db.query(Equipment.id).filter(Equipment.site_id.in_(site_ids)).all()
    equipment_ids = set([e[0] for e in direct_equipment])

    # Get all buildings for these sites (direct and via blocks)
    direct_building_ids = db.query(Building.id).filter(Building.site_id.in_(site_ids)).all()
    direct_building_ids = [b[0] for b in direct_building_ids]

    # Buildings via blocks
    block_ids = db.query(Block.id).filter(Block.site_id.in_(site_ids)).all()
    block_ids = [b[0] for b in block_ids]

    block_building_ids = []
    if block_ids:
        block_building_ids = db.query(Building.id).filter(Building.block_id.in_(block_ids)).all()
        block_building_ids = [b[0] for b in block_building_ids]

    all_building_ids = list(set(direct_building_ids + block_building_ids))

    # Equipment directly on buildings
    if all_building_ids:
        building_equipment = db.query(Equipment.id).filter(Equipment.building_id.in_(all_building_ids)).all()
        equipment_ids.update([e[0] for e in building_equipment])

    # Get all floor IDs for these buildings
    floor_ids = []
    if all_building_ids:
        floor_ids = db.query(Floor.id).filter(Floor.building_id.in_(all_building_ids)).all()
        floor_ids = [f[0] for f in floor_ids]

    # Equipment directly on floors
    if floor_ids:
        floor_equipment = db.query(Equipment.id).filter(Equipment.floor_id.in_(floor_ids)).all()
        equipment_ids.update([e[0] for e in floor_equipment])

    # Get all unit IDs for these floors
    unit_ids = []
    if floor_ids:
        unit_ids = db.query(Unit.id).filter(Unit.floor_id.in_(floor_ids)).all()
        unit_ids = [u[0] for u in unit_ids]

    # Equipment directly on units
    if unit_ids:
        unit_equipment = db.query(Equipment.id).filter(Equipment.unit_id.in_(unit_ids)).all()
        equipment_ids.update([e[0] for e in unit_equipment])

    # Get all room IDs for these floors
    room_ids = []
    if floor_ids:
        room_ids = db.query(Room.id).filter(Room.floor_id.in_(floor_ids)).all()
        room_ids = [r[0] for r in room_ids]

    # Equipment directly on rooms
    if room_ids:
        room_equipment = db.query(Equipment.id).filter(Equipment.room_id.in_(room_ids)).all()
        equipment_ids.update([e[0] for e in room_equipment])

    return list(equipment_ids)


@router.get("/{contract_id}/cost-center")
async def get_contract_cost_center(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get cost center breakdown for a contract"""
    # Get contract with sites
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.company_id == current_user.company_id
    ).options(
        joinedload(Contract.sites),
        joinedload(Contract.client)
    ).first()

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Get site IDs covered by this contract
    site_ids = [site.id for site in contract.sites]

    if not site_ids:
        # No sites, return empty cost center
        return {
            "contract": {
                "id": contract.id,
                "contract_number": contract.contract_number,
                "name": contract.name,
                "client_name": contract.client.name if contract.client else None,
                "budget": decimal_to_float(contract.budget),
                "contract_value": decimal_to_float(contract.contract_value),
                "currency": contract.currency,
                "status": contract.status
            },
            "summary": {
                "total_work_orders": 0,
                "work_orders_by_status": {},
                "work_orders_by_type": {},
                "total_labor_hours": 0,
                "labor_cost": 0,
                "parts_cost": 0,
                "total_cost": 0,
                "billable_amount": 0,
                "budget_used": 0,
                "budget_remaining": decimal_to_float(contract.budget) if contract.budget else None,
                "budget_used_percent": 0
            },
            "sites_breakdown": [],
            "labor_by_technician": [],
            "work_orders": []
        }

    # Get all equipment IDs for these sites
    equipment_ids = get_equipment_ids_for_sites(db, site_ids)

    # Get all work orders for equipment in these sites
    work_orders = []
    if equipment_ids:
        work_orders = db.query(WorkOrder).filter(
            WorkOrder.company_id == current_user.company_id,
            WorkOrder.equipment_id.in_(equipment_ids)
        ).all()

    wo_ids = [wo.id for wo in work_orders]

    # Calculate labor costs from time entries
    labor_stats = db.query(
        func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('total_hours'),
        func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('total_cost'),
        func.count(WorkOrderTimeEntry.id).label('entries_count')
    ).filter(
        WorkOrderTimeEntry.work_order_id.in_(wo_ids) if wo_ids else False
    ).first()

    # Calculate parts costs
    parts_stats = db.query(
        func.coalesce(func.sum(WorkOrderSparePart.total_cost), 0).label('total_cost'),
        func.coalesce(func.sum(WorkOrderSparePart.quantity), 0).label('total_quantity'),
        func.count(WorkOrderSparePart.id).label('parts_count')
    ).filter(
        WorkOrderSparePart.work_order_id.in_(wo_ids) if wo_ids else False
    ).first()

    # Work order stats by status and type
    wo_by_status = {}
    wo_by_type = {}
    total_billable_amount = 0

    for wo in work_orders:
        wo_by_status[wo.status] = wo_by_status.get(wo.status, 0) + 1
        wo_by_type[wo.work_order_type] = wo_by_type.get(wo.work_order_type, 0) + 1
        if wo.is_billable and wo.billable_amount:
            total_billable_amount += float(wo.billable_amount)

    # Get labor breakdown by technician
    technician_labor = []
    if wo_ids:
        technician_labor = db.query(
            WorkOrderTimeEntry.technician_id,
            func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('hours'),
            func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('cost')
        ).filter(
            WorkOrderTimeEntry.work_order_id.in_(wo_ids)
        ).group_by(WorkOrderTimeEntry.technician_id).all()

    # Get technician names
    tech_names = {}
    if technician_labor:
        tech_ids = [t.technician_id for t in technician_labor if t.technician_id]
        if tech_ids:
            technicians = db.query(Technician).filter(Technician.id.in_(tech_ids)).all()
            tech_names = {t.id: t.name for t in technicians}

    labor_by_technician = [
        {
            "technician_id": t.technician_id,
            "technician_name": tech_names.get(t.technician_id, "Unknown"),
            "hours": decimal_to_float(t.hours),
            "cost": decimal_to_float(t.cost)
        }
        for t in technician_labor if t.technician_id
    ]

    # Get work order details
    wo_details = []
    for wo in work_orders:
        # Get labor cost for this WO
        wo_labor = db.query(
            func.coalesce(func.sum(WorkOrderTimeEntry.hours_worked), 0).label('hours'),
            func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0).label('cost')
        ).filter(WorkOrderTimeEntry.work_order_id == wo.id).first()

        # Get parts cost for this WO
        wo_parts = db.query(
            func.coalesce(func.sum(WorkOrderSparePart.total_cost), 0).label('cost')
        ).filter(WorkOrderSparePart.work_order_id == wo.id).first()

        labor_cost = decimal_to_float(wo_labor.cost) if wo_labor else 0
        parts_cost = decimal_to_float(wo_parts.cost) if wo_parts else 0
        total_cost = labor_cost + parts_cost

        # Get equipment info
        equipment_name = None
        equipment_code = None
        if wo.equipment_id:
            equipment = db.query(Equipment).filter(Equipment.id == wo.equipment_id).first()
            if equipment:
                equipment_name = equipment.name
                equipment_code = equipment.code

        wo_details.append({
            "id": wo.id,
            "work_order_number": wo.wo_number,
            "title": wo.title,
            "type": wo.work_order_type,
            "status": wo.status,
            "priority": wo.priority,
            "is_billable": wo.is_billable,
            "equipment_name": equipment_name,
            "equipment_code": equipment_code,
            "labor_hours": decimal_to_float(wo_labor.hours) if wo_labor else 0,
            "labor_cost": labor_cost,
            "parts_cost": parts_cost,
            "total_cost": total_cost,
            "billable_amount": decimal_to_float(wo.billable_amount) or 0,
            "created_at": wo.created_at.isoformat() if wo.created_at else None,
            "completed_at": wo.actual_end.isoformat() if wo.actual_end else None
        })

    # Calculate totals
    total_labor_cost = decimal_to_float(labor_stats.total_cost) if labor_stats else 0
    total_parts_cost = decimal_to_float(parts_stats.total_cost) if parts_stats else 0
    total_cost = total_labor_cost + total_parts_cost

    # Budget calculations
    budget = decimal_to_float(contract.budget) if contract.budget else None
    budget_remaining = (budget - total_cost) if budget else None
    budget_used_percent = round((total_cost / budget * 100), 1) if budget and budget > 0 else None

    # Sites breakdown
    sites_breakdown = []
    for site in contract.sites:
        # Get equipment count for this site
        site_equipment_ids = get_equipment_ids_for_sites(db, [site.id])

        # Get WO count for this site
        site_wo_count = 0
        site_labor_cost = 0
        site_parts_cost = 0

        if site_equipment_ids:
            site_wos = db.query(WorkOrder).filter(
                WorkOrder.company_id == current_user.company_id,
                WorkOrder.equipment_id.in_(site_equipment_ids)
            ).all()
            site_wo_count = len(site_wos)
            site_wo_ids = [w.id for w in site_wos]

            if site_wo_ids:
                site_labor = db.query(
                    func.coalesce(func.sum(WorkOrderTimeEntry.total_cost), 0)
                ).filter(WorkOrderTimeEntry.work_order_id.in_(site_wo_ids)).scalar()
                site_labor_cost = decimal_to_float(site_labor) or 0

                site_parts = db.query(
                    func.coalesce(func.sum(WorkOrderSparePart.total_cost), 0)
                ).filter(WorkOrderSparePart.work_order_id.in_(site_wo_ids)).scalar()
                site_parts_cost = decimal_to_float(site_parts) or 0

        sites_breakdown.append({
            "site_id": site.id,
            "site_name": site.name,
            "site_code": site.code,
            "equipment_count": len(site_equipment_ids),
            "work_order_count": site_wo_count,
            "labor_cost": site_labor_cost,
            "parts_cost": site_parts_cost,
            "total_cost": site_labor_cost + site_parts_cost
        })

    return {
        "contract": {
            "id": contract.id,
            "contract_number": contract.contract_number,
            "name": contract.name,
            "client_name": contract.client.name if contract.client else None,
            "budget": decimal_to_float(contract.budget),
            "contract_value": decimal_to_float(contract.contract_value),
            "currency": contract.currency,
            "status": contract.status,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None
        },
        "summary": {
            "total_work_orders": len(work_orders),
            "work_orders_by_status": wo_by_status,
            "work_orders_by_type": wo_by_type,
            "total_labor_hours": decimal_to_float(labor_stats.total_hours) if labor_stats else 0,
            "labor_cost": total_labor_cost,
            "parts_cost": total_parts_cost,
            "total_cost": total_cost,
            "billable_amount": total_billable_amount,
            "budget_used": total_cost,
            "budget_remaining": budget_remaining,
            "budget_used_percent": budget_used_percent
        },
        "sites_breakdown": sites_breakdown,
        "labor_by_technician": labor_by_technician,
        "work_orders": wo_details
    }
