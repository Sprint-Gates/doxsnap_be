"""
Fleet Management API - Vehicles, Maintenance, and Fuel Logs
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import Optional, List
from decimal import Decimal
from datetime import datetime, date
from pydantic import BaseModel

from app.database import get_db
from app.models import Vehicle, VehicleMaintenance, VehicleFuelLog, AddressBook, Site, User
from app.api.auth import get_current_user

router = APIRouter()


# ============================================================================
# Pydantic Schemas
# ============================================================================

class VehicleCreate(BaseModel):
    vehicle_number: str
    license_plate: str
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    color: Optional[str] = None
    vehicle_type: Optional[str] = None
    fuel_type: Optional[str] = None
    seating_capacity: Optional[int] = None
    cargo_capacity_kg: Optional[float] = None
    ownership_type: Optional[str] = 'owned'
    purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None
    lease_end_date: Optional[date] = None
    lease_monthly_cost: Optional[float] = None
    current_odometer: Optional[float] = 0
    odometer_unit: Optional[str] = 'km'
    assigned_driver_id: Optional[int] = None
    assigned_site_id: Optional[int] = None
    insurance_policy_number: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_expiry: Optional[date] = None
    registration_number: Optional[str] = None
    registration_expiry: Optional[date] = None
    service_interval_km: Optional[float] = 5000
    service_interval_months: Optional[int] = 6
    notes: Optional[str] = None


class VehicleUpdate(BaseModel):
    vehicle_number: Optional[str] = None
    license_plate: Optional[str] = None
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    color: Optional[str] = None
    vehicle_type: Optional[str] = None
    fuel_type: Optional[str] = None
    seating_capacity: Optional[int] = None
    cargo_capacity_kg: Optional[float] = None
    ownership_type: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None
    lease_end_date: Optional[date] = None
    lease_monthly_cost: Optional[float] = None
    status: Optional[str] = None
    current_odometer: Optional[float] = None
    odometer_unit: Optional[str] = None
    assigned_driver_id: Optional[int] = None
    assigned_site_id: Optional[int] = None
    insurance_policy_number: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_expiry: Optional[date] = None
    registration_number: Optional[str] = None
    registration_expiry: Optional[date] = None
    last_service_date: Optional[date] = None
    last_service_odometer: Optional[float] = None
    next_service_due_date: Optional[date] = None
    next_service_due_odometer: Optional[float] = None
    service_interval_km: Optional[float] = None
    service_interval_months: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class MaintenanceCreate(BaseModel):
    vehicle_id: int
    maintenance_date: date
    maintenance_type: str
    description: str
    odometer_reading: Optional[float] = None
    work_performed: Optional[str] = None
    labor_cost: Optional[float] = 0
    parts_cost: Optional[float] = 0
    service_provider: Optional[str] = None
    service_provider_address_book_id: Optional[int] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    status: Optional[str] = 'completed'
    next_service_date: Optional[date] = None
    next_service_odometer: Optional[float] = None
    notes: Optional[str] = None


class MaintenanceUpdate(BaseModel):
    maintenance_date: Optional[date] = None
    maintenance_type: Optional[str] = None
    description: Optional[str] = None
    odometer_reading: Optional[float] = None
    work_performed: Optional[str] = None
    labor_cost: Optional[float] = None
    parts_cost: Optional[float] = None
    service_provider: Optional[str] = None
    service_provider_address_book_id: Optional[int] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    status: Optional[str] = None
    next_service_date: Optional[date] = None
    next_service_odometer: Optional[float] = None
    notes: Optional[str] = None


class FuelLogCreate(BaseModel):
    vehicle_id: int
    fuel_date: date
    fuel_time: Optional[str] = None
    odometer_reading: float
    fuel_type: Optional[str] = None
    quantity_liters: float
    unit_price: Optional[float] = None
    total_cost: float
    currency: Optional[str] = 'USD'
    is_full_tank: Optional[bool] = True
    fuel_station: Optional[str] = None
    location: Optional[str] = None
    driver_id: Optional[int] = None
    notes: Optional[str] = None


class FuelLogUpdate(BaseModel):
    fuel_date: Optional[date] = None
    fuel_time: Optional[str] = None
    odometer_reading: Optional[float] = None
    fuel_type: Optional[str] = None
    quantity_liters: Optional[float] = None
    unit_price: Optional[float] = None
    total_cost: Optional[float] = None
    currency: Optional[str] = None
    is_full_tank: Optional[bool] = None
    fuel_station: Optional[str] = None
    location: Optional[str] = None
    driver_id: Optional[int] = None
    notes: Optional[str] = None


# ============================================================================
# Response Helpers
# ============================================================================

def vehicle_to_response(vehicle: Vehicle) -> dict:
    """Convert Vehicle model to response dict"""
    return {
        "id": vehicle.id,
        "vehicle_number": vehicle.vehicle_number,
        "license_plate": vehicle.license_plate,
        "vin": vehicle.vin,
        "make": vehicle.make,
        "model": vehicle.model,
        "year": vehicle.year,
        "color": vehicle.color,
        "vehicle_type": vehicle.vehicle_type,
        "fuel_type": vehicle.fuel_type,
        "seating_capacity": vehicle.seating_capacity,
        "cargo_capacity_kg": vehicle.cargo_capacity_kg,
        "ownership_type": vehicle.ownership_type,
        "purchase_date": vehicle.purchase_date.isoformat() if vehicle.purchase_date else None,
        "purchase_price": float(vehicle.purchase_price) if vehicle.purchase_price else None,
        "lease_end_date": vehicle.lease_end_date.isoformat() if vehicle.lease_end_date else None,
        "lease_monthly_cost": float(vehicle.lease_monthly_cost) if vehicle.lease_monthly_cost else None,
        "status": vehicle.status,
        "current_odometer": vehicle.current_odometer,
        "odometer_unit": vehicle.odometer_unit,
        "assigned_driver_id": vehicle.assigned_driver_id,
        "assigned_driver_name": vehicle.assigned_driver.alpha_name if vehicle.assigned_driver else None,
        "assigned_site_id": vehicle.assigned_site_id,
        "assigned_site_name": vehicle.assigned_site.name if vehicle.assigned_site else None,
        "insurance_policy_number": vehicle.insurance_policy_number,
        "insurance_provider": vehicle.insurance_provider,
        "insurance_expiry": vehicle.insurance_expiry.isoformat() if vehicle.insurance_expiry else None,
        "registration_number": vehicle.registration_number,
        "registration_expiry": vehicle.registration_expiry.isoformat() if vehicle.registration_expiry else None,
        "last_service_date": vehicle.last_service_date.isoformat() if vehicle.last_service_date else None,
        "last_service_odometer": vehicle.last_service_odometer,
        "next_service_due_date": vehicle.next_service_due_date.isoformat() if vehicle.next_service_due_date else None,
        "next_service_due_odometer": vehicle.next_service_due_odometer,
        "service_interval_km": vehicle.service_interval_km,
        "service_interval_months": vehicle.service_interval_months,
        "notes": vehicle.notes,
        "is_active": vehicle.is_active,
        "created_at": vehicle.created_at.isoformat() if vehicle.created_at else None,
        "updated_at": vehicle.updated_at.isoformat() if vehicle.updated_at else None,
    }


def maintenance_to_response(m: VehicleMaintenance) -> dict:
    """Convert VehicleMaintenance model to response dict"""
    return {
        "id": m.id,
        "vehicle_id": m.vehicle_id,
        "vehicle_number": m.vehicle.vehicle_number if m.vehicle else None,
        "vehicle_license_plate": m.vehicle.license_plate if m.vehicle else None,
        "maintenance_number": m.maintenance_number,
        "maintenance_date": m.maintenance_date.isoformat() if m.maintenance_date else None,
        "maintenance_type": m.maintenance_type,
        "odometer_reading": m.odometer_reading,
        "description": m.description,
        "work_performed": m.work_performed,
        "labor_cost": float(m.labor_cost) if m.labor_cost else 0,
        "parts_cost": float(m.parts_cost) if m.parts_cost else 0,
        "total_cost": float(m.total_cost) if m.total_cost else 0,
        "service_provider": m.service_provider,
        "service_provider_address_book_id": m.service_provider_address_book_id,
        "service_provider_name": m.service_provider_vendor.alpha_name if m.service_provider_vendor else None,
        "invoice_number": m.invoice_number,
        "invoice_date": m.invoice_date.isoformat() if m.invoice_date else None,
        "status": m.status,
        "next_service_date": m.next_service_date.isoformat() if m.next_service_date else None,
        "next_service_odometer": m.next_service_odometer,
        "notes": m.notes,
        "created_by": m.created_by,
        "created_by_name": m.creator.email if m.creator else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def fuel_log_to_response(f: VehicleFuelLog) -> dict:
    """Convert VehicleFuelLog model to response dict"""
    return {
        "id": f.id,
        "vehicle_id": f.vehicle_id,
        "vehicle_number": f.vehicle.vehicle_number if f.vehicle else None,
        "vehicle_license_plate": f.vehicle.license_plate if f.vehicle else None,
        "fuel_log_number": f.fuel_log_number,
        "fuel_date": f.fuel_date.isoformat() if f.fuel_date else None,
        "fuel_time": f.fuel_time.isoformat() if f.fuel_time else None,
        "odometer_reading": f.odometer_reading,
        "fuel_type": f.fuel_type,
        "quantity_liters": float(f.quantity_liters) if f.quantity_liters else 0,
        "unit_price": float(f.unit_price) if f.unit_price else None,
        "total_cost": float(f.total_cost) if f.total_cost else 0,
        "currency": f.currency,
        "is_full_tank": f.is_full_tank,
        "fuel_station": f.fuel_station,
        "location": f.location,
        "driver_id": f.driver_id,
        "driver_name": f.driver.alpha_name if f.driver else None,
        "km_since_last_fill": f.km_since_last_fill,
        "liters_per_100km": f.liters_per_100km,
        "notes": f.notes,
        "created_by": f.created_by,
        "created_by_name": f.creator.email if f.creator else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


# ============================================================================
# Vehicle Endpoints
# ============================================================================

@router.get("/vehicles/")
async def get_vehicles(
    status: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    assigned_site_id: Optional[int] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all vehicles for the company"""
    query = db.query(Vehicle).options(
        joinedload(Vehicle.assigned_driver),
        joinedload(Vehicle.assigned_site)
    ).filter(Vehicle.company_id == current_user.company_id)

    if status:
        query = query.filter(Vehicle.status == status)
    if vehicle_type:
        query = query.filter(Vehicle.vehicle_type == vehicle_type)
    if assigned_site_id:
        query = query.filter(Vehicle.assigned_site_id == assigned_site_id)
    if is_active is not None:
        query = query.filter(Vehicle.is_active == is_active)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Vehicle.vehicle_number.ilike(search_term),
                Vehicle.license_plate.ilike(search_term),
                Vehicle.make.ilike(search_term),
                Vehicle.model.ilike(search_term)
            )
        )

    vehicles = query.order_by(Vehicle.vehicle_number).all()
    return [vehicle_to_response(v) for v in vehicles]


