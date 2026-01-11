from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal
from app.database import get_db
from app.models import (
    Contract, ContractScope, Scope, Site, Client, User, contract_sites, AddressBook,
    WorkOrder, WorkOrderTimeEntry, WorkOrderSparePart, Equipment, Building, Block, Floor, Room, Unit,
    Technician, PettyCashTransaction, InvoiceAllocation, AllocationPeriod, ProcessedImage,
    JournalEntry, JournalEntryLine, Account, AccountType
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
    client_id: Optional[int] = Query(None, description="Filter by client ID (legacy)"),
    address_book_id: Optional[int] = Query(None, description="Filter by Address Book ID (customer)"),
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

    # Support filtering by address_book_id (new) or client_id (legacy)
    if address_book_id is not None:
        query = query.filter(Contract.address_book_id == address_book_id)
    elif client_id is not None:
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
    # Verify client/address_book entry belongs to company
    # Support both legacy client_id and new address_book_id
    address_book_entry = None
    client = None

    if contract_data.address_book_id:
        # New approach: Use Address Book
        address_book_entry = db.query(AddressBook).filter(
            AddressBook.id == contract_data.address_book_id,
            AddressBook.company_id == current_user.company_id,
            AddressBook.search_type == 'C'  # Customer type
        ).first()
        if not address_book_entry:
            raise HTTPException(status_code=404, detail="Customer not found or access denied")
    elif contract_data.client_id:
        # Legacy approach: Use Client table
        client = db.query(Client).filter(
            Client.id == contract_data.client_id,
            Client.company_id == current_user.company_id
        ).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found or access denied")
    else:
        raise HTTPException(status_code=400, detail="Either client_id or address_book_id is required")

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

    # Ensure address_book_id is set for new contracts
    if contract_data.address_book_id and not contract_dict.get('address_book_id'):
        contract_dict['address_book_id'] = contract_data.address_book_id

    contract = Contract(
        company_id=current_user.company_id,
        created_by=current_user.id,
        **contract_dict
    )
    db.add(contract)
    db.flush()  # Get contract ID

    # Add sites
    if site_ids:
        # Build site filter based on whether we're using address_book_id or client_id
        site_query = db.query(Site).filter(Site.id.in_(site_ids))
        if contract_data.address_book_id:
            site_query = site_query.filter(Site.address_book_id == contract_data.address_book_id)
        elif contract_data.client_id:
            site_query = site_query.filter(Site.client_id == contract_data.client_id)

        sites = site_query.all()

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

    # Get all equipment IDs for these sites (empty list if no sites)
    equipment_ids = get_equipment_ids_for_sites(db, site_ids) if site_ids else []

    # Get ALL site IDs for this client (address_book_id) - not just contract-covered sites
    # This allows work orders for ANY site belonging to the same client to show in cost center
    all_client_site_ids = []
    if contract.address_book_id:
        all_client_sites = db.query(Site.id).filter(
            Site.company_id == current_user.company_id,
            Site.address_book_id == contract.address_book_id
        ).all()
        all_client_site_ids = [s.id for s in all_client_sites]

    # Get all equipment IDs for ALL client sites
    all_client_equipment_ids = get_equipment_ids_for_sites(db, all_client_site_ids) if all_client_site_ids else []

    # Get all work orders for this contract/client
    # Include work orders linked via:
    # 1. Direct contract_id
    # 2. Direct site_id (for ANY site belonging to the same client)
    # 3. Equipment in ANY site belonging to the same client
    work_orders = []

    # Build the OR conditions for work order query
    wo_conditions = [WorkOrder.contract_id == contract_id]

    if all_client_site_ids:
        wo_conditions.append(WorkOrder.site_id.in_(all_client_site_ids))

    if all_client_equipment_ids:
        wo_conditions.append(WorkOrder.equipment_id.in_(all_client_equipment_ids))

    work_orders = db.query(WorkOrder).filter(
        WorkOrder.company_id == current_user.company_id,
        or_(*wo_conditions)
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

    # Get petty cash transactions linked to this contract
    petty_cash_stats = db.query(
        func.count(PettyCashTransaction.id).label('transaction_count'),
        func.coalesce(func.sum(PettyCashTransaction.amount), 0).label('total_amount')
    ).filter(
        PettyCashTransaction.company_id == current_user.company_id,
        PettyCashTransaction.contract_id == contract_id,
        PettyCashTransaction.status == 'approved'
    ).first()

    petty_cash_cost = decimal_to_float(petty_cash_stats.total_amount) if petty_cash_stats else 0

    # Get invoice allocations linked to this contract
    allocations = db.query(InvoiceAllocation).filter(
        InvoiceAllocation.contract_id == contract_id,
        InvoiceAllocation.status == 'active'
    ).options(joinedload(InvoiceAllocation.periods)).all()

    total_allocated = Decimal("0")
    total_recognized = Decimal("0")
    total_pending = Decimal("0")
    allocation_count = len(allocations)

    allocation_details = []
    monthly_distribution = {}  # {month_key: {recognized, pending}}

    for allocation in allocations:
        total_allocated += allocation.total_amount

        # Get invoice info
        invoice = db.query(ProcessedImage).filter(ProcessedImage.id == allocation.invoice_id).first()
        invoice_number = None
        vendor_name = None
        if invoice and invoice.structured_data:
            import json
            try:
                data = json.loads(invoice.structured_data)
                invoice_number = data.get("invoice_number")
                vendor_name = data.get("vendor_name") or data.get("vendor")
            except:
                pass

        period_details = []
        for period in allocation.periods:
            if period.is_recognized:
                total_recognized += period.amount
            else:
                total_pending += period.amount

            # Track monthly distribution
            month_key = period.period_start.strftime("%Y-%m")
            if month_key not in monthly_distribution:
                monthly_distribution[month_key] = {"recognized": Decimal("0"), "pending": Decimal("0")}
            if period.is_recognized:
                monthly_distribution[month_key]["recognized"] += period.amount
            else:
                monthly_distribution[month_key]["pending"] += period.amount

            period_details.append({
                "id": period.id,
                "period_start": period.period_start.isoformat() if period.period_start else None,
                "period_end": period.period_end.isoformat() if period.period_end else None,
                "period_number": period.period_number,
                "amount": decimal_to_float(period.amount),
                "is_recognized": period.is_recognized
            })

        allocation_details.append({
            "id": allocation.id,
            "invoice_id": allocation.invoice_id,
            "invoice_number": invoice_number,
            "vendor_name": vendor_name,
            "total_amount": decimal_to_float(allocation.total_amount),
            "distribution_type": allocation.distribution_type,
            "start_date": allocation.start_date.isoformat() if allocation.start_date else None,
            "end_date": allocation.end_date.isoformat() if allocation.end_date else None,
            "periods": period_details
        })

    # Convert monthly distribution to sorted list
    monthly_breakdown = [
        {
            "month": month,
            "recognized": decimal_to_float(amounts["recognized"]),
            "pending": decimal_to_float(amounts["pending"]),
            "total": decimal_to_float(amounts["recognized"] + amounts["pending"])
        }
        for month, amounts in sorted(monthly_distribution.items())
    ]

    subcontractor_cost = decimal_to_float(total_recognized)

    # ========== ACCOUNTING LEDGER INTEGRATION ==========
    # Get accounting data from journal entries for the contract's sites
    ledger_summary = {
        "total_debits": 0.0,
        "total_credits": 0.0,
        "revenue": 0.0,
        "expenses": 0.0,
        "net_income": 0.0,
        "entries_by_account": [],
        "recent_entries": []
    }

    # Get account types for categorization
    account_types_map = {}
    account_types = db.query(AccountType).filter(
        AccountType.company_id == current_user.company_id
    ).all()
    for at in account_types:
        account_types_map[at.id] = at.code

    # Build filter for journal entry lines
    # Include lines linked via: site_id (for contract sites) OR contract_id (direct)
    je_line_conditions = [JournalEntryLine.contract_id == contract_id]
    if site_ids:
        je_line_conditions.append(JournalEntryLine.site_id.in_(site_ids))

    # Get totals by account for this contract
    account_totals = db.query(
        Account.id,
        Account.code,
        Account.name,
        Account.account_type_id,
        func.coalesce(func.sum(JournalEntryLine.debit), 0).label('total_debit'),
        func.coalesce(func.sum(JournalEntryLine.credit), 0).label('total_credit')
    ).join(
        JournalEntryLine, Account.id == JournalEntryLine.account_id
    ).join(
        JournalEntry, and_(
            JournalEntryLine.journal_entry_id == JournalEntry.id,
            JournalEntry.status == "posted"
        )
    ).filter(
        Account.company_id == current_user.company_id,
        or_(*je_line_conditions)
    ).group_by(
        Account.id, Account.code, Account.name, Account.account_type_id
    ).order_by(Account.code).all()

    entries_by_account = []
    total_ledger_debits = 0.0
    total_ledger_credits = 0.0
    total_revenue = 0.0
    total_expenses = 0.0

    for row in account_totals:
        debit = decimal_to_float(row.total_debit) or 0.0
        credit = decimal_to_float(row.total_credit) or 0.0
        balance = debit - credit

        account_type_code = account_types_map.get(row.account_type_id, "")

        # Categorize by account type
        if account_type_code == "REVENUE":
            # Revenue has credit normal balance
            total_revenue += credit - debit
        elif account_type_code == "EXPENSE":
            # Expense has debit normal balance
            total_expenses += debit - credit

        total_ledger_debits += debit
        total_ledger_credits += credit

        entries_by_account.append({
            "account_id": row.id,
            "account_code": row.code,
            "account_name": row.name,
            "account_type": account_type_code,
            "total_debit": debit,
            "total_credit": credit,
            "balance": balance
        })

    # Get recent journal entries for this contract
    recent_entries_query = db.query(JournalEntry).join(
        JournalEntryLine
    ).filter(
        JournalEntry.company_id == current_user.company_id,
        JournalEntry.status == "posted",
        or_(*je_line_conditions)
    ).distinct().order_by(
        JournalEntry.entry_date.desc()
    ).limit(10).all()

    recent_entries = []
    for entry in recent_entries_query:
        # Get lines for this entry that belong to the contract
        entry_lines = db.query(JournalEntryLine).filter(
            JournalEntryLine.journal_entry_id == entry.id,
            or_(*je_line_conditions)
        ).all()

        entry_debit = sum(decimal_to_float(line.debit) or 0 for line in entry_lines)
        entry_credit = sum(decimal_to_float(line.credit) or 0 for line in entry_lines)

        recent_entries.append({
            "id": entry.id,
            "entry_number": entry.entry_number,
            "entry_date": entry.entry_date.isoformat() if entry.entry_date else None,
            "description": entry.description,
            "source_type": entry.source_type,
            "source_number": entry.source_number,
            "total_debit": entry_debit,
            "total_credit": entry_credit
        })

    if entries_by_account or recent_entries:
        ledger_summary = {
            "total_debits": total_ledger_debits,
            "total_credits": total_ledger_credits,
            "revenue": total_revenue,
            "expenses": total_expenses,
            "net_income": total_revenue - total_expenses,
            "entries_by_account": entries_by_account,
            "recent_entries": recent_entries
        }
    # ========== END ACCOUNTING LEDGER INTEGRATION ==========

    # Update total cost to include petty cash and recognized subcontractor allocations
    total_cost_with_all = total_cost + petty_cash_cost + subcontractor_cost
    budget_remaining_with_all = (budget - total_cost_with_all) if budget else None
    budget_used_percent_with_all = round((total_cost_with_all / budget * 100), 1) if budget and budget > 0 else None

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
            "petty_cash_cost": petty_cash_cost,
            "subcontractor_cost": subcontractor_cost,
            "total_cost": total_cost_with_all,
            "billable_amount": total_billable_amount,
            "budget_used": total_cost_with_all,
            "budget_remaining": budget_remaining_with_all,
            "budget_used_percent": budget_used_percent_with_all
        },
        "petty_cash": {
            "transaction_count": petty_cash_stats.transaction_count or 0 if petty_cash_stats else 0,
            "total_amount": petty_cash_cost
        },
        "subcontractor_allocations": {
            "allocation_count": allocation_count,
            "total_allocated": decimal_to_float(total_allocated),
            "total_recognized": decimal_to_float(total_recognized),
            "total_pending": decimal_to_float(total_pending),
            "monthly_breakdown": monthly_breakdown,
            "allocations": allocation_details
        },
        "sites_breakdown": sites_breakdown,
        "labor_by_technician": labor_by_technician,
        "work_orders": wo_details,
        "ledger": ledger_summary
    }
