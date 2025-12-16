from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Float, Date, Numeric, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# Association table for Operator-Branch many-to-many relationship
operator_branches = Table(
    'operator_branches',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('branch_id', Integer, ForeignKey('branches.id'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now())
)

# Association table for HandHeldDevice-Technician many-to-many relationship
handheld_device_technicians = Table(
    'handheld_device_technicians',
    Base.metadata,
    Column('handheld_device_id', Integer, ForeignKey('handheld_devices.id', ondelete='CASCADE'), primary_key=True),
    Column('technician_id', Integer, ForeignKey('technicians.id', ondelete='CASCADE'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now()),
    Column('is_primary', Boolean, default=False),
    Column('notes', Text, nullable=True)
)

# Association table for Operator-Site many-to-many relationship
operator_sites = Table(
    'operator_sites',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('site_id', Integer, ForeignKey('sites.id'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now())
)

# Association table for Contract-Site many-to-many relationship
contract_sites = Table(
    'contract_sites',
    Base.metadata,
    Column('contract_id', Integer, ForeignKey('contracts.id', ondelete='CASCADE'), primary_key=True),
    Column('site_id', Integer, ForeignKey('sites.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime, default=func.now())
)


class Plan(Base):
    """Subscription plans for document management"""
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # "Starter", "Professional", "Enterprise"
    slug = Column(String, unique=True, nullable=False, index=True)  # "starter", "professional", "enterprise"
    description = Column(Text, nullable=True)
    price_monthly = Column(Numeric(10, 2), nullable=False)  # Monthly price in USD
    documents_min = Column(Integer, nullable=False)  # Min documents included
    documents_max = Column(Integer, nullable=False)  # Max documents included
    max_users = Column(Integer, default=5)  # Max users allowed
    max_clients = Column(Integer, default=10)  # Max clients allowed
    max_branches = Column(Integer, default=5)  # Max branches per client
    max_projects = Column(Integer, default=20)  # Max projects allowed
    features = Column(Text, nullable=True)  # JSON list of features
    is_active = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)  # Highlight as popular
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    companies = relationship("Company", back_populates="plan")


class Company(Base):
    """Company/Organization that subscribes to a plan"""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    tax_number = Column(String, nullable=True)  # Company tax ID
    registration_number = Column(String, nullable=True)
    website = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    size = Column(String, nullable=True)  # "1-10", "11-50", "51-200", etc.

    # Subscription info
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    subscription_status = Column(String, default="trial")  # trial, active, suspended, cancelled
    subscription_start = Column(DateTime, nullable=True)
    subscription_end = Column(DateTime, nullable=True)
    documents_used_this_month = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    plan = relationship("Plan", back_populates="companies")
    users = relationship("User", back_populates="company")
    clients = relationship("Client", back_populates="company")


class Client(Base):
    """Client/Customer of a company"""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True, index=True)  # Client code for imports
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    tax_number = Column(String, nullable=True)
    contact_person = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="clients")
    branches = relationship("Branch", back_populates="client")


class Branch(Base):
    """Branch/Location of a client"""
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True)  # Branch code for reference
    address = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    manager_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    client = relationship("Client", back_populates="branches")
    operators = relationship("User", secondary=operator_branches, back_populates="assigned_branches")
    floors = relationship("Floor", back_populates="branch")


class Project(Base):
    """Project under a site"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True)  # Project code for reference
    description = Column(Text, nullable=True)
    status = Column(String, default="active")  # active, on_hold, completed, archived
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    budget = Column(Numeric(12, 2), nullable=True)
    currency = Column(String, default="USD")
    # Default markup percentages for work orders in this project
    labor_markup_percent = Column(Numeric(5, 2), default=0)
    parts_markup_percent = Column(Numeric(5, 2), default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    site = relationship("Site", back_populates="projects")
    invoices = relationship("ProcessedImage", back_populates="project")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    name = Column(String, nullable=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)  # Admin flag (legacy, use role instead)
    remaining_documents = Column(Integer, default=5)  # Free documents limit

    # Multi-tenant fields
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    role = Column(String, default="admin")  # admin, operator, accounting
    phone = Column(String, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="users")
    processed_images = relationship("ProcessedImage", back_populates="user")
    assigned_branches = relationship("Branch", secondary=operator_branches, back_populates="operators")


class ProcessedImage(Base):
    __tablename__ = "processed_images"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    original_filename = Column(String)
    s3_key = Column(String)
    s3_url = Column(String)
    processing_status = Column(String, default="pending")  # pending, completed, failed
    document_type = Column(String, default="invoice")  # invoice, receipt, purchase_order, bill_of_lading, etc.
    invoice_category = Column(String, nullable=True)  # service (subcontractor invoice) or spare_parts

    # Project linkage for multi-tenant structure
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    # Vendor linkage
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)

    # Enhanced Invoice processing results
    ocr_extracted_words = Column(Integer, default=0)  # Number of words extracted by OCR
    ocr_average_confidence = Column(Float, default=0.0)  # Average OCR confidence score
    ocr_preprocessing_methods = Column(Integer, default=1)  # Number of preprocessing methods used
    patterns_detected = Column(Integer, default=0)  # Number of patterns detected
    has_structured_data = Column(Boolean, default=False)  # Whether AI extraction was successful
    structured_data = Column(Text, nullable=True)  # JSON string of extracted invoice data
    extraction_confidence = Column(Float, default=0.0)  # AI extraction confidence score
    processing_method = Column(String, default="basic")  # Processing method used

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="processed_images")
    project = relationship("Project", back_populates="invoices")
    vendor = relationship("Vendor", back_populates="invoices")


class DocumentType(Base):
    __tablename__ = "document_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)  # invoice, receipt, etc.
    display_name = Column(String, nullable=False)  # "Invoice", "Receipt", etc.
    description = Column(Text, nullable=True)
    color = Column(String, default="#007bff")  # Hex color for UI
    is_active = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)  # System types cannot be deleted
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    name = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    tax_number = Column(String, nullable=True)  # VAT/Tax registration number
    registration_number = Column(String, nullable=True)  # Company registration number
    website = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)  # Soft delete - cannot delete, only disable
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    invoices = relationship("ProcessedImage", back_populates="vendor")


class Warehouse(Base):
    """Warehouse/Storage location belonging to a company"""
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True)  # Warehouse code for reference (e.g., "WH-001")
    address = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    manager_name = Column(String, nullable=True)
    capacity = Column(String, nullable=True)  # Storage capacity description
    notes = Column(Text, nullable=True)
    is_main = Column(Boolean, default=False)  # Main warehouse for auto-receiving invoice items
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="warehouses")


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True)
    otp_code = Column(String, nullable=False)
    purpose = Column(String, default="email_verification")  # email_verification, password_reset, login
    is_verified = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class RefreshToken(Base):
    """Refresh tokens for JWT authentication"""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    revoked_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", backref="refresh_tokens")


class Technician(Base):
    """Technician/Field worker belonging to a company"""
    __tablename__ = "technicians"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    employee_id = Column(String, nullable=True)  # Internal employee ID
    specialization = Column(String, nullable=True)  # e.g., "HVAC", "Electrical", "Plumbing"
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Salary breakdown fields (accounting only)
    salary_type = Column(String, default="monthly")  # monthly, hourly, daily
    base_salary = Column(Numeric(12, 2), nullable=True)  # Base salary amount
    currency = Column(String, default="USD")
    hourly_rate = Column(Numeric(10, 2), nullable=True)  # Calculated or manual hourly rate
    overtime_rate_multiplier = Column(Numeric(4, 2), default=1.5)  # e.g., 1.5x for overtime
    working_hours_per_day = Column(Numeric(4, 2), default=8.0)
    working_days_per_month = Column(Integer, default=22)

    # Additional compensation
    transport_allowance = Column(Numeric(10, 2), nullable=True)
    housing_allowance = Column(Numeric(10, 2), nullable=True)
    food_allowance = Column(Numeric(10, 2), nullable=True)
    other_allowances = Column(Numeric(10, 2), nullable=True)
    allowances_notes = Column(Text, nullable=True)  # Description of other allowances

    # Deductions
    social_security_rate = Column(Numeric(5, 4), nullable=True)  # e.g., 0.0725 for 7.25%
    tax_rate = Column(Numeric(5, 4), nullable=True)  # Income tax rate
    other_deductions = Column(Numeric(10, 2), nullable=True)
    deductions_notes = Column(Text, nullable=True)

    # Relationships
    company = relationship("Company")
    assigned_device = relationship("HandHeldDevice", back_populates="assigned_technician", uselist=False)
    assigned_devices = relationship("HandHeldDevice", secondary="handheld_device_technicians", back_populates="assigned_technicians")


class HandHeldDevice(Base):
    """Hand Held Device for field technicians to perform maintenance work"""
    __tablename__ = "handheld_devices"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    device_code = Column(String, nullable=False)  # Unique device identifier (e.g., "HHD-001")
    device_name = Column(String, nullable=True)  # Friendly name
    device_model = Column(String, nullable=True)  # Device model/type
    serial_number = Column(String, nullable=True)  # Hardware serial number
    os_version = Column(String, nullable=True)  # Operating system version
    app_version = Column(String, nullable=True)  # Mobile app version installed
    last_sync_at = Column(DateTime, nullable=True)  # Last time device synced with server

    # Warehouse assignment - HHD can be linked to a warehouse for inventory transfers
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)

    # Technician assignment (one device = one technician)
    assigned_technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)
    assigned_at = Column(DateTime, nullable=True)  # When technician was assigned

    # Mobile app authentication
    mobile_pin = Column(String, nullable=True)  # PIN for mobile app login (4-6 digits)

    # Device status
    status = Column(String, default="available")  # available, assigned, maintenance, retired
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    warehouse = relationship("Warehouse", backref="handheld_devices")
    assigned_technician = relationship("Technician", back_populates="assigned_device")
    assigned_technicians = relationship("Technician", secondary="handheld_device_technicians", back_populates="assigned_devices")


class Floor(Base):
    """Floor within a building for asset capturing"""
    __tablename__ = "floors"

    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)  # Legacy field
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)
    name = Column(String, nullable=False)  # e.g., "Ground Floor", "Floor 1", "Basement"
    code = Column(String, nullable=True)  # e.g., "GF", "F1", "B1"
    level = Column(Integer, default=0)  # Numeric level for sorting (-1 for basement, 0 for ground, etc.)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    branch = relationship("Branch", back_populates="floors")
    building = relationship("Building", back_populates="floors")
    rooms = relationship("Room", back_populates="floor", cascade="all, delete-orphan")
    units = relationship("Unit", back_populates="floor", cascade="all, delete-orphan")


class Unit(Base):
    """Unit within a floor (e.g., apartment, office unit) for asset capturing"""
    __tablename__ = "units"

    id = Column(Integer, primary_key=True, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g., "Unit 101", "Apartment A", "Office Suite 5"
    code = Column(String, nullable=True)  # e.g., "U-101", "APT-A"
    unit_type = Column(String, nullable=True)  # e.g., "Apartment", "Office", "Retail", "Storage"
    area_sqm = Column(Float, nullable=True)  # Unit area in square meters
    tenant_name = Column(String, nullable=True)  # Current tenant/occupant
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    floor = relationship("Floor", back_populates="units")
    rooms = relationship("Room", back_populates="unit", cascade="all, delete-orphan")
    equipment = relationship("Equipment", back_populates="unit")


class Room(Base):
    """Room within a floor or unit for asset capturing"""
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)  # Direct parent floor (if not in a unit)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True)  # Parent unit (if in a unit)
    name = Column(String, nullable=False)  # e.g., "Server Room", "Office 101", "Kitchen"
    code = Column(String, nullable=True)  # e.g., "SR-01", "OFF-101"
    room_type = Column(String, nullable=True)  # e.g., "Office", "Storage", "Utility", "Common Area"
    area_sqm = Column(Float, nullable=True)  # Room area in square meters
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    floor = relationship("Floor", back_populates="rooms")
    unit = relationship("Unit", back_populates="rooms")
    desks = relationship("Desk", back_populates="room", cascade="all, delete-orphan")
    equipment = relationship("Equipment", back_populates="room", cascade="all, delete-orphan")


class Desk(Base):
    """Desk/Workstation within a room for asset capturing"""
    __tablename__ = "desks"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g., "Desk 1", "Workstation A", "Reception Desk"
    code = Column(String, nullable=True)  # e.g., "D-001", "WS-A"
    desk_type = Column(String, nullable=True)  # e.g., "Workstation", "Reception", "Manager", "Hot Desk"
    occupant_name = Column(String, nullable=True)  # Current occupant/user
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    room = relationship("Room", back_populates="desks")
    equipment = relationship("Equipment", back_populates="desk")


class Equipment(Base):
    """
    Equipment/Asset - can be assigned to any level of the hierarchy
    Must have exactly ONE parent (client, site, building, space, floor, or room)
    """
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)

    # Flexible parent assignment - equipment can belong to any level
    # Only ONE of these should be set (enforced at application level)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    desk_id = Column(Integer, ForeignKey("desks.id"), nullable=True)

    name = Column(String, nullable=False)  # e.g., "Air Conditioning Unit", "Main Distribution Panel"
    code = Column(String, nullable=True, index=True)  # Asset tag/code e.g., "AC-001", "MDP-01"
    category = Column(String, nullable=False)  # "electrical", "mechanical", "plumbing"
    equipment_type = Column(String, nullable=True)  # Specific type within category

    # PM Hierarchy link - links to PMEquipmentClass for maintenance checklists
    pm_equipment_class_id = Column(Integer, ForeignKey("pm_equipment_classes.id"), nullable=True)
    pm_asset_type_id = Column(Integer, ForeignKey("pm_asset_types.id"), nullable=True)
    manufacturer = Column(String, nullable=True)
    model = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    installation_date = Column(Date, nullable=True)
    warranty_expiry = Column(Date, nullable=True)
    status = Column(String, default="operational")  # operational, needs_maintenance, out_of_service, retired
    condition = Column(String, default="good")  # excellent, good, fair, poor
    condition_rating = Column(Integer, nullable=True)  # 1-10 rating scale
    specifications = Column(Text, nullable=True)  # JSON string for technical specs
    location_details = Column(String, nullable=True)  # Specific location description
    photo_url = Column(String, nullable=True)  # Photo of the equipment
    qr_code = Column(String, nullable=True)  # QR code for quick scanning
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    client = relationship("Client", backref="equipment")
    site = relationship("Site", backref="equipment")
    building = relationship("Building", backref="equipment")
    space = relationship("Space", backref="equipment")
    floor = relationship("Floor", backref="equipment")
    unit = relationship("Unit", back_populates="equipment")
    room = relationship("Room", back_populates="equipment")
    desk = relationship("Desk", back_populates="equipment")
    sub_equipment = relationship("SubEquipment", back_populates="parent_equipment", cascade="all, delete-orphan")
    pm_equipment_class = relationship("PMEquipmentClass", backref="equipment")
    pm_asset_type = relationship("PMAssetType", backref="equipment")


class SubEquipment(Base):
    """
    Sub-component - can be assigned to Equipment OR any level of the hierarchy
    Typically a component of Equipment, but can also be standalone at any location level
    """
    __tablename__ = "sub_equipment"

    id = Column(Integer, primary_key=True, index=True)

    # Parent equipment (most common case)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True)

    # Flexible parent assignment - sub-equipment can also belong to any level directly
    # Only ONE of these should be set (enforced at application level)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)

    name = Column(String, nullable=False)  # e.g., "Compressor", "Filter", "Motor"
    code = Column(String, nullable=True, index=True)  # Sub-asset code
    component_type = Column(String, nullable=True)  # Type of component
    manufacturer = Column(String, nullable=True)
    model = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    installation_date = Column(Date, nullable=True)
    warranty_expiry = Column(Date, nullable=True)
    status = Column(String, default="operational")  # operational, needs_maintenance, out_of_service, retired
    condition = Column(String, default="good")  # excellent, good, fair, poor
    specifications = Column(Text, nullable=True)  # JSON string for technical specs
    photo_url = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    parent_equipment = relationship("Equipment", back_populates="sub_equipment")
    client = relationship("Client", backref="sub_equipment")
    site = relationship("Site", backref="sub_equipment")
    building = relationship("Building", backref="sub_equipment")
    space = relationship("Space", backref="sub_equipment")
    floor = relationship("Floor", backref="sub_equipment")
    room = relationship("Room", backref="sub_equipment")


class TechnicianAttendance(Base):
    """Daily attendance record for technicians"""
    __tablename__ = "technician_attendance"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)  # The date of attendance

    # Attendance status
    status = Column(String, default="present")  # present, absent, late, half_day, on_leave, holiday

    # Time tracking
    check_in = Column(DateTime, nullable=True)  # Clock in time
    check_out = Column(DateTime, nullable=True)  # Clock out time
    break_duration_minutes = Column(Integer, default=0)  # Total break time in minutes

    # Computed/Override fields
    hours_worked = Column(Numeric(5, 2), nullable=True)  # Total hours worked (can be auto-calculated or manual)
    overtime_hours = Column(Numeric(5, 2), default=0)  # Overtime hours

    # Leave/Absence details
    leave_type = Column(String, nullable=True)  # sick, vacation, personal, unpaid, maternity, paternity
    leave_approved = Column(Boolean, default=False)
    leave_approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Location (for field technicians)
    check_in_location = Column(String, nullable=True)  # GPS coordinates or location name
    check_out_location = Column(String, nullable=True)

    # Notes and metadata
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    technician = relationship("Technician", backref="attendance_records")
    approver = relationship("User", foreign_keys=[leave_approved_by])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


# Association table for WorkOrder-Technician many-to-many relationship
work_order_technicians = Table(
    'work_order_technicians',
    Base.metadata,
    Column('work_order_id', Integer, ForeignKey('work_orders.id'), primary_key=True),
    Column('technician_id', Integer, ForeignKey('technicians.id'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now()),
    Column('hours_worked', Numeric(5, 2), nullable=True),  # Hours this technician worked on this WO
    Column('hourly_rate', Numeric(10, 2), nullable=True),  # Snapshot of rate at time of assignment
    Column('notes', Text, nullable=True)
)


class SparePart(Base):
    """Spare parts inventory for maintenance work"""
    __tablename__ = "spare_parts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Part identification
    part_number = Column(String, nullable=False, index=True)  # SKU or part number
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)  # electrical, mechanical, plumbing, consumable, etc.

    # Inventory
    quantity_in_stock = Column(Integer, default=0)
    minimum_stock_level = Column(Integer, default=0)  # Alert when below this
    unit = Column(String, default="pcs")  # pcs, m, kg, L, etc.

    # Pricing
    unit_cost = Column(Numeric(12, 2), nullable=True)  # Cost to company
    unit_price = Column(Numeric(12, 2), nullable=True)  # Price charged to client (if billable)
    currency = Column(String, default="USD")

    # Supplier info
    supplier_name = Column(String, nullable=True)
    supplier_part_number = Column(String, nullable=True)

    # Metadata
    location = Column(String, nullable=True)  # Storage location
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")


class WorkOrder(Base):
    """Work order for maintenance tasks on assets"""
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Work order identification
    wo_number = Column(String, nullable=False, index=True)  # Auto-generated WO number
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Type of maintenance
    work_order_type = Column(String, nullable=False)  # corrective, preventive, operations

    # Priority and status
    priority = Column(String, default="medium")  # low, medium, high, critical
    status = Column(String, default="draft")  # draft, pending, in_progress, on_hold, completed, cancelled

    # General notes
    notes = Column(Text, nullable=True)

    # Asset linkage (can be equipment or sub-equipment)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True)
    sub_equipment_id = Column(Integer, ForeignKey("sub_equipment.id"), nullable=True)

    # Location context (denormalized for easier querying)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)

    # Project assignment (legacy - use contract_id instead)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    # Contract assignment
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)

    # Direct HHD assignment (alternative to technician assignment)
    assigned_hhd_id = Column(Integer, ForeignKey("handheld_devices.id"), nullable=True)

    # Scheduling
    scheduled_start = Column(DateTime, nullable=True)
    scheduled_end = Column(DateTime, nullable=True)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)

    # Billing
    is_billable = Column(Boolean, default=False)
    billing_status = Column(String, nullable=True)  # not_applicable, pending, invoiced, paid

    # Cost tracking (computed fields, can be overridden)
    estimated_labor_cost = Column(Numeric(12, 2), nullable=True)
    estimated_parts_cost = Column(Numeric(12, 2), nullable=True)
    estimated_total_cost = Column(Numeric(12, 2), nullable=True)

    actual_labor_cost = Column(Numeric(12, 2), nullable=True)
    actual_parts_cost = Column(Numeric(12, 2), nullable=True)
    actual_total_cost = Column(Numeric(12, 2), nullable=True)

    # Markup for billable work orders
    labor_markup_percent = Column(Numeric(5, 2), default=0)  # e.g., 20 for 20%
    parts_markup_percent = Column(Numeric(5, 2), default=0)

    # Final billing amount (after markup)
    billable_amount = Column(Numeric(12, 2), nullable=True)
    currency = Column(String, default="USD")

    # Completion
    completion_notes = Column(Text, nullable=True)
    requires_follow_up = Column(Boolean, default=False)
    follow_up_notes = Column(Text, nullable=True)

    # Approval workflow
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    # Cancellation workflow
    cancelled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    equipment = relationship("Equipment", backref="work_orders")
    sub_equipment = relationship("SubEquipment", backref="work_orders")
    site = relationship("Site", backref="work_orders")
    branch = relationship("Branch")
    floor = relationship("Floor")
    room = relationship("Room")
    project = relationship("Project", backref="work_orders")
    contract = relationship("Contract", backref="work_orders")
    assigned_hhd = relationship("HandHeldDevice", backref="assigned_work_orders")
    approver = relationship("User", foreign_keys=[approved_by])
    canceller = relationship("User", foreign_keys=[cancelled_by])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
    assigned_technicians = relationship("Technician", secondary=work_order_technicians, backref="work_orders")
    spare_parts_used = relationship("WorkOrderSparePart", back_populates="work_order", cascade="all, delete-orphan")
    time_entries = relationship("WorkOrderTimeEntry", back_populates="work_order", cascade="all, delete-orphan")
    checklist_items = relationship("WorkOrderChecklistItem", back_populates="work_order", cascade="all, delete-orphan", order_by="WorkOrderChecklistItem.item_number")
    snapshots = relationship("WorkOrderSnapshot", back_populates="work_order", cascade="all, delete-orphan")


class WorkOrderSparePart(Base):
    """Spare parts used in a work order"""
    __tablename__ = "work_order_spare_parts"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    spare_part_id = Column(Integer, ForeignKey("spare_parts.id"), nullable=False)

    # Quantity and pricing at time of use
    quantity = Column(Numeric(10, 2), nullable=False)
    unit_cost = Column(Numeric(12, 2), nullable=True)  # Snapshot of cost at time of use
    unit_price = Column(Numeric(12, 2), nullable=True)  # Price charged (if billable)
    total_cost = Column(Numeric(12, 2), nullable=True)  # quantity * unit_cost
    total_price = Column(Numeric(12, 2), nullable=True)  # quantity * unit_price

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    work_order = relationship("WorkOrder", back_populates="spare_parts_used")
    spare_part = relationship("SparePart")


class WorkOrderTimeEntry(Base):
    """Time tracking entries for work orders"""
    __tablename__ = "work_order_time_entries"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=False)

    # Time tracking
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    break_minutes = Column(Integer, default=0)

    # Computed/Override
    hours_worked = Column(Numeric(5, 2), nullable=True)
    is_overtime = Column(Boolean, default=False)

    # Cost snapshot
    hourly_rate = Column(Numeric(10, 2), nullable=True)  # Rate at time of entry
    overtime_rate = Column(Numeric(10, 2), nullable=True)
    total_cost = Column(Numeric(12, 2), nullable=True)

    # Details
    work_description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_order = relationship("WorkOrder", back_populates="time_entries")
    technician = relationship("Technician")


class WorkOrderChecklistItem(Base):
    """Checklist items for work orders (especially PM work orders)"""
    __tablename__ = "work_order_checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)

    # Item details
    item_number = Column(Integer, nullable=False)  # Order in the list
    description = Column(Text, nullable=False)
    is_completed = Column(Boolean, default=False)

    # Completion tracking
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)  # Notes added when completing

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_order = relationship("WorkOrder", back_populates="checklist_items")
    completer = relationship("User", foreign_keys=[completed_by])


class WorkOrderSnapshot(Base):
    """Snapshots/photos attached to work orders"""
    __tablename__ = "work_order_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # File info
    filename = Column(String, nullable=False)  # Stored filename (UUID-based)
    original_filename = Column(String, nullable=False)  # Original uploaded filename
    file_path = Column(String, nullable=False)  # Full path to file
    file_size = Column(Integer, nullable=True)  # File size in bytes
    mime_type = Column(String, nullable=True)  # MIME type (image/jpeg, etc.)

    # Metadata
    caption = Column(String(500), nullable=True)
    taken_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    taken_at = Column(DateTime, default=func.now())

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_order = relationship("WorkOrder", back_populates="snapshots")
    photographer = relationship("User", foreign_keys=[taken_by])


# ============================================================================
# Preventive Maintenance Hierarchy Models (from MMG)
# ============================================================================

class PMEquipmentClass(Base):
    """
    Level 1: Equipment Class (UDC = C2)
    e.g., 101 = HVAC, 102 = Electrical Power, 103 = Low Current
    """
    __tablename__ = "pm_equipment_classes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    code = Column(String, nullable=False, index=True)  # e.g., "101", "102"
    name = Column(String, nullable=False)  # e.g., "HVAC", "Electrical Power"
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="pm_equipment_classes")
    system_codes = relationship("PMSystemCode", back_populates="equipment_class", cascade="all, delete-orphan")


class PMSystemCode(Base):
    """
    Level 2: System Code (UDC = C6)
    e.g., H01 = Heating, H02 = Cooling (links to C2 via special_handling)
    """
    __tablename__ = "pm_system_codes"

    id = Column(Integer, primary_key=True, index=True)
    equipment_class_id = Column(Integer, ForeignKey("pm_equipment_classes.id"), nullable=False)
    code = Column(String, nullable=False, index=True)  # e.g., "H01", "H02"
    name = Column(String, nullable=False)  # e.g., "Heating", "Cooling"
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    equipment_class = relationship("PMEquipmentClass", back_populates="system_codes")
    asset_types = relationship("PMAssetType", back_populates="system_code", cascade="all, delete-orphan")


class PMAssetType(Base):
    """
    Level 3: Asset/Equipment Type (UDC = C7)
    e.g., 001 = Water Boiler (WATBOIL), links to C6 via special_handling
    """
    __tablename__ = "pm_asset_types"

    id = Column(Integer, primary_key=True, index=True)
    system_code_id = Column(Integer, ForeignKey("pm_system_codes.id"), nullable=False)
    code = Column(String, nullable=False, index=True)  # e.g., "001", "002"
    name = Column(String, nullable=False)  # e.g., "Water Boiler"
    pm_code = Column(String, nullable=True, index=True)  # e.g., "WATBOIL" - used to link to checklists
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    system_code = relationship("PMSystemCode", back_populates="asset_types")
    checklists = relationship("PMChecklist", back_populates="asset_type", cascade="all, delete-orphan")


class PMChecklist(Base):
    """
    Preventive Maintenance Checklist for an asset type
    Groups activities by frequency (1M = Monthly, 1Q = Quarterly, etc.)
    """
    __tablename__ = "pm_checklists"

    id = Column(Integer, primary_key=True, index=True)
    asset_type_id = Column(Integer, ForeignKey("pm_asset_types.id"), nullable=False)
    frequency_code = Column(String, nullable=False, index=True)  # "1W", "1M", "3M", "6M", "1Q", "1Y"
    frequency_name = Column(String, nullable=False)  # "Weekly", "Monthly", "Quarterly", etc.
    frequency_days = Column(Integer, nullable=False)  # 7, 30, 90, 180, 365
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    asset_type = relationship("PMAssetType", back_populates="checklists")
    activities = relationship("PMActivity", back_populates="checklist", cascade="all, delete-orphan")


class PMActivity(Base):
    """
    Individual maintenance activity/task within a checklist
    """
    __tablename__ = "pm_activities"

    id = Column(Integer, primary_key=True, index=True)
    checklist_id = Column(Integer, ForeignKey("pm_checklists.id"), nullable=False)
    sequence_order = Column(Integer, nullable=False)  # Line number from Excel
    description = Column(String, nullable=False)  # The actual activity description
    estimated_duration_minutes = Column(Integer, nullable=True)
    requires_measurement = Column(Boolean, default=False)
    measurement_unit = Column(String, nullable=True)  # e.g., "°C", "psi", "amps"
    is_critical = Column(Boolean, default=False)
    safety_notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    checklist = relationship("PMChecklist", back_populates="activities")


class PMSchedule(Base):
    """
    Tracks PM schedule for each equipment/checklist combination
    Used to determine when PM work orders are due
    """
    __tablename__ = "pm_schedules"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False)
    checklist_id = Column(Integer, ForeignKey("pm_checklists.id"), nullable=False)

    # Schedule tracking
    last_completed_date = Column(DateTime, nullable=True)  # When PM was last done
    last_work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    next_due_date = Column(DateTime, nullable=True)  # When next PM is due

    # Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    equipment = relationship("Equipment", backref="pm_schedules")
    checklist = relationship("PMChecklist")
    last_work_order = relationship("WorkOrder")

    # Unique constraint - one schedule per equipment/checklist combination
    __table_args__ = (
        UniqueConstraint('equipment_id', 'checklist_id', name='uq_equipment_checklist'),
    )


# ============================================================================
# Item Master & Inventory Management Models
# ============================================================================

class ItemCategory(Base):
    """
    Item categories based on MMG classification
    CV=Civil, EL=Electrical, TL=Tool, PL=Plumbing, MC=Mechanical,
    LGH=Lighting, SAN=Sanitary, HVC=HVAC
    """
    __tablename__ = "item_categories"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    code = Column(String(10), nullable=False, index=True)  # CV, EL, TL, PL, MC, LGH, SAN, HVC
    name = Column(String(100), nullable=False)  # Civil, Electrical, Tool, etc.
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="item_categories")
    items = relationship("ItemMaster", back_populates="category")

    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_company_item_category_code'),
    )


class ItemMaster(Base):
    """
    Item Master - Central repository of all spare parts/materials
    Each client creates their own item naming/numbering system
    """
    __tablename__ = "item_master"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Identification
    item_number = Column(String(50), nullable=False, index=True)  # Unique item code (e.g., CVCVL3M10001)
    short_item_no = Column(Integer, nullable=True)  # Short reference number

    # Description (concatenated from Description + Description 2)
    description = Column(String(500), nullable=False)
    search_text = Column(String(500), nullable=True)  # For search optimization

    # Classification
    category_id = Column(Integer, ForeignKey("item_categories.id"), nullable=True)

    # Stock settings
    stocking_type = Column(String(10), default="S")  # S=Stocked, O=Non-stocked
    line_type = Column(String(10), default="S")  # S=Stock, N=Non-stock
    unit = Column(String(20), default="pcs")  # Unit of measure: pcs, m, kg, L, etc.

    # Pricing
    unit_cost = Column(Numeric(12, 2), nullable=True)  # Standard cost
    unit_price = Column(Numeric(12, 2), nullable=True)  # Selling price
    currency = Column(String(10), default="USD")

    # Reorder settings
    minimum_stock_level = Column(Integer, default=0)
    reorder_quantity = Column(Integer, default=0)

    # Supplier info
    primary_vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    vendor_part_number = Column(String(100), nullable=True)

    # Additional info
    manufacturer = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    company = relationship("Company", backref="item_master")
    category = relationship("ItemCategory", back_populates="items")
    primary_vendor = relationship("Vendor", backref="supplied_items")
    creator = relationship("User", foreign_keys=[created_by])
    stock_levels = relationship("ItemStock", back_populates="item", cascade="all, delete-orphan")
    ledger_entries = relationship("ItemLedger", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('company_id', 'item_number', name='uq_company_item_number'),
    )


class ItemAlias(Base):
    """
    Aliases for Item Master items - stores vendor/supplier item codes.
    Allows multiple vendors to have different codes for the same item.
    Used for automatic matching during invoice processing.
    """
    __tablename__ = "item_aliases"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("item_master.id", ondelete="CASCADE"), nullable=False)

    # Alias details
    alias_code = Column(String(100), nullable=False, index=True)  # Vendor's item code (e.g., LG406481)
    alias_description = Column(String(500), nullable=True)  # Vendor's description if different
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)  # Optional: specific vendor

    # Metadata
    source = Column(String(50), default="manual")  # manual, invoice_link, import
    notes = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    company = relationship("Company")
    item = relationship("ItemMaster", backref="aliases")
    vendor = relationship("Vendor")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        UniqueConstraint('company_id', 'alias_code', name='uq_company_alias_code'),
    )


class ItemStock(Base):
    """
    Current stock levels per location (warehouse or HHD)
    Denormalized for quick stock queries
    """
    __tablename__ = "item_stock"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=False)

    # Location - either warehouse OR handheld device (one must be set)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    handheld_device_id = Column(Integer, ForeignKey("handheld_devices.id"), nullable=True)

    # Stock quantities
    quantity_on_hand = Column(Numeric(12, 2), default=0)  # Current available stock
    quantity_reserved = Column(Numeric(12, 2), default=0)  # Reserved for work orders
    quantity_on_order = Column(Numeric(12, 2), default=0)  # On order from vendor

    # Cost tracking
    average_cost = Column(Numeric(12, 2), nullable=True)  # Moving average cost
    last_cost = Column(Numeric(12, 2), nullable=True)  # Last purchase cost

    # Tracking
    last_count_date = Column(DateTime, nullable=True)
    last_movement_date = Column(DateTime, nullable=True)

    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    item = relationship("ItemMaster", back_populates="stock_levels")
    warehouse = relationship("Warehouse", backref="item_stock")
    handheld_device = relationship("HandHeldDevice", backref="item_stock")

    __table_args__ = (
        # Ensure unique stock record per item per location
        UniqueConstraint('item_id', 'warehouse_id', name='uq_item_warehouse_stock'),
        UniqueConstraint('item_id', 'handheld_device_id', name='uq_item_hhd_stock'),
    )


class ItemLedger(Base):
    """
    Item Ledger - Tracks all inventory transactions
    Every stock movement is recorded here for full traceability
    """
    __tablename__ = "item_ledger"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=False)

    # Transaction identification
    transaction_number = Column(String(50), nullable=False, index=True)  # Auto-generated
    transaction_date = Column(DateTime, nullable=False, default=func.now())

    # Transaction type
    transaction_type = Column(String(30), nullable=False)
    # Types:
    # - RECEIVE_INVOICE: Received from invoice into warehouse
    # - TRANSFER_OUT: Transfer out from warehouse to HHD
    # - TRANSFER_IN: Transfer into HHD from warehouse
    # - ISSUE_WORK_ORDER: Issued to work order from HHD
    # - RETURN_WORK_ORDER: Returned from work order to HHD
    # - ADJUSTMENT_PLUS: Positive adjustment
    # - ADJUSTMENT_MINUS: Negative adjustment
    # - INITIAL_STOCK: Initial stock entry

    # Quantity (positive for in, negative for out)
    quantity = Column(Numeric(12, 2), nullable=False)
    unit = Column(String(20), nullable=True)

    # Cost at time of transaction
    unit_cost = Column(Numeric(12, 2), nullable=True)
    total_cost = Column(Numeric(12, 2), nullable=True)

    # Location references (source and destination)
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    from_hhd_id = Column(Integer, ForeignKey("handheld_devices.id"), nullable=True)
    to_hhd_id = Column(Integer, ForeignKey("handheld_devices.id"), nullable=True)

    # Reference documents
    invoice_id = Column(Integer, ForeignKey("processed_images.id"), nullable=True)  # For RECEIVE_INVOICE
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)  # For ISSUE/RETURN
    transfer_id = Column(Integer, ForeignKey("item_transfers.id"), nullable=True)  # For TRANSFER

    # Running balance at this location after transaction
    balance_after = Column(Numeric(12, 2), nullable=True)

    # Notes and audit
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    company = relationship("Company")
    item = relationship("ItemMaster", back_populates="ledger_entries")
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    from_hhd = relationship("HandHeldDevice", foreign_keys=[from_hhd_id])
    to_hhd = relationship("HandHeldDevice", foreign_keys=[to_hhd_id])
    invoice = relationship("ProcessedImage")
    work_order = relationship("WorkOrder")
    transfer = relationship("ItemTransfer", back_populates="ledger_entries")
    creator = relationship("User", foreign_keys=[created_by])


class ItemTransfer(Base):
    """
    Transfer document for moving stock between locations
    Warehouse → HHD or Warehouse → Warehouse
    """
    __tablename__ = "item_transfers"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Transfer identification
    transfer_number = Column(String(50), nullable=False, index=True)
    transfer_date = Column(DateTime, nullable=False, default=func.now())

    # Status
    status = Column(String(20), default="draft")  # draft, pending, completed, cancelled

    # Source and destination
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    to_hhd_id = Column(Integer, ForeignKey("handheld_devices.id"), nullable=True)

    # Notes and audit
    notes = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    to_hhd = relationship("HandHeldDevice", backref="received_transfers")
    completer = relationship("User", foreign_keys=[completed_by])
    creator = relationship("User", foreign_keys=[created_by])
    lines = relationship("ItemTransferLine", back_populates="transfer", cascade="all, delete-orphan")
    ledger_entries = relationship("ItemLedger", back_populates="transfer")


class ItemTransferLine(Base):
    """
    Individual line items in a transfer document
    """
    __tablename__ = "item_transfer_lines"

    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("item_transfers.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=False)

    # Quantity
    quantity_requested = Column(Numeric(12, 2), nullable=False)
    quantity_transferred = Column(Numeric(12, 2), nullable=True)  # Actual transferred (may differ)
    unit = Column(String(20), nullable=True)

    # Cost at time of transfer
    unit_cost = Column(Numeric(12, 2), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    transfer = relationship("ItemTransfer", back_populates="lines")
    item = relationship("ItemMaster")


class InvoiceItem(Base):
    """
    Line items from processed invoices - links to Item Master for receiving
    """
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("processed_images.id", ondelete="CASCADE"), nullable=False)

    # Item reference (can be linked to item master or free text)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=True)
    item_description = Column(String(500), nullable=True)  # Free text from invoice
    item_number = Column(String(100), nullable=True)  # Part number from invoice

    # Quantity and pricing from invoice
    quantity = Column(Numeric(12, 2), nullable=True)
    unit = Column(String(20), nullable=True)
    unit_price = Column(Numeric(12, 2), nullable=True)
    total_price = Column(Numeric(12, 2), nullable=True)

    # Receiving status
    quantity_received = Column(Numeric(12, 2), default=0)
    receive_status = Column(String(20), default="pending")  # pending, partial, received
    received_to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    received_at = Column(DateTime, nullable=True)
    received_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    invoice = relationship("ProcessedImage", backref="invoice_items")
    item = relationship("ItemMaster")
    warehouse = relationship("Warehouse")
    receiver = relationship("User", foreign_keys=[received_by])


class CycleCount(Base):
    """
    Cycle Count document for physical inventory verification
    """
    __tablename__ = "cycle_counts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Count identification
    count_number = Column(String(50), nullable=False, index=True)  # e.g., CC-2025-00001
    count_date = Column(DateTime, nullable=False, default=func.now())

    # Location being counted
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)

    # Status: draft, in_progress, completed, cancelled
    status = Column(String(20), nullable=False, default="draft")

    # Count scope
    count_type = Column(String(20), nullable=False, default="full")  # full, partial, category
    category_id = Column(Integer, ForeignKey("item_categories.id"), nullable=True)  # For category-based counts

    # Summary fields (calculated on completion)
    total_items_counted = Column(Integer, default=0)
    items_with_variance = Column(Integer, default=0)
    total_variance_value = Column(Numeric(12, 2), default=0)

    # Audit
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    warehouse = relationship("Warehouse")
    category = relationship("ItemCategory")
    creator = relationship("User", foreign_keys=[created_by])
    completer = relationship("User", foreign_keys=[completed_by])
    items = relationship("CycleCountItem", back_populates="cycle_count", cascade="all, delete-orphan")


class CycleCountItem(Base):
    """
    Individual item counts within a cycle count
    """
    __tablename__ = "cycle_count_items"

    id = Column(Integer, primary_key=True, index=True)
    cycle_count_id = Column(Integer, ForeignKey("cycle_counts.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=False)

    # System quantity at time of count
    system_quantity = Column(Numeric(12, 2), nullable=False, default=0)

    # Counted quantity (entered by user)
    counted_quantity = Column(Numeric(12, 2), nullable=True)

    # Variance (calculated: counted - system)
    variance_quantity = Column(Numeric(12, 2), nullable=True)
    variance_value = Column(Numeric(12, 2), nullable=True)  # variance_quantity * unit_cost

    # Cost at time of count
    unit_cost = Column(Numeric(12, 2), nullable=True)

    # Status: pending, counted, adjusted
    status = Column(String(20), nullable=False, default="pending")

    # Audit
    counted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    counted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    cycle_count = relationship("CycleCount", back_populates="items")
    item = relationship("ItemMaster")
    counter = relationship("User", foreign_keys=[counted_by])

# ============================================================================
# New Location Hierarchy Models (Site, Building, Space)
# ============================================================================

class Site(Base):
    """
    Site - Location/facility of a client (replaces Branch concept for asset hierarchy)
    Client -> Site -> Building -> Space/Floor -> Room
    """
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True, index=True)  # Site code for reference
    address = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)  # GPS coordinates
    longitude = Column(Float, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    site_manager = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    client = relationship("Client", backref="sites")
    blocks = relationship("Block", back_populates="site", cascade="all, delete-orphan")
    buildings = relationship("Building", back_populates="site", cascade="all, delete-orphan")
    spaces = relationship("Space", back_populates="site", cascade="all, delete-orphan")
    operators = relationship("User", secondary=operator_sites, backref="assigned_sites")
    contracts = relationship("Contract", secondary=contract_sites, back_populates="sites")
    projects = relationship("Project", back_populates="site", cascade="all, delete-orphan")


class Block(Base):
    """
    Block within a Site - A grouping of buildings or a subdivision of the site
    Examples: Block A, North Wing, Phase 1, Zone A
    """
    __tablename__ = "blocks"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g., "Block A", "North Wing", "Phase 1"
    code = Column(String, nullable=True, index=True)  # Block code
    block_type = Column(String, nullable=True)  # Zone, Wing, Phase, Sector, etc.
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    site = relationship("Site", back_populates="blocks")
    buildings = relationship("Building", back_populates="block", cascade="all, delete-orphan")


class Building(Base):
    """
    Building within a Site or Block
    Building can have both Spaces (direct) and Floors
    Can belong to a Site directly OR to a Block within a Site
    """
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)  # For direct site-level buildings
    block_id = Column(Integer, ForeignKey("blocks.id"), nullable=True)  # For buildings within a block
    name = Column(String, nullable=False)  # e.g., "Main Building", "Tower A", "Warehouse"
    code = Column(String, nullable=True, index=True)  # Building code
    building_type = Column(String, nullable=True)  # Office, Warehouse, Residential, Industrial, etc.
    address = Column(Text, nullable=True)  # Building-specific address if different from site
    total_floors = Column(Integer, nullable=True)  # Number of floors
    total_area_sqm = Column(Float, nullable=True)  # Total building area
    year_built = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    site = relationship("Site", back_populates="buildings")
    block = relationship("Block", back_populates="buildings")
    floors = relationship("Floor", back_populates="building", cascade="all, delete-orphan")
    spaces = relationship("Space", back_populates="building", cascade="all, delete-orphan")


class Space(Base):
    """
    Space - Direct area under a Site or Building (not on a specific floor)
    Examples: Parking lot, Courtyard, Rooftop, External area, Garden
    Can be attached to either a Site directly or to a Building
    """
    __tablename__ = "spaces"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)  # For site-level spaces
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)  # For building-level spaces
    name = Column(String, nullable=False)  # e.g., "Parking Lot A", "Rooftop", "Courtyard"
    code = Column(String, nullable=True, index=True)
    space_type = Column(String, nullable=True)  # Parking, Outdoor, Rooftop, Common Area, etc.
    area_sqm = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    site = relationship("Site", back_populates="spaces")
    building = relationship("Building", back_populates="spaces")


# ============================================================================
# Contract Management Models
# ============================================================================

class Scope(Base):
    """
    Reference table for contract scope types
    Examples: HVAC, Spare Parts, Labor, Subcontractor, Electrical, Plumbing, Fire Safety
    """
    __tablename__ = "scopes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)  # HVAC, Spare Parts, Labor, etc.
    code = Column(String, nullable=True, index=True)  # Short code
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="scopes")

    __table_args__ = (
        UniqueConstraint('company_id', 'name', name='uq_company_scope_name'),
    )


class Contract(Base):
    """
    Contract under a Client
    One client can have multiple contracts
    Each contract can cover multiple sites
    """
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    
    # Contract identification
    contract_number = Column(String, nullable=False, index=True)  # Auto-generated or manual
    name = Column(String, nullable=False)  # Contract name/title
    description = Column(Text, nullable=True)
    
    # Contract type
    # comprehensive: Full coverage including parts
    # non_comprehensive: Labor only
    # with_threshold: Parts covered up to threshold amount
    contract_type = Column(String, nullable=False, default="comprehensive")
    threshold_amount = Column(Numeric(12, 2), nullable=True)  # For with_threshold type
    threshold_period = Column(String, nullable=True)  # per_work_order, monthly, yearly, contract_period
    
    # Dates
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    
    # Financials
    contract_value = Column(Numeric(14, 2), nullable=True)  # Total contract value
    budget = Column(Numeric(14, 2), nullable=True)  # Budget allocation
    currency = Column(String(10), default="USD")
    
    # Status
    status = Column(String, default="draft")  # draft, active, expired, terminated, renewed
    
    # Renewal
    is_renewable = Column(Boolean, default=False)
    renewal_notice_days = Column(Integer, nullable=True)  # Days before end to notify for renewal
    auto_renew = Column(Boolean, default=False)
    
    # Documents
    document_url = Column(String, nullable=True)  # Link to contract document
    
    # Notes
    notes = Column(Text, nullable=True)
    terms_conditions = Column(Text, nullable=True)
    
    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="contracts")
    client = relationship("Client", backref="contracts")
    sites = relationship("Site", secondary=contract_sites, back_populates="contracts")
    scopes = relationship("ContractScope", back_populates="contract", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class ContractScope(Base):
    """
    Scope items within a contract with their specific SLA
    Each contract can have multiple scopes, each with its own SLA
    """
    __tablename__ = "contract_scopes"

    id = Column(Integer, primary_key=True, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    scope_id = Column(Integer, ForeignKey("scopes.id"), nullable=False)
    
    # Scope-specific budget (optional, can allocate budget per scope)
    allocated_budget = Column(Numeric(12, 2), nullable=True)
    
    # SLA - Response Time
    sla_response_time_hours = Column(Integer, nullable=True)  # Hours to respond
    sla_response_time_priority_low = Column(Integer, nullable=True)  # Hours for low priority
    sla_response_time_priority_medium = Column(Integer, nullable=True)  # Hours for medium priority
    sla_response_time_priority_high = Column(Integer, nullable=True)  # Hours for high priority
    sla_response_time_priority_critical = Column(Integer, nullable=True)  # Hours for critical
    
    # SLA - Resolution Time
    sla_resolution_time_hours = Column(Integer, nullable=True)  # Hours to resolve
    sla_resolution_time_priority_low = Column(Integer, nullable=True)
    sla_resolution_time_priority_medium = Column(Integer, nullable=True)
    sla_resolution_time_priority_high = Column(Integer, nullable=True)
    sla_resolution_time_priority_critical = Column(Integer, nullable=True)
    
    # SLA - Availability
    sla_availability_percent = Column(Numeric(5, 2), nullable=True)  # e.g., 99.9%
    
    # SLA - Penalties
    sla_penalty_response_breach = Column(Numeric(10, 2), nullable=True)  # Penalty amount per breach
    sla_penalty_resolution_breach = Column(Numeric(10, 2), nullable=True)
    sla_penalty_availability_breach = Column(Numeric(10, 2), nullable=True)
    sla_penalty_calculation = Column(String, nullable=True)  # fixed, percentage, per_hour
    
    # Scope-specific notes
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    contract = relationship("Contract", back_populates="scopes")
    scope = relationship("Scope")

    __table_args__ = (
        UniqueConstraint('contract_id', 'scope_id', name='uq_contract_scope'),
    )


# ============================================================================
# Ticketing System Models
# ============================================================================

class Ticket(Base):
    """
    Ticket/Service Request - Users can submit requests that can be converted to work orders
    """
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Ticket identification
    ticket_number = Column(String, nullable=False, unique=True, index=True)  # Auto-generated TKT-YYYYMMDD-XXXX

    # Request details
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    # Category/Type
    category = Column(String(50), nullable=False)  # maintenance, repair, installation, inspection, other

    # Priority
    priority = Column(String(20), default="medium")  # low, medium, high, urgent

    # Status
    status = Column(String(20), default="open")  # open, in_review, approved, converted, rejected, closed

    # Location (optional but recommended)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    location_description = Column(String(500), nullable=True)  # Free text location if not in hierarchy

    # Equipment reference (optional)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True)

    # Requester info
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    requester_name = Column(String(200), nullable=True)  # Can be different from logged-in user
    requester_email = Column(String(200), nullable=True)
    requester_phone = Column(String(50), nullable=True)

    # Preferred scheduling
    preferred_date = Column(Date, nullable=True)
    preferred_time_slot = Column(String(50), nullable=True)  # morning, afternoon, evening, anytime

    # Attachments (stored as JSON array of file paths)
    attachments = Column(Text, nullable=True)  # JSON array

    # Work order linkage (after conversion)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    converted_at = Column(DateTime, nullable=True)
    converted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Review/Approval
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Internal notes (for admins)
    internal_notes = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="tickets")
    site = relationship("Site", backref="tickets")
    building = relationship("Building", backref="tickets")
    floor = relationship("Floor", backref="tickets")
    room = relationship("Room", backref="tickets")
    equipment = relationship("Equipment", backref="tickets")
    requester = relationship("User", foreign_keys=[requested_by], backref="submitted_tickets")
    converter = relationship("User", foreign_keys=[converted_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    work_order = relationship("WorkOrder", backref="source_ticket")