@router.get("/vehicles/{vehicle_id}")
async def get_vehicle(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific vehicle"""
    vehicle = db.query(Vehicle).options(
        joinedload(Vehicle.assigned_driver),
        joinedload(Vehicle.assigned_site)
    ).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == current_user.company_id
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    return vehicle_to_response(vehicle)


@router.post("/vehicles/")
async def create_vehicle(
    vehicle_data: VehicleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new vehicle"""
    # Check for duplicate vehicle number
    existing = db.query(Vehicle).filter(
        Vehicle.company_id == current_user.company_id,
        Vehicle.vehicle_number == vehicle_data.vehicle_number
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Vehicle number already exists")

    # Check for duplicate license plate
    existing_plate = db.query(Vehicle).filter(
        Vehicle.company_id == current_user.company_id,
        Vehicle.license_plate == vehicle_data.license_plate
    ).first()
    if existing_plate:
        raise HTTPException(status_code=400, detail="License plate already exists")

    vehicle = Vehicle(
        company_id=current_user.company_id,
        created_by=current_user.id,
        **vehicle_data.model_dump()
    )

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    # Reload with relationships
    vehicle = db.query(Vehicle).options(
        joinedload(Vehicle.assigned_driver),
        joinedload(Vehicle.assigned_site)
    ).filter(Vehicle.id == vehicle.id).first()

    return vehicle_to_response(vehicle)


@router.put("/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: int,
    vehicle_data: VehicleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a vehicle"""
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == current_user.company_id
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    update_data = vehicle_data.model_dump(exclude_unset=True)

    # Check for duplicate vehicle number if changing
    if 'vehicle_number' in update_data and update_data['vehicle_number'] != vehicle.vehicle_number:
        existing = db.query(Vehicle).filter(
            Vehicle.company_id == current_user.company_id,
            Vehicle.vehicle_number == update_data['vehicle_number'],
            Vehicle.id != vehicle_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Vehicle number already exists")

    # Check for duplicate license plate if changing
    if 'license_plate' in update_data and update_data['license_plate'] != vehicle.license_plate:
        existing = db.query(Vehicle).filter(
            Vehicle.company_id == current_user.company_id,
            Vehicle.license_plate == update_data['license_plate'],
            Vehicle.id != vehicle_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="License plate already exists")

    for key, value in update_data.items():
        setattr(vehicle, key, value)

    db.commit()
    db.refresh(vehicle)

    # Reload with relationships
    vehicle = db.query(Vehicle).options(
        joinedload(Vehicle.assigned_driver),
        joinedload(Vehicle.assigned_site)
    ).filter(Vehicle.id == vehicle.id).first()

    return vehicle_to_response(vehicle)


@router.delete("/vehicles/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a vehicle"""
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.company_id == current_user.company_id
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    db.delete(vehicle)
    db.commit()

    return {"message": "Vehicle deleted successfully"}


@router.get("/vehicles/stats/summary")
async def get_vehicle_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fleet statistics summary"""
    vehicles = db.query(Vehicle).filter(
        Vehicle.company_id == current_user.company_id
    ).all()

    total = len(vehicles)
    active = sum(1 for v in vehicles if v.is_active)
    available = sum(1 for v in vehicles if v.status == 'available' and v.is_active)
    in_use = sum(1 for v in vehicles if v.status == 'in_use' and v.is_active)
    maintenance = sum(1 for v in vehicles if v.status == 'maintenance' and v.is_active)
    out_of_service = sum(1 for v in vehicles if v.status == 'out_of_service')

    # Vehicles needing service
    today = date.today()
    service_due = sum(1 for v in vehicles if v.is_active and (
        (v.next_service_due_date and v.next_service_due_date <= today) or
        (v.next_service_due_odometer and v.current_odometer >= v.next_service_due_odometer)
    ))

    # Expiring documents (within 30 days)
    from datetime import timedelta
    thirty_days = today + timedelta(days=30)
    insurance_expiring = sum(1 for v in vehicles if v.is_active and v.insurance_expiry and v.insurance_expiry <= thirty_days)
    registration_expiring = sum(1 for v in vehicles if v.is_active and v.registration_expiry and v.registration_expiry <= thirty_days)

    # By type
    by_type = {}
    for v in vehicles:
        if v.is_active:
            vtype = v.vehicle_type or 'Other'
            by_type[vtype] = by_type.get(vtype, 0) + 1

    # By ownership
    by_ownership = {}
    for v in vehicles:
        if v.is_active:
            ownership = v.ownership_type or 'owned'
            by_ownership[ownership] = by_ownership.get(ownership, 0) + 1

    return {
        "total_vehicles": total,
        "active_vehicles": active,
        "available": available,
        "in_use": in_use,
        "in_maintenance": maintenance,
        "out_of_service": out_of_service,
        "service_due": service_due,
        "insurance_expiring_soon": insurance_expiring,
        "registration_expiring_soon": registration_expiring,
        "by_type": by_type,
        "by_ownership": by_ownership,
    }


# ============================================================================
# Maintenance Endpoints
# ============================================================================

@router.get("/vehicles/maintenance/")
async def get_all_maintenance(
    vehicle_id: Optional[int] = None,
    maintenance_type: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all maintenance records"""
    query = db.query(VehicleMaintenance).options(
        joinedload(VehicleMaintenance.vehicle),
        joinedload(VehicleMaintenance.service_provider_vendor),
        joinedload(VehicleMaintenance.creator)
    ).filter(VehicleMaintenance.company_id == current_user.company_id)

    if vehicle_id:
        query = query.filter(VehicleMaintenance.vehicle_id == vehicle_id)
    if maintenance_type:
        query = query.filter(VehicleMaintenance.maintenance_type == maintenance_type)
    if status:
        query = query.filter(VehicleMaintenance.status == status)
    if from_date:
        query = query.filter(VehicleMaintenance.maintenance_date >= from_date)
    if to_date:
        query = query.filter(VehicleMaintenance.maintenance_date <= to_date)

    records = query.order_by(VehicleMaintenance.maintenance_date.desc()).all()
    return [maintenance_to_response(m) for m in records]


@router.get("/vehicles/maintenance/{maintenance_id}")
async def get_maintenance(
    maintenance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific maintenance record"""
    m = db.query(VehicleMaintenance).options(
        joinedload(VehicleMaintenance.vehicle),
        joinedload(VehicleMaintenance.service_provider_vendor),
        joinedload(VehicleMaintenance.creator)
    ).filter(
        VehicleMaintenance.id == maintenance_id,
        VehicleMaintenance.company_id == current_user.company_id
    ).first()

    if not m:
        raise HTTPException(status_code=404, detail="Maintenance record not found")

    return maintenance_to_response(m)


@router.post("/vehicles/maintenance/")
async def create_maintenance(
    data: MaintenanceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a maintenance record"""
    # Verify vehicle exists
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == data.vehicle_id,
        Vehicle.company_id == current_user.company_id
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Generate maintenance number
    year = date.today().year
    last_mnt = db.query(VehicleMaintenance).filter(
        VehicleMaintenance.company_id == current_user.company_id,
        VehicleMaintenance.maintenance_number.like(f'MNT-{year}-%')
    ).order_by(VehicleMaintenance.maintenance_number.desc()).first()

    if last_mnt:
        last_num = int(last_mnt.maintenance_number.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    maintenance_number = f"MNT-{year}-{new_num:05d}"

    # Calculate total cost
    labor_cost = Decimal(str(data.labor_cost or 0))
    parts_cost = Decimal(str(data.parts_cost or 0))
    total_cost = labor_cost + parts_cost

    maintenance = VehicleMaintenance(
        company_id=current_user.company_id,
        maintenance_number=maintenance_number,
        total_cost=total_cost,
        created_by=current_user.id,
        **data.model_dump(exclude={'labor_cost', 'parts_cost'})
    )
    maintenance.labor_cost = labor_cost
    maintenance.parts_cost = parts_cost

    db.add(maintenance)

    # Update vehicle's last service info if completed
    if data.status == 'completed':
        vehicle.last_service_date = data.maintenance_date
        if data.odometer_reading:
            vehicle.last_service_odometer = data.odometer_reading
            vehicle.current_odometer = max(vehicle.current_odometer or 0, data.odometer_reading)
        if data.next_service_date:
            vehicle.next_service_due_date = data.next_service_date
        if data.next_service_odometer:
            vehicle.next_service_due_odometer = data.next_service_odometer

    db.commit()
    db.refresh(maintenance)

    # Reload with relationships
    maintenance = db.query(VehicleMaintenance).options(
        joinedload(VehicleMaintenance.vehicle),
        joinedload(VehicleMaintenance.service_provider_vendor),
        joinedload(VehicleMaintenance.creator)
    ).filter(VehicleMaintenance.id == maintenance.id).first()

    return maintenance_to_response(maintenance)


@router.put("/vehicles/maintenance/{maintenance_id}")
async def update_maintenance(
    maintenance_id: int,
    data: MaintenanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a maintenance record"""
    m = db.query(VehicleMaintenance).filter(
        VehicleMaintenance.id == maintenance_id,
        VehicleMaintenance.company_id == current_user.company_id
    ).first()

    if not m:
        raise HTTPException(status_code=404, detail="Maintenance record not found")

    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key in ['labor_cost', 'parts_cost']:
            setattr(m, key, Decimal(str(value)) if value is not None else None)
        else:
            setattr(m, key, value)

    # Recalculate total cost
    m.total_cost = (m.labor_cost or Decimal('0')) + (m.parts_cost or Decimal('0'))

    db.commit()
    db.refresh(m)

    # Reload with relationships
    m = db.query(VehicleMaintenance).options(
        joinedload(VehicleMaintenance.vehicle),
        joinedload(VehicleMaintenance.service_provider_vendor),
        joinedload(VehicleMaintenance.creator)
    ).filter(VehicleMaintenance.id == m.id).first()

    return maintenance_to_response(m)


@router.delete("/vehicles/maintenance/{maintenance_id}")
async def delete_maintenance(
    maintenance_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a maintenance record"""
    m = db.query(VehicleMaintenance).filter(
        VehicleMaintenance.id == maintenance_id,
        VehicleMaintenance.company_id == current_user.company_id
    ).first()

    if not m:
        raise HTTPException(status_code=404, detail="Maintenance record not found")

    db.delete(m)
    db.commit()

    return {"message": "Maintenance record deleted successfully"}


# ============================================================================
# Fuel Log Endpoints
# ============================================================================

@router.get("/vehicles/fuel-logs/")
async def get_all_fuel_logs(
    vehicle_id: Optional[int] = None,
    driver_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fuel logs"""
    query = db.query(VehicleFuelLog).options(
        joinedload(VehicleFuelLog.vehicle),
        joinedload(VehicleFuelLog.driver),
        joinedload(VehicleFuelLog.creator)
    ).filter(VehicleFuelLog.company_id == current_user.company_id)

    if vehicle_id:
        query = query.filter(VehicleFuelLog.vehicle_id == vehicle_id)
    if driver_id:
        query = query.filter(VehicleFuelLog.driver_id == driver_id)
    if from_date:
        query = query.filter(VehicleFuelLog.fuel_date >= from_date)
    if to_date:
        query = query.filter(VehicleFuelLog.fuel_date <= to_date)

    logs = query.order_by(VehicleFuelLog.fuel_date.desc(), VehicleFuelLog.id.desc()).all()
    return [fuel_log_to_response(f) for f in logs]


@router.get("/vehicles/fuel-logs/{fuel_log_id}")
async def get_fuel_log(
    fuel_log_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific fuel log"""
    f = db.query(VehicleFuelLog).options(
        joinedload(VehicleFuelLog.vehicle),
        joinedload(VehicleFuelLog.driver),
        joinedload(VehicleFuelLog.creator)
    ).filter(
        VehicleFuelLog.id == fuel_log_id,
        VehicleFuelLog.company_id == current_user.company_id
    ).first()

    if not f:
        raise HTTPException(status_code=404, detail="Fuel log not found")

    return fuel_log_to_response(f)


@router.post("/vehicles/fuel-logs/")
async def create_fuel_log(
    data: FuelLogCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a fuel log"""
    # Verify vehicle exists
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == data.vehicle_id,
        Vehicle.company_id == current_user.company_id
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Generate fuel log number
    year = date.today().year
    last_log = db.query(VehicleFuelLog).filter(
        VehicleFuelLog.company_id == current_user.company_id,
        VehicleFuelLog.fuel_log_number.like(f'FUEL-{year}-%')
    ).order_by(VehicleFuelLog.fuel_log_number.desc()).first()

    if last_log:
        last_num = int(last_log.fuel_log_number.split('-')[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    fuel_log_number = f"FUEL-{year}-{new_num:05d}"

    # Calculate fuel efficiency if full tank
    km_since_last = None
    liters_per_100km = None
    if data.is_full_tank:
        # Find previous full tank fill for this vehicle
        prev_fill = db.query(VehicleFuelLog).filter(
            VehicleFuelLog.vehicle_id == data.vehicle_id,
            VehicleFuelLog.is_full_tank == True,
            VehicleFuelLog.odometer_reading < data.odometer_reading
        ).order_by(VehicleFuelLog.odometer_reading.desc()).first()

        if prev_fill:
            km_since_last = data.odometer_reading - prev_fill.odometer_reading
            if km_since_last > 0:
                liters_per_100km = (float(data.quantity_liters) / km_since_last) * 100

    fuel_log = VehicleFuelLog(
        company_id=current_user.company_id,
        fuel_log_number=fuel_log_number,
        km_since_last_fill=km_since_last,
        liters_per_100km=liters_per_100km,
        created_by=current_user.id,
        quantity_liters=Decimal(str(data.quantity_liters)),
        unit_price=Decimal(str(data.unit_price)) if data.unit_price else None,
        total_cost=Decimal(str(data.total_cost)),
        **data.model_dump(exclude={'quantity_liters', 'unit_price', 'total_cost'})
    )

    db.add(fuel_log)

    # Update vehicle odometer
    vehicle.current_odometer = max(vehicle.current_odometer or 0, data.odometer_reading)

    db.commit()
    db.refresh(fuel_log)

    # Reload with relationships
    fuel_log = db.query(VehicleFuelLog).options(
        joinedload(VehicleFuelLog.vehicle),
        joinedload(VehicleFuelLog.driver),
        joinedload(VehicleFuelLog.creator)
    ).filter(VehicleFuelLog.id == fuel_log.id).first()

    return fuel_log_to_response(fuel_log)


@router.put("/vehicles/fuel-logs/{fuel_log_id}")
async def update_fuel_log(
    fuel_log_id: int,
    data: FuelLogUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a fuel log"""
    f = db.query(VehicleFuelLog).filter(
        VehicleFuelLog.id == fuel_log_id,
        VehicleFuelLog.company_id == current_user.company_id
    ).first()

    if not f:
        raise HTTPException(status_code=404, detail="Fuel log not found")

    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key in ['quantity_liters', 'unit_price', 'total_cost']:
            setattr(f, key, Decimal(str(value)) if value is not None else None)
        else:
            setattr(f, key, value)

    db.commit()
    db.refresh(f)

    # Reload with relationships
    f = db.query(VehicleFuelLog).options(
        joinedload(VehicleFuelLog.vehicle),
        joinedload(VehicleFuelLog.driver),
        joinedload(VehicleFuelLog.creator)
    ).filter(VehicleFuelLog.id == f.id).first()

    return fuel_log_to_response(f)


@router.delete("/vehicles/fuel-logs/{fuel_log_id}")
async def delete_fuel_log(
    fuel_log_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a fuel log"""
    f = db.query(VehicleFuelLog).filter(
        VehicleFuelLog.id == fuel_log_id,
        VehicleFuelLog.company_id == current_user.company_id
    ).first()

    if not f:
        raise HTTPException(status_code=404, detail="Fuel log not found")

    db.delete(f)
    db.commit()

    return {"message": "Fuel log deleted successfully"}


@router.get("/vehicles/fuel-logs/stats/summary")
async def get_fuel_stats(
    vehicle_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fuel consumption statistics"""
    query = db.query(VehicleFuelLog).filter(
        VehicleFuelLog.company_id == current_user.company_id
    )

    if vehicle_id:
        query = query.filter(VehicleFuelLog.vehicle_id == vehicle_id)
    if from_date:
        query = query.filter(VehicleFuelLog.fuel_date >= from_date)
    if to_date:
        query = query.filter(VehicleFuelLog.fuel_date <= to_date)

    logs = query.all()

    total_liters = sum(float(log.quantity_liters or 0) for log in logs)
    total_cost = sum(float(log.total_cost or 0) for log in logs)
    total_records = len(logs)

    # Average consumption
    consumption_logs = [log for log in logs if log.liters_per_100km]
    avg_consumption = None
    if consumption_logs:
        avg_consumption = sum(log.liters_per_100km for log in consumption_logs) / len(consumption_logs)

    return {
        "total_fuel_liters": round(total_liters, 2),
        "total_fuel_cost": round(total_cost, 2),
        "total_records": total_records,
        "average_liters_per_100km": round(avg_consumption, 2) if avg_consumption else None,
    }
