from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Float, Date, Numeric, Table, UniqueConstraint, Time
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func
from app.database import Base

# DEPRECATED: Association table for Operator-Branch - Use operator_sites instead
# Keeping table definition to avoid migration issues with existing data
operator_branches = Table(
    'operator_branches',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('branch_id', Integer, ForeignKey('branches.id'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now())
)

# Association table for HandHeldDevice-Technician many-to-many relationship (Legacy)
handheld_device_technicians = Table(
    'handheld_device_technicians',
    Base.metadata,
    Column('handheld_device_id', Integer, ForeignKey('handheld_devices.id', ondelete='CASCADE'), primary_key=True),
    Column('technician_id', Integer, ForeignKey('technicians.id', ondelete='CASCADE'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now()),
    Column('is_primary', Boolean, default=False),
    Column('notes', Text, nullable=True)
)

# Association table for HandHeldDevice-AddressBook (Employee) many-to-many relationship
handheld_device_technicians_ab = Table(
    'handheld_device_technicians_ab',
    Base.metadata,
    Column('handheld_device_id', Integer, ForeignKey('handheld_devices.id', ondelete='CASCADE'), primary_key=True),
    Column('address_book_id', Integer, ForeignKey('address_book.id', ondelete='CASCADE'), primary_key=True),
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
    company_code = Column(String, unique=True, nullable=True, index=True)  # Unique code for mobile app login
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
    primary_currency = Column(String(3), default='USD')  # ISO 4217 currency code
    industry = Column(String, nullable=True)
    size = Column(String, nullable=True)  # "1-10", "11-50", "51-200", etc.

    # Tax Settings
    default_vat_rate = Column(Numeric(5, 2), default=15.00)  # Default VAT/Tax rate (e.g., 15.00 for 15%)

    # Subscription info
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    subscription_status = Column(String, default="trial")  # trial, active, suspended, cancelled
    subscription_start = Column(DateTime, nullable=True)
    subscription_end = Column(DateTime, nullable=True)
    documents_used_this_month = Column(Integer, default=0)

    # Custom limits (override plan limits when set)
    max_users_override = Column(Integer, nullable=True)  # Override plan's max_users if set
    documents_limit_override = Column(Integer, nullable=True)  # Override plan's documents_max if set

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    plan = relationship("Plan", back_populates="companies")
    users = relationship("User", back_populates="company")
    clients = relationship("Client", back_populates="company")


class Client(Base):
    """Client/Customer of a company - linked to Address Book for master data"""
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

    # Address Book link - connects Client to Address Book entry (type C)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Relationships
    company = relationship("Company", back_populates="clients")
    # DEPRECATED: branches relationship - use Sites instead
    # branches = relationship("Branch", back_populates="client")
    address_book = relationship("AddressBook", backref="client")


# DEPRECATED: Branch model - Use Site model instead
# Keeping model definition to avoid migration issues with existing data
class Branch(Base):
    """DEPRECATED: Branch/Location of a client - Use Site instead"""
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

    # Address Book link (for transition to Address Book as master data)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Relationships - DEPRECATED
    client = relationship("Client")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    # operators = relationship("User", secondary=operator_branches, back_populates="assigned_branches")  # Use operator_sites
    # floors = relationship("Floor", back_populates="branch")  # Use Floor.site instead

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
    role = Column(String, default="admin")  # admin, operator, accounting, approver
    phone = Column(String, nullable=True)

    # PR Approval settings
    can_approve_pr = Column(Boolean, default=False)  # Can this user approve purchase requests?
    approval_limit = Column(Numeric(15, 2), nullable=True)  # Max amount user can approve (NULL = unlimited for admins)
    can_convert_po = Column(Boolean, default=False)  # Can this user convert approved PRs to Purchase Orders?

    # Work Order Approval settings
    can_approve_wo = Column(Boolean, default=False)  # Can this user approve work orders?

    # Link to Address Book employee record (search_type='E')
    # This allows users to have associated petty cash funds, attendance, etc.
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="users")
    processed_images = relationship("ProcessedImage", back_populates="user")
    # DEPRECATED: Use assigned_sites via operator_sites table instead
    # assigned_branches = relationship("Branch", secondary=operator_branches, back_populates="operators")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id], backref="user_account")


class SuperAdmin(Base):
    """Platform super admin for managing all companies and subscriptions"""
    __tablename__ = "super_admins"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)


class SuperAdminRefreshToken(Base):
    """Refresh tokens for super admin authentication"""
    __tablename__ = "super_admin_refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    super_admin_id = Column(Integer, ForeignKey("super_admins.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now())
    is_revoked = Column(Boolean, default=False)

    # Relationships
    super_admin = relationship("SuperAdmin", backref="refresh_tokens")


class UpgradeRequest(Base):
    """Upgrade/subscription change requests from companies"""
    __tablename__ = "upgrade_requests"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    current_plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    requested_plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    request_type = Column(String, nullable=False)  # upgrade, downgrade, renewal, custom
    status = Column(String, default="pending")  # pending, approved, rejected, completed
    message = Column(Text, nullable=True)  # User's message/reason for upgrade
    admin_notes = Column(Text, nullable=True)  # Platform admin notes
    processed_by_id = Column(Integer, ForeignKey("super_admins.id"), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="upgrade_requests")
    requested_by = relationship("User", backref="upgrade_requests")
    current_plan = relationship("Plan", foreign_keys=[current_plan_id])
    requested_plan = relationship("Plan", foreign_keys=[requested_plan_id])
    processed_by = relationship("SuperAdmin", backref="processed_upgrade_requests")


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
    posting_status = Column(String, nullable=True)  # pending, posted - tracks if invoice items were posted to inventory

    # Project linkage for multi-tenant structure
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)

    # Site linkage
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    # Contract linkage
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)

    # Vendor linkage - Address Book (search_type='V')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

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
    site = relationship("Site", backref="invoices")
    contract = relationship("Contract", backref="invoices")
    address_book = relationship("AddressBook", backref="invoices")


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


# REMOVED: Vendor model - Use AddressBook with search_type='V' instead
# Legacy vendors table kept in database for data migration purposes only


class Warehouse(Base):
    """Warehouse/Storage location belonging to a company"""
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Business Unit - links warehouse to accounting (JDE concept)
    # All inventory transactions for this warehouse will post to this BU
    business_unit_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)

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
    business_unit = relationship("BusinessUnit", backref="warehouses")


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

    # DEPRECATED: Salary fields are now in AddressBook (search_type='E')
    # These fields are kept for backward compatibility during migration
    # Use AddressBook salary fields for new implementations
    salary_type = Column(String, default="monthly")  # DEPRECATED
    base_salary = Column(Numeric(12, 2), nullable=True)  # DEPRECATED
    currency = Column(String, default="USD")  # DEPRECATED
    hourly_rate = Column(Numeric(10, 2), nullable=True)  # DEPRECATED
    overtime_rate_multiplier = Column(Numeric(4, 2), default=1.5)  # DEPRECATED
    working_hours_per_day = Column(Numeric(4, 2), default=8.0)  # DEPRECATED
    working_days_per_month = Column(Integer, default=22)  # DEPRECATED

    # DEPRECATED: Additional compensation - use AddressBook
    transport_allowance = Column(Numeric(10, 2), nullable=True)  # DEPRECATED
    housing_allowance = Column(Numeric(10, 2), nullable=True)  # DEPRECATED
    food_allowance = Column(Numeric(10, 2), nullable=True)  # DEPRECATED
    other_allowances = Column(Numeric(10, 2), nullable=True)  # DEPRECATED
    allowances_notes = Column(Text, nullable=True)  # DEPRECATED

    # DEPRECATED: Deductions - use AddressBook
    social_security_rate = Column(Numeric(5, 4), nullable=True)  # DEPRECATED
    tax_rate = Column(Numeric(5, 4), nullable=True)  # DEPRECATED
    other_deductions = Column(Numeric(10, 2), nullable=True)  # DEPRECATED
    deductions_notes = Column(Text, nullable=True)  # DEPRECATED

    # Address Book link (Employee type - search_type='E')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Relationships
    company = relationship("Company")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    assigned_device = relationship("HandHeldDevice", back_populates="assigned_technician", uselist=False)
    assigned_devices = relationship("HandHeldDevice", secondary="handheld_device_technicians", back_populates="assigned_technicians")
    site_shifts = relationship("TechnicianSiteShift", back_populates="technician", cascade="all, delete-orphan")

class TechnicianSiteShift(Base):
    __tablename__ = "technician_site_shifts"

    id = Column(Integer, primary_key=True)

    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True, index=True)  # Legacy

    # Address Book employee (replaces technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True, index=True)

    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)

    day_of_week = Column(Integer, nullable=False)  # 0 = Monday, 6 = Sunday

    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    technician = relationship("Technician", back_populates="site_shifts")
    address_book = relationship("AddressBook")
    site = relationship("Site", back_populates="technician_shifts")


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
    assigned_technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy
    assigned_at = Column(DateTime, nullable=True)  # When technician was assigned

    # Address Book employee assignment (replaces assigned_technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Mobile app authentication
    mobile_pin = Column(String, nullable=True)  # PIN for mobile app login (4-6 digits)

    # Device status
    status = Column(String, default="available")  # available, assigned, maintenance, retired
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # FCM Push Notifications
    fcm_token = Column(String, nullable=True)  # Firebase Cloud Messaging token
    fcm_token_updated_at = Column(DateTime, nullable=True)  # When token was last updated

    # Relationships
    company = relationship("Company")
    warehouse = relationship("Warehouse", backref="handheld_devices")
    assigned_technician = relationship("Technician", back_populates="assigned_device")  # Legacy
    assigned_technicians = relationship("Technician", secondary="handheld_device_technicians", back_populates="assigned_devices")  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])


class Floor(Base):
    """Floor within a building/site for asset capturing"""
    __tablename__ = "floors"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)  # Direct link to Site
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
    site = relationship("Site", back_populates="floors")
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

    # Address Book link (for transition to Address Book as master data)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

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
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
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

    # Address Book link (for transition to Address Book as master data)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

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
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
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
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy
    date = Column(Date, nullable=False, index=True)  # The date of attendance

    # Address Book employee (replaces technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

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
    technician = relationship("Technician", backref="attendance_records")  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    approver = relationship("User", foreign_keys=[leave_approved_by])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


# Association table for WorkOrder-Technician many-to-many relationship (Legacy)
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

# Association table for WorkOrder-AddressBook Employee many-to-many relationship
work_order_technicians_ab = Table(
    'work_order_technicians_ab',
    Base.metadata,
    Column('work_order_id', Integer, ForeignKey('work_orders.id'), primary_key=True),
    Column('address_book_id', Integer, ForeignKey('address_book.id'), primary_key=True),
    Column('assigned_at', DateTime, default=func.now()),
    Column('hours_worked', Numeric(5, 2), nullable=True),  # Hours this employee worked on this WO
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
    assigned_technicians = relationship("Technician", secondary=work_order_technicians, backref="work_orders")  # Legacy
    assigned_employees = relationship("AddressBook", secondary=work_order_technicians_ab, backref="assigned_work_orders")
    spare_parts_used = relationship("WorkOrderSparePart", back_populates="work_order", cascade="all, delete-orphan")
    time_entries = relationship("WorkOrderTimeEntry", back_populates="work_order", cascade="all, delete-orphan")
    checklist_items = relationship("WorkOrderChecklistItem", back_populates="work_order", cascade="all, delete-orphan", order_by="WorkOrderChecklistItem.item_number")
    snapshots = relationship("WorkOrderSnapshot", back_populates="work_order", cascade="all, delete-orphan")
    completion = relationship("WorkOrderCompletion", back_populates="work_order", uselist=False, cascade="all, delete-orphan")


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
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy

    # Address Book employee (replaces technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

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
    technician = relationship("Technician")  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])


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


class WorkOrderCompletion(Base):
    """Client rating, comments, and signature for work order completion"""
    __tablename__ = "work_order_completions"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Client rating (1-5 stars)
    rating = Column(Integer, nullable=True)  # 1-5 scale

    # Client comments
    comments = Column(Text, nullable=True)

    # Signature file info
    signature_filename = Column(String, nullable=True)  # Stored filename (UUID-based)
    signature_path = Column(String, nullable=True)  # Full path to signature file

    # Who signed and when
    signed_by_name = Column(String(255), nullable=True)  # Client name who signed
    signed_at = Column(DateTime, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # HHD user who captured this
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_order = relationship("WorkOrder", back_populates="completion")
    company = relationship("Company")
    creator = relationship("User", foreign_keys=[created_by])


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

    # Supplier info - Address Book (search_type='V')
    primary_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)
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
    primary_address_book = relationship("AddressBook", backref="supplied_items")
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
    # Vendor - Address Book (search_type='V')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Metadata
    source = Column(String(50), default="manual")  # manual, invoice_link, import
    notes = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    company = relationship("Company")
    item = relationship("ItemMaster", backref="aliases")
    address_book = relationship("AddressBook")
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

    # Business Unit - derived from warehouse for accounting integration
    business_unit_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)

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
    business_unit = relationship("BusinessUnit", backref="item_ledger_entries")
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

    Now linked to Address Book for master data management.
    """
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)  # Legacy - use address_book_id for new sites
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

    # Address Book link - connects Site to Address Book entry (type CB)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Relationships
    client = relationship("Client", backref="sites")
    address_book = relationship("AddressBook", backref="site")
    blocks = relationship("Block", back_populates="site", cascade="all, delete-orphan")
    buildings = relationship("Building", back_populates="site", cascade="all, delete-orphan")
    spaces = relationship("Space", back_populates="site", cascade="all, delete-orphan")
    floors = relationship("Floor", back_populates="site", cascade="all, delete-orphan")  # Direct floor relationship for assets
    operators = relationship("User", secondary=operator_sites, backref="assigned_sites")
    contracts = relationship("Contract", secondary=contract_sites, back_populates="sites")
    projects = relationship("Project", back_populates="site", cascade="all, delete-orphan")
    technician_shifts = relationship("TechnicianSiteShift", back_populates="site", cascade="all, delete-orphan"
)



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
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)  # Legacy - use address_book_id for new contracts

    # Address Book link (for transition to Address Book as master data)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

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
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
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
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # Null for client portal submissions
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

    # Source tracking (where the ticket was submitted from)
    source = Column(String(50), default="admin_portal")  # admin_portal, client_portal, email, api

    # Client portal user reference (if submitted via client portal)
    client_user_id = Column(Integer, ForeignKey("client_users.id"), nullable=True)

    # Service reference (optional, for categorization)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=True)

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
    client_user = relationship("ClientUser", backref="tickets")
    service = relationship("Service", backref="tickets")


class TicketActivity(Base):
    """
    Activity/Timeline entry for a Ticket/Service Request.
    Tracks ticket lifecycle events and user-added notes.
    """
    __tablename__ = "ticket_activities"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)

    # Activity type: ticket_created, status_changed, approved, rejected, converted, note
    activity_type = Column(String(50), nullable=False)

    # Content
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Status change tracking
    previous_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)

    # Flexible metadata (JSON for additional data like rejection_reason, work_order_id, etc.)
    extra_data = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), index=True)

    # Soft delete for notes
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    company = relationship("Company")
    ticket = relationship("Ticket", backref="activities")
    creator = relationship("User", foreign_keys=[created_by])
    deleter = relationship("User", foreign_keys=[deleted_by])


# ============================================================================
# Calendar & Scheduling Models
# ============================================================================

class CalendarSlot(Base):
    """
    Represents an available time slot that can be booked for work order visits.
    Slots are hourly increments throughout the day.
    """
    __tablename__ = "calendar_slots"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Date and time
    slot_date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)  # e.g., 09:00
    end_time = Column(Time, nullable=False)    # e.g., 10:00

    # Capacity (how many work orders can be scheduled in this slot)
    max_capacity = Column(Integer, default=1)
    current_bookings = Column(Integer, default=0)

    # Technician assignment (optional - slot can be for specific technician)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy

    # Address Book employee (replaces technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Site context (optional - slot can be site-specific)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    # Status
    status = Column(String, default="available")  # available, fully_booked, blocked

    # Metadata
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="calendar_slots")
    technician = relationship("Technician", backref="calendar_slots")  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    site = relationship("Site", backref="calendar_slots")
    creator = relationship("User", foreign_keys=[created_by])
    assignments = relationship("WorkOrderSlotAssignment", back_populates="calendar_slot", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('company_id', 'slot_date', 'start_time', 'technician_id', name='uq_slot_date_time_technician'),
    )


class WorkOrderSlotAssignment(Base):
    """
    Links work orders to calendar slots.
    A work order can be assigned to one or more slots.
    """
    __tablename__ = "work_order_slot_assignments"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    calendar_slot_id = Column(Integer, ForeignKey("calendar_slots.id", ondelete="CASCADE"), nullable=False)

    # Assignment details
    assigned_at = Column(DateTime, default=func.now())
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Address Book employee assignment (derived from calendar_slot or direct)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Status
    status = Column(String, default="scheduled")  # scheduled, confirmed, completed, cancelled

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_order = relationship("WorkOrder", backref="slot_assignments")
    calendar_slot = relationship("CalendarSlot", back_populates="assignments")
    assigner = relationship("User", foreign_keys=[assigned_by])
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])

    __table_args__ = (
        UniqueConstraint('work_order_id', 'calendar_slot_id', name='uq_work_order_slot'),
    )


class CalendarTemplate(Base):
    """
    Template for generating recurring calendar slots automatically.
    Defines working hours and days for a company.
    """
    __tablename__ = "calendar_templates"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    name = Column(String, nullable=False)  # e.g., "Standard Work Week"

    # Days of week (JSON array: [0,1,2,3,4] for Mon-Fri, where 0=Monday)
    days_of_week = Column(Text, nullable=False)

    # Working hours
    start_hour = Column(Integer, default=8)   # 8 AM
    end_hour = Column(Integer, default=17)    # 5 PM
    slot_duration_minutes = Column(Integer, default=60)  # 1 hour slots

    # Break time (optional)
    break_start_hour = Column(Integer, nullable=True)  # e.g., 12
    break_end_hour = Column(Integer, nullable=True)    # e.g., 13

    # Capacity per slot
    default_capacity = Column(Integer, default=1)

    # Technician (optional - template can be technician-specific)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="calendar_templates")
    technician = relationship("Technician", backref="calendar_templates")


# ============================================================================
# Condition Report Models
# ============================================================================

class ConditionReport(Base):
    """
    Condition Report created by HHD users to document issues at client sites.
    Contains issue description, classification, estimated cost, and images.
    """
    __tablename__ = "condition_reports"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)  # Legacy: Can be null if using address_book_id

    # Address Book link (for transition to Address Book as master data)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)  # New: Use this for customers

    # Report details
    report_number = Column(String, nullable=True, index=True)  # Auto-generated: CR-YYYYMMDD-XXX
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)

    # Classification
    issue_class = Column(String(50), nullable=False)  # civil, mechanical, electrical, others

    # Cost estimation
    estimated_cost = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), default="USD")

    # Location context (optional)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=True)
    space_id = Column(Integer, ForeignKey("spaces.id"), nullable=True)
    location_notes = Column(Text, nullable=True)  # Additional location details

    # Status tracking
    status = Column(String(50), default="submitted")  # submitted, under_review, approved, rejected, resolved

    # Priority
    priority = Column(String(20), default="medium")  # low, medium, high, critical

    # Audit fields
    collected_by = Column(Integer, ForeignKey("users.id"), nullable=False)  # HHD user who created
    collected_at = Column(DateTime, default=func.now())
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="condition_reports")
    client = relationship("Client", backref="condition_reports")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    site = relationship("Site", backref="condition_reports")
    building = relationship("Building", backref="condition_reports")
    floor = relationship("Floor", backref="condition_reports")
    space = relationship("Space", backref="condition_reports")
    collector = relationship("User", foreign_keys=[collected_by], backref="collected_condition_reports")
    reviewer = relationship("User", foreign_keys=[reviewed_by], backref="reviewed_condition_reports")
    images = relationship("ConditionReportImage", back_populates="condition_report", cascade="all, delete-orphan")


class ConditionReportImage(Base):
    """
    Images attached to a condition report.
    Each condition report can have multiple images.
    """
    __tablename__ = "condition_report_images"

    id = Column(Integer, primary_key=True, index=True)
    condition_report_id = Column(Integer, ForeignKey("condition_reports.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # File info
    filename = Column(String, nullable=False)  # Stored filename (UUID-based)
    original_filename = Column(String, nullable=False)  # Original uploaded filename
    file_path = Column(String, nullable=False)  # Full path or S3 key
    file_size = Column(Integer, nullable=True)  # File size in bytes
    mime_type = Column(String, nullable=True)  # MIME type (image/jpeg, etc.)

    # Metadata
    caption = Column(String(500), nullable=True)
    sort_order = Column(Integer, default=0)

    # Audit
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=func.now())

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    condition_report = relationship("ConditionReport", back_populates="images")
    company = relationship("Company")
    uploader = relationship("User", foreign_keys=[uploaded_by])


# ============================================================================
# Technician Evaluation Models (HR Service)
# ============================================================================

class TechnicianEvaluation(Base):
    """
    Technician Performance Evaluation for HR purposes.
    Tracks periodic performance assessments of technicians.
    """
    __tablename__ = "technician_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy

    # Address Book employee (replaces technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Evaluation period
    evaluation_period = Column(String(50), nullable=False)  # monthly, quarterly, semi-annual, annual
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)

    # Performance Metrics (1-5 scale)
    attendance_score = Column(Integer, nullable=True)  # Punctuality and attendance
    quality_score = Column(Integer, nullable=True)  # Quality of work
    productivity_score = Column(Integer, nullable=True)  # Work output/efficiency
    teamwork_score = Column(Integer, nullable=True)  # Team collaboration
    safety_score = Column(Integer, nullable=True)  # Safety compliance
    communication_score = Column(Integer, nullable=True)  # Communication skills
    initiative_score = Column(Integer, nullable=True)  # Proactiveness
    technical_skills_score = Column(Integer, nullable=True)  # Technical competency

    # Overall assessment
    overall_score = Column(Numeric(3, 2), nullable=True)  # Calculated average
    overall_rating = Column(String(20), nullable=True)  # excellent, good, satisfactory, needs_improvement, poor

    # Detailed feedback
    strengths = Column(Text, nullable=True)
    areas_for_improvement = Column(Text, nullable=True)
    goals_for_next_period = Column(Text, nullable=True)
    evaluator_comments = Column(Text, nullable=True)
    technician_comments = Column(Text, nullable=True)  # Self-assessment/response

    # Status tracking
    status = Column(String(50), default="draft")  # draft, submitted, acknowledged, finalized

    # Audit fields
    evaluated_by = Column(Integer, ForeignKey("users.id"), nullable=False)  # HR/Supervisor who created
    evaluated_at = Column(DateTime, nullable=True)
    acknowledged_by_technician = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="technician_evaluations")
    technician = relationship("Technician", backref="evaluations")  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    evaluator = relationship("User", foreign_keys=[evaluated_by], backref="conducted_evaluations")


# ============================================================================
# Net Promoter Score (NPS) Models
# ============================================================================

class NPSSurvey(Base):
    """
    Net Promoter Score Survey for measuring client satisfaction.
    NPS Score: 0-10 scale
    - Promoters (9-10): Loyal enthusiasts
    - Passives (7-8): Satisfied but unenthusiastic
    - Detractors (0-6): Unhappy customers
    NPS = % Promoters - % Detractors
    """
    __tablename__ = "nps_surveys"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)

    # Address Book link (for transition to Address Book as master data)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Survey details
    survey_date = Column(Date, nullable=False)
    survey_type = Column(String(50), default="general")  # general, post_service, quarterly, annual

    # NPS Score (0-10)
    score = Column(Integer, nullable=False)  # 0-10 scale

    # Classification (calculated from score)
    category = Column(String(20), nullable=False)  # promoter, passive, detractor

    # Feedback
    feedback = Column(Text, nullable=True)  # Open-ended feedback
    would_recommend_reason = Column(Text, nullable=True)  # Why they would/wouldn't recommend

    # Context - optional link to work order or service
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    # Contact info
    respondent_name = Column(String(255), nullable=True)
    respondent_email = Column(String(255), nullable=True)
    respondent_phone = Column(String(50), nullable=True)
    respondent_role = Column(String(100), nullable=True)  # e.g., "Facility Manager", "Owner"

    # Follow-up tracking
    requires_follow_up = Column(Boolean, default=False)
    follow_up_status = Column(String(50), nullable=True)  # pending, in_progress, completed, not_required
    follow_up_notes = Column(Text, nullable=True)
    followed_up_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    followed_up_at = Column(DateTime, nullable=True)

    # Audit fields
    collected_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="nps_surveys")
    client = relationship("Client", backref="nps_surveys")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    work_order = relationship("WorkOrder", backref="nps_surveys")
    site = relationship("Site", backref="nps_surveys")
    collector = relationship("User", foreign_keys=[collected_by], backref="collected_nps_surveys")
    follow_up_user = relationship("User", foreign_keys=[followed_up_by], backref="followed_up_nps_surveys")


# ============================================================================
# Petty Cash Models
# ============================================================================

class PettyCashFund(Base):
    """
    Petty Cash Fund - Allocated fund for each technician.
    Tracks fund limit, current balance, and replenishment history.
    Each technician can have one active petty cash fund.
    """
    __tablename__ = "petty_cash_funds"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy

    # Address Book employee (replaces technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Fund details
    fund_limit = Column(Numeric(12, 2), nullable=False, default=500.00)  # Maximum allocated amount
    current_balance = Column(Numeric(12, 2), nullable=False, default=0)  # Current available balance
    currency = Column(String(3), default="USD")

    # Status
    status = Column(String(20), default="active")  # active, suspended, closed

    # Thresholds for approval workflow
    auto_approve_threshold = Column(Numeric(12, 2), default=50.00)  # Transactions below this are auto-approved

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="petty_cash_funds")
    technician = relationship("Technician", backref=backref("petty_cash_fund", uselist=False))  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    creator = relationship("User", foreign_keys=[created_by], backref="created_petty_cash_funds")
    transactions = relationship("PettyCashTransaction", back_populates="fund", cascade="all, delete-orphan")
    replenishments = relationship("PettyCashReplenishment", back_populates="fund", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('technician_id', name='uq_technician_petty_cash_fund'),
    )


class PettyCashTransaction(Base):
    """
    Petty Cash Transaction - Individual expense entry.
    Tracks expense details, receipt images, and approval status.
    """
    __tablename__ = "petty_cash_transactions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fund_id = Column(Integer, ForeignKey("petty_cash_funds.id"), nullable=False)

    # Transaction identification
    transaction_number = Column(String(50), nullable=False, index=True)  # Auto-generated: PCT-YYYYMMDD-XXX
    transaction_date = Column(DateTime, nullable=False, default=func.now())

    # Expense details
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD")
    description = Column(String(500), nullable=False)
    category = Column(String(50), nullable=True)  # supplies, tools, transport, meals, materials, services, other
    merchant_name = Column(String(200), nullable=True)

    # Optional linking to work order/contract for cost tracking
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)

    # Vendor linking (Address Book) - for tracking which vendor the expense was made to
    vendor_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Invoice linking - for associating petty cash expense with a processed invoice
    invoice_id = Column(Integer, ForeignKey("processed_images.id"), nullable=True)

    # Approval workflow
    status = Column(String(20), default="pending")  # pending, approved, rejected, reversed
    auto_approved = Column(Boolean, default=False)  # True if below threshold

    # Approval details
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Reversal details
    reversed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reversed_at = Column(DateTime, nullable=True)
    reversal_reason = Column(Text, nullable=True)
    reversal_journal_entry_id = Column(Integer, nullable=True)  # ID of the reversing journal entry

    # Notes
    notes = Column(Text, nullable=True)

    # Balance tracking
    balance_before = Column(Numeric(12, 2), nullable=True)
    balance_after = Column(Numeric(12, 2), nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)  # Technician who created
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="petty_cash_transactions")
    fund = relationship("PettyCashFund", back_populates="transactions")
    work_order = relationship("WorkOrder", backref="petty_cash_transactions")
    contract = relationship("Contract", backref="petty_cash_transactions")
    vendor = relationship("AddressBook", foreign_keys=[vendor_address_book_id], backref="petty_cash_transactions")
    invoice = relationship("ProcessedImage", backref="petty_cash_transactions")
    approver = relationship("User", foreign_keys=[approved_by], backref="approved_petty_cash_transactions")
    creator = relationship("User", foreign_keys=[created_by], backref="created_petty_cash_transactions")
    reverser = relationship("User", foreign_keys=[reversed_by], backref="reversed_petty_cash_transactions")
    receipts = relationship("PettyCashReceipt", back_populates="transaction", cascade="all, delete-orphan")


class PettyCashReceipt(Base):
    """
    Receipt images attached to petty cash transactions.
    """
    __tablename__ = "petty_cash_receipts"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("petty_cash_transactions.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # File info
    filename = Column(String, nullable=False)  # Stored filename (UUID-based)
    original_filename = Column(String, nullable=False)  # Original uploaded filename
    file_path = Column(String, nullable=False)  # Full path or S3 key
    file_size = Column(Integer, nullable=True)  # File size in bytes
    mime_type = Column(String, nullable=True)  # MIME type (image/jpeg, etc.)

    # Metadata
    caption = Column(String(500), nullable=True)

    # Audit
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=func.now())

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    transaction = relationship("PettyCashTransaction", back_populates="receipts")
    company = relationship("Company", backref="petty_cash_receipts")
    uploader = relationship("User", foreign_keys=[uploaded_by], backref="uploaded_petty_cash_receipts")


class PettyCashReplenishment(Base):
    """
    Petty Cash Replenishment - Records when funds are replenished.
    """
    __tablename__ = "petty_cash_replenishments"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fund_id = Column(Integer, ForeignKey("petty_cash_funds.id"), nullable=False)

    # Replenishment details
    replenishment_number = Column(String(50), nullable=False, index=True)  # Auto-generated: PCR-YYYYMMDD-XXX
    replenishment_date = Column(DateTime, nullable=False, default=func.now())
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD")

    # Method (for reconciliation)
    method = Column(String(50), nullable=True)  # cash, transfer, check
    reference_number = Column(String(100), nullable=True)  # Check number, transfer reference

    # Balance tracking
    balance_before = Column(Numeric(12, 2), nullable=True)
    balance_after = Column(Numeric(12, 2), nullable=True)

    # Notes
    notes = Column(Text, nullable=True)

    # Audit
    processed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    company = relationship("Company", backref="petty_cash_replenishments")
    fund = relationship("PettyCashFund", back_populates="replenishments")
    processor = relationship("User", foreign_keys=[processed_by], backref="processed_petty_cash_replenishments")


# ============================================================================
# Invoice Allocation Models
# ============================================================================

class InvoiceAllocation(Base):
    """
    Invoice Allocation - Links subcontractor invoices to contracts, sites, or projects with cost distribution settings.
    Allows spreading invoice costs over duration (monthly, quarterly, etc.)
    """
    __tablename__ = "invoice_allocations"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("processed_images.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Allocation target - exactly one must be set
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    allocation_type = Column(String(20), default="contract")  # contract, site, project

    # Allocation settings
    total_amount = Column(Numeric(14, 2), nullable=False)  # Total invoice amount to allocate
    distribution_type = Column(String(20), nullable=False, default="one_time")  # one_time, monthly, quarterly, custom

    # For distributed allocations
    start_date = Column(Date, nullable=True)  # Start of distribution period
    end_date = Column(Date, nullable=True)    # End of distribution period
    number_of_periods = Column(Integer, default=1)  # Number of periods to distribute over

    # Status and audit
    status = Column(String(20), default="active")  # active, cancelled, completed
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    # passive_deletes=True tells SQLAlchemy to let the DB handle cascade deletion
    # instead of trying to set invoice_id to NULL (which violates NOT NULL constraint)
    invoice = relationship("ProcessedImage", backref=backref("allocation", passive_deletes=True))
    contract = relationship("Contract", backref="allocations")
    site = relationship("Site", backref="allocations")
    project = relationship("Project", backref="allocations")
    creator = relationship("User", foreign_keys=[created_by], backref="created_allocations")
    periods = relationship("AllocationPeriod", back_populates="allocation", cascade="all, delete-orphan")


class AllocationPeriod(Base):
    """
    Allocation Period - Individual period amounts for distributed invoice costs.
    Each period represents a portion of the total invoice amount allocated to a specific time period.
    """
    __tablename__ = "allocation_periods"

    id = Column(Integer, primary_key=True, index=True)
    allocation_id = Column(Integer, ForeignKey("invoice_allocations.id", ondelete="CASCADE"), nullable=False)

    # Period details
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    period_number = Column(Integer, nullable=False)  # 1, 2, 3, etc.

    # Amount for this period
    amount = Column(Numeric(14, 2), nullable=False)

    # Recognition status
    is_recognized = Column(Boolean, default=False)  # Whether this period's cost has been recognized
    recognized_at = Column(DateTime, nullable=True)

    # Recognition tracking (for audit trail)
    recognition_number = Column(String(20), nullable=True, index=True)  # Auto-generated: REC-2025-0001
    recognition_reference = Column(String(100), nullable=True)  # External ref (payment voucher, check #)
    recognition_notes = Column(Text, nullable=True)  # Comments/reason
    recognized_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=func.now())

    # Relationships
    allocation = relationship("InvoiceAllocation", back_populates="periods")
    recognized_by_user = relationship("User", foreign_keys=[recognized_by])


class RecognitionLog(Base):
    """
    Recognition Log - Audit trail for all recognition actions.
    Tracks when periods are recognized, unrecognized, or modified.
    """
    __tablename__ = "recognition_log"

    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("allocation_periods.id", ondelete="CASCADE"), nullable=False)

    action = Column(String(20), nullable=False)  # 'recognized', 'unrecognized', 'modified'
    recognition_number = Column(String(20), nullable=True)
    previous_status = Column(Boolean, nullable=True)
    new_status = Column(Boolean, nullable=True)
    reference = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    period = relationship("AllocationPeriod")
    user = relationship("User")


# ============================================================================
# Accounting Ledger Models
# ============================================================================

class AccountType(Base):
    """
    Account Type - Classification of accounts (Asset, Liability, Equity, Revenue, Expense)
    """
    __tablename__ = "account_types"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    code = Column(String(10), nullable=False)  # ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
    name = Column(String(100), nullable=False)
    normal_balance = Column(String(10), nullable=False)  # debit or credit
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    # Unique constraint per company
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_account_type_company_code'),
    )

    # Relationships
    company = relationship("Company", backref="account_types")
    accounts = relationship("Account", back_populates="account_type")


class Account(Base):
    """
    Chart of Accounts - Hierarchical account structure for double-entry bookkeeping.
    Accounts can be site-specific for cost center tracking.
    """
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Account identification
    code = Column(String(20), nullable=False, index=True)  # e.g., "5110", "1100"
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Classification
    account_type_id = Column(Integer, ForeignKey("account_types.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # For hierarchy

    # Behavior
    is_site_specific = Column(Boolean, default=False)  # If true, tracks by site as cost center
    is_header = Column(Boolean, default=False)  # Header accounts can't have transactions
    is_bank_account = Column(Boolean, default=False)  # Cash/bank accounts
    is_control_account = Column(Boolean, default=False)  # Sub-ledger control (AP, AR)

    # Status
    is_active = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)  # System accounts can't be deleted

    # Audit
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Unique constraint per company
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_account_company_code'),
    )

    # Relationships
    company = relationship("Company", backref="accounts")
    account_type = relationship("AccountType", back_populates="accounts")
    parent = relationship("Account", remote_side=[id], backref="children")
    creator = relationship("User", foreign_keys=[created_by])
    journal_lines = relationship("JournalEntryLine", back_populates="account")


class FiscalPeriod(Base):
    """
    Fiscal Period - Defines accounting periods (months) within a fiscal year.
    Used for period-end closing and financial reporting.
    """
    __tablename__ = "fiscal_periods"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Period identification
    fiscal_year = Column(Integer, nullable=False)  # e.g., 2025
    period_number = Column(Integer, nullable=False)  # 1-12 for months, 13 for adjustments
    period_name = Column(String(50), nullable=False)  # e.g., "January 2025"

    # Date range
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    # Status
    status = Column(String(20), default="open")  # open, closed, locked
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Audit
    created_at = Column(DateTime, default=func.now())

    # Unique constraint
    __table_args__ = (
        UniqueConstraint('company_id', 'fiscal_year', 'period_number', name='uq_fiscal_period'),
    )

    # Relationships
    company = relationship("Company", backref="fiscal_periods")
    closer = relationship("User", foreign_keys=[closed_by])
    journal_entries = relationship("JournalEntry", back_populates="fiscal_period")


class JournalEntry(Base):
    """
    Journal Entry - Header for accounting transactions.
    Each entry contains multiple lines that must balance (debits = credits).
    """
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Entry identification
    entry_number = Column(String(30), nullable=False, index=True)  # JE-2025-000001
    entry_date = Column(Date, nullable=False, index=True)
    fiscal_period_id = Column(Integer, ForeignKey("fiscal_periods.id"), nullable=True)

    # Description
    description = Column(Text, nullable=False)
    reference = Column(String(100), nullable=True)  # External reference number

    # Source tracking - what generated this entry
    source_type = Column(String(50), nullable=True)  # invoice, work_order, petty_cash, manual, adjustment
    source_id = Column(Integer, nullable=True)  # ID of source document
    source_number = Column(String(50), nullable=True)  # Human-readable source ref

    # Status
    status = Column(String(20), default="draft")  # draft, posted, reversed
    is_auto_generated = Column(Boolean, default=False)  # True if system-generated

    # Totals (denormalized for quick access)
    total_debit = Column(Numeric(14, 2), default=0)
    total_credit = Column(Numeric(14, 2), default=0)

    # Reversal tracking
    is_reversal = Column(Boolean, default=False)
    reversal_of_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    reversed_by_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)

    # Audit
    posted_at = Column(DateTime, nullable=True)
    posted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Unique constraint per company
    __table_args__ = (
        UniqueConstraint('company_id', 'entry_number', name='uq_journal_entry_number'),
    )

    # Relationships
    company = relationship("Company", backref="journal_entries")
    fiscal_period = relationship("FiscalPeriod", back_populates="journal_entries")
    lines = relationship("JournalEntryLine", back_populates="journal_entry", cascade="all, delete-orphan")
    poster = relationship("User", foreign_keys=[posted_by])
    creator = relationship("User", foreign_keys=[created_by])
    reversal_of = relationship("JournalEntry", foreign_keys=[reversal_of_id], remote_side=[id], backref="reversed_by_entry")


class JournalEntryLine(Base):
    """
    Journal Entry Line - Individual debit/credit line within a journal entry.
    Site is the primary cost center for tracking expenses by location.
    """
    __tablename__ = "journal_entry_lines"

    id = Column(Integer, primary_key=True, index=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False)

    # Account and amounts
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    debit = Column(Numeric(14, 2), default=0)
    credit = Column(Numeric(14, 2), default=0)

    # Line description
    description = Column(Text, nullable=True)

    # Cost center - Business Unit is the primary dimension (JDE concept)
    business_unit_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)

    # Legacy site_id - kept for backward compatibility during migration
    # TODO: Deprecate after full migration to business_unit_id
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    # Additional dimensions for drill-down reporting
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)

    # Vendor - Address Book (search_type='V')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)

    # Line ordering
    line_number = Column(Integer, default=1)

    # Audit
    created_at = Column(DateTime, default=func.now())

    # Relationships
    journal_entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("Account", back_populates="journal_lines")
    business_unit = relationship("BusinessUnit", backref="journal_lines")
    site = relationship("Site", backref="journal_lines")
    contract = relationship("Contract", backref="journal_lines")
    work_order = relationship("WorkOrder", backref="journal_lines")
    address_book = relationship("AddressBook", backref="journal_lines")
    project = relationship("Project", backref="journal_lines")
    technician = relationship("Technician", backref="journal_lines")


class AccountBalance(Base):
    """
    Account Balance - Pre-computed balances by account, site, and period for fast reporting.
    Updated when journal entries are posted.
    """
    __tablename__ = "account_balances"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    fiscal_period_id = Column(Integer, ForeignKey("fiscal_periods.id"), nullable=False)

    # Cost center - Business Unit is the primary dimension (JDE concept)
    business_unit_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)

    # Legacy site_id - kept for backward compatibility during migration
    # TODO: Deprecate after full migration to business_unit_id
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    # Period activity
    period_debit = Column(Numeric(14, 2), default=0)
    period_credit = Column(Numeric(14, 2), default=0)

    # Running balance
    opening_balance = Column(Numeric(14, 2), default=0)
    closing_balance = Column(Numeric(14, 2), default=0)

    # Audit
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Unique constraint - now includes business_unit_id
    __table_args__ = (
        UniqueConstraint('company_id', 'account_id', 'fiscal_period_id', 'business_unit_id', 'site_id',
                        name='uq_account_balance_period_bu'),
    )

    # Relationships
    company = relationship("Company", backref="account_balances")
    account = relationship("Account", backref="balances")
    fiscal_period = relationship("FiscalPeriod", backref="account_balances")
    site = relationship("Site", backref="account_balances")
    business_unit = relationship("BusinessUnit", backref="account_balances")


class BusinessUnit(Base):
    """
    Business Unit - The smallest accounting unit in the ERP system.
    Inspired by Oracle JD Edwards, this represents the "where" portion of an account.

    Key concepts:
    - Each BU belongs to exactly one company
    - Supports hierarchy via parent_id (up to 9 levels)
    - Two types: balance_sheet (assets/liabilities/equity) and profit_loss (revenue/expenses)
    - All accounting entries reference a BU for proper cost center tracking
    - Warehouses are linked to BUs for inventory-accounting integration
    """
    __tablename__ = "business_units"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # JD Edwards style identifier (12-char alphanumeric)
    code = Column(String(12), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Hierarchy support
    parent_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)
    level_of_detail = Column(Integer, default=1)  # 1-9 for hierarchy depth

    # Type classification
    bu_type = Column(String(20), default="profit_loss")  # balance_sheet, profit_loss

    # Model/Consolidated flag (JDE concept)
    # "" = Normal BU
    # "M" = Model BU (template)
    # "C" = Consolidated BU (roll-up)
    # "1" = Target BU
    model_flag = Column(String(1), default="")

    # Posting control
    # "" = Normal posting allowed
    # "K" = Budget locked
    # "N" = No posting allowed
    # "P" = Purge (marked for deletion)
    posting_edit = Column(String(1), default="")
    is_adjustment_only = Column(Boolean, default=False)

    # Status
    is_active = Column(Boolean, default=True)

    # Subsequent BU (for closed/redirected BUs)
    subsequent_bu_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)

    # Address/Location info (optional)
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(50), nullable=True)
    country = Column(String(50), nullable=True)

    # Category codes (JDE has 30, we support 10 for flexibility)
    category_code_01 = Column(String(10), nullable=True)  # Primary classification
    category_code_02 = Column(String(10), nullable=True)  # Secondary classification
    category_code_03 = Column(String(10), nullable=True)
    category_code_04 = Column(String(10), nullable=True)
    category_code_05 = Column(String(10), nullable=True)
    category_code_06 = Column(String(10), nullable=True)
    category_code_07 = Column(String(10), nullable=True)
    category_code_08 = Column(String(10), nullable=True)
    category_code_09 = Column(String(10), nullable=True)
    category_code_10 = Column(String(10), nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Unique constraint: code must be unique within company
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_business_unit_code'),
    )

    # Relationships
    company = relationship("Company", backref="business_units")
    parent = relationship("BusinessUnit", foreign_keys=[parent_id], remote_side=[id], backref="children")
    subsequent_bu = relationship("BusinessUnit", foreign_keys=[subsequent_bu_id], remote_side=[id])
    creator = relationship("User", foreign_keys=[created_by])


class DefaultAccountMapping(Base):
    """
    Default Account Mapping - Maps transaction types to default accounts.
    Used for auto-posting journal entries from source documents.
    """
    __tablename__ = "default_account_mappings"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Mapping identification
    transaction_type = Column(String(50), nullable=False)  # invoice_expense, invoice_payable, wo_labor, wo_parts, etc.
    category = Column(String(50), nullable=True)  # Sub-category (e.g., invoice_category: service, spare_parts)

    # Default accounts
    debit_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    credit_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    # Settings
    is_active = Column(Boolean, default=True)
    description = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Unique constraint
    __table_args__ = (
        UniqueConstraint('company_id', 'transaction_type', 'category',
                        name='uq_default_account_mapping'),
    )

    # Relationships
    company = relationship("Company", backref="account_mappings")
    debit_account = relationship("Account", foreign_keys=[debit_account_id])
    credit_account = relationship("Account", foreign_keys=[credit_account_id])


class ExchangeRate(Base):
    """
    Exchange Rate - Stores current exchange rates per company.
    Rates can be fetched from API or set manually.
    """
    __tablename__ = "exchange_rates"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    from_currency = Column(String(3), nullable=False)  # ISO 4217 currency code (e.g., USD)
    to_currency = Column(String(3), nullable=False)    # ISO 4217 currency code (e.g., LBP)
    rate = Column(Numeric(18, 8), nullable=False)      # Exchange rate (1 from_currency = rate to_currency)
    source = Column(String(20), default='api')         # 'api' or 'manual'
    effective_date = Column(Date, default=func.current_date())

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Unique constraint: one active rate per currency pair per company
    __table_args__ = (
        UniqueConstraint('company_id', 'from_currency', 'to_currency',
                        name='uq_exchange_rate_pair'),
    )

    # Relationships
    company = relationship("Company", backref="exchange_rates")


class ExchangeRateLog(Base):
    """
    Exchange Rate Log - Historical log of all exchange rate fetches and changes.
    Used for auditing and tracking rate history.
    """
    __tablename__ = "exchange_rate_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    from_currency = Column(String(3), nullable=False)
    to_currency = Column(String(3), nullable=False)
    rate = Column(Numeric(18, 8), nullable=False)
    source = Column(String(20), nullable=False)  # 'api', 'manual', 'api_fallback'
    fetched_at = Column(DateTime, default=func.now())

    # Optional: store API response details
    api_provider = Column(String(50), nullable=True)  # e.g., 'exchangerate-api.com'
    raw_response = Column(Text, nullable=True)        # JSON response for debugging

    # Relationships
    company = relationship("Company", backref="exchange_rate_logs")


# ============================================================================
# Purchase Request & Purchase Order Models (Procurement Workflow)
# ============================================================================

class PurchaseRequest(Base):
    """
    Purchase Request - Request for purchasing items/services.
    Workflow: draft → submitted → approved → rejected → ordered → cancelled
    """
    __tablename__ = "purchase_requests"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    pr_number = Column(String(50), unique=True, index=True)  # PR-2025-00001

    # Status workflow
    status = Column(String(20), default='draft')  # draft, submitted, approved, rejected, ordered, cancelled

    # Source linkage (optional)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)

    # Vendor - Address Book (search_type='V')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Details
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    required_date = Column(Date, nullable=True)  # When items are needed
    priority = Column(String(20), default='normal')  # low, normal, high, urgent

    # Totals (calculated from line items)
    estimated_total = Column(Numeric(12, 2), default=0)
    currency = Column(String(3), default='USD')

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Submission
    submitted_at = Column(DateTime, nullable=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Approval
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejected_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    notes = Column(Text, nullable=True)

    # Relationships
    company = relationship("Company", backref="purchase_requests")
    work_order = relationship("WorkOrder", backref="purchase_requests")
    contract = relationship("Contract", backref="purchase_requests")
    address_book = relationship("AddressBook", backref="purchase_requests")
    creator = relationship("User", foreign_keys=[created_by], backref="created_purchase_requests")
    submitter = relationship("User", foreign_keys=[submitted_by])
    approver = relationship("User", foreign_keys=[approved_by])
    rejector = relationship("User", foreign_keys=[rejected_by])
    lines = relationship("PurchaseRequestLine", back_populates="purchase_request", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="purchase_request")


class PurchaseRequestLine(Base):
    """
    Purchase Request Line Item - Individual items requested in a PR.
    """
    __tablename__ = "purchase_request_lines"

    id = Column(Integer, primary_key=True, index=True)
    purchase_request_id = Column(Integer, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False)

    # Item reference (optional - can be free text)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=True)

    # Item details
    item_number = Column(String(100), nullable=True)  # From item master or manual
    description = Column(String(500), nullable=False)

    # Quantities
    quantity_requested = Column(Numeric(10, 2), nullable=False)
    quantity_approved = Column(Numeric(10, 2), nullable=True)  # Set during approval
    unit = Column(String(20), default='EA')

    # Costs
    estimated_unit_cost = Column(Numeric(12, 2), nullable=True)
    estimated_total = Column(Numeric(12, 2), nullable=True)

    notes = Column(Text, nullable=True)

    # Relationships
    purchase_request = relationship("PurchaseRequest", back_populates="lines")
    item = relationship("ItemMaster")


class PurchaseOrder(Base):
    """
    Purchase Order - Order sent to vendor for purchasing items/services.
    Workflow: draft → sent → acknowledged → partial → received → cancelled
    """
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    po_number = Column(String(50), unique=True, index=True)  # PO-2025-00001

    # Link to PR (optional - PO can exist without PR)
    purchase_request_id = Column(Integer, ForeignKey("purchase_requests.id"), nullable=True)

    # Status: draft → sent → acknowledged → partial → received → cancelled
    status = Column(String(20), default='draft')

    # Vendor - Address Book (search_type='V') - required for PO
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Source linkage (inherited from PR or set directly)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)

    # Dates
    order_date = Column(Date, nullable=True)
    expected_date = Column(Date, nullable=True)

    # Totals
    subtotal = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    total_amount = Column(Numeric(12, 2), default=0)
    currency = Column(String(3), default='USD')

    # Terms
    payment_terms = Column(String(100), nullable=True)  # Net 30, etc.
    shipping_address = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    notes = Column(Text, nullable=True)

    # Relationships
    company = relationship("Company", backref="purchase_orders")
    purchase_request = relationship("PurchaseRequest", back_populates="purchase_orders")
    address_book = relationship("AddressBook", backref="purchase_orders")
    work_order = relationship("WorkOrder", backref="purchase_orders")
    contract = relationship("Contract", backref="purchase_orders")
    creator = relationship("User", foreign_keys=[created_by], backref="created_purchase_orders")
    lines = relationship("PurchaseOrderLine", back_populates="purchase_order", cascade="all, delete-orphan")
    linked_invoices = relationship("PurchaseOrderInvoice", back_populates="purchase_order", cascade="all, delete-orphan")
    goods_receipts = relationship("GoodsReceipt", back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderLine(Base):
    """
    Purchase Order Line Item - Individual items ordered in a PO.
    """
    __tablename__ = "purchase_order_lines"

    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)

    # Link to PR line (if converted from PR)
    pr_line_id = Column(Integer, ForeignKey("purchase_request_lines.id"), nullable=True)

    # Item reference
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=True)
    item_number = Column(String(100), nullable=True)
    description = Column(String(500), nullable=False)

    # Quantities
    quantity_ordered = Column(Numeric(10, 2), nullable=False)
    quantity_received = Column(Numeric(10, 2), default=0)
    unit = Column(String(20), default='EA')

    # Pricing
    unit_price = Column(Numeric(12, 2), nullable=False)
    total_price = Column(Numeric(12, 2), nullable=False)

    # Status: pending → partial → received → cancelled
    receive_status = Column(String(20), default='pending')

    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="lines")
    pr_line = relationship("PurchaseRequestLine")
    item = relationship("ItemMaster")


class PurchaseOrderInvoice(Base):
    """
    Purchase Order Invoice Link - Links invoices to purchase orders for 3-way matching.
    """
    __tablename__ = "purchase_order_invoices"

    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("processed_images.id"), nullable=False)

    linked_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    linked_at = Column(DateTime, default=func.now())
    notes = Column(Text, nullable=True)

    # Unique constraint: one link per PO-Invoice pair
    __table_args__ = (
        UniqueConstraint('purchase_order_id', 'invoice_id', name='uq_po_invoice_link'),
    )

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="linked_invoices")
    invoice = relationship("ProcessedImage")
    linker = relationship("User", foreign_keys=[linked_by])


class GoodsReceipt(Base):
    """
    Goods Receipt Note (GRN) - Document for receiving goods against a PO.
    Supports partial receiving, multiple receipts per PO, and quality inspection.
    """
    __tablename__ = "goods_receipts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    grn_number = Column(String(50), unique=True, nullable=False)  # GRN-YYYY-NNNNN

    # Link to Purchase Order
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)

    # Receiving details
    receipt_date = Column(Date, nullable=False)  # Actual date goods were received
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)

    # Supplier delivery info
    supplier_delivery_note = Column(String(100), nullable=True)  # Supplier's DN number
    carrier = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)

    # Status workflow: draft → pending_inspection → accepted → rejected → cancelled
    status = Column(String(20), default='draft')

    # Quality inspection
    inspection_required = Column(Boolean, default=False)
    inspection_status = Column(String(20), nullable=True)  # pending, passed, failed, partial
    inspected_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    inspected_at = Column(DateTime, nullable=True)
    inspection_notes = Column(Text, nullable=True)

    # Financial tracking
    currency = Column(String(3), default='USD')
    exchange_rate = Column(Numeric(18, 6), default=1.0)
    subtotal = Column(Numeric(18, 2), default=0)
    tax_amount = Column(Numeric(18, 2), default=0)
    total_amount = Column(Numeric(18, 2), default=0)

    # Landed cost tracking for imports
    is_import = Column(Boolean, default=False)  # Flag for import receipts
    total_extra_costs = Column(Numeric(18, 2), default=0)  # Sum of all extra costs
    total_landed_cost = Column(Numeric(18, 2), default=0)  # total_amount + total_extra_costs

    # Journal entry reference
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    reversal_journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)

    notes = Column(Text, nullable=True)

    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    posted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)

    # Relationships
    company = relationship("Company")
    purchase_order = relationship("PurchaseOrder", back_populates="goods_receipts")
    warehouse = relationship("Warehouse")
    lines = relationship("GoodsReceiptLine", back_populates="goods_receipt", cascade="all, delete-orphan")
    extra_costs = relationship("GoodsReceiptExtraCost", back_populates="goods_receipt", cascade="all, delete-orphan")
    journal_entry = relationship("JournalEntry", foreign_keys=[journal_entry_id])
    reversal_journal_entry = relationship("JournalEntry", foreign_keys=[reversal_journal_entry_id])
    creator = relationship("User", foreign_keys=[created_by])
    inspector = relationship("User", foreign_keys=[inspected_by])
    poster = relationship("User", foreign_keys=[posted_by])


class GoodsReceiptLine(Base):
    """
    Goods Receipt Line - Individual line items being received.
    Links to PO line and tracks quantity, location, lot/serial, and inspection.
    """
    __tablename__ = "goods_receipt_lines"

    id = Column(Integer, primary_key=True, index=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False)
    po_line_id = Column(Integer, ForeignKey("purchase_order_lines.id"), nullable=False)

    # Item details (denormalized for history)
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=True)
    item_code = Column(String(50), nullable=True)
    item_description = Column(String(500), nullable=True)

    # Quantities
    quantity_ordered = Column(Numeric(18, 4), nullable=False)  # From PO line
    quantity_received = Column(Numeric(18, 4), nullable=False)  # Quantity in this receipt
    quantity_accepted = Column(Numeric(18, 4), default=0)  # After inspection
    quantity_rejected = Column(Numeric(18, 4), default=0)  # Failed inspection

    unit = Column(String(20), default='EA')

    # Location - can differ from header warehouse for multi-location receiving
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    bin_location = Column(String(50), nullable=True)  # Specific bin/shelf location

    # Lot/Serial tracking
    lot_number = Column(String(100), nullable=True)  # Supplier batch/lot
    serial_numbers = Column(Text, nullable=True)  # JSON array for serialized items
    expiry_date = Column(Date, nullable=True)
    manufacture_date = Column(Date, nullable=True)

    # Pricing (from PO, may be updated)
    unit_price = Column(Numeric(18, 4), nullable=False)
    total_price = Column(Numeric(18, 2), nullable=False)

    # Landed cost fields (for imports with extra costs)
    allocated_extra_cost = Column(Numeric(18, 2), default=0)  # Proportionally allocated extra costs
    landed_unit_cost = Column(Numeric(18, 4), nullable=True)  # unit_price + (allocated_extra_cost / quantity)
    landed_total_cost = Column(Numeric(18, 2), nullable=True)  # Total including extra costs

    # Inspection details
    inspection_status = Column(String(20), default='pending')  # pending, passed, failed
    rejection_reason = Column(String(200), nullable=True)
    inspection_notes = Column(Text, nullable=True)

    # Variance tracking
    has_variance = Column(Boolean, default=False)
    variance_type = Column(String(20), nullable=True)  # over, under, damaged, wrong_item
    variance_notes = Column(Text, nullable=True)

    # ItemLedger reference for audit
    item_ledger_id = Column(Integer, ForeignKey("item_ledger.id"), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    goods_receipt = relationship("GoodsReceipt", back_populates="lines")
    po_line = relationship("PurchaseOrderLine")
    item = relationship("ItemMaster")
    warehouse = relationship("Warehouse")
    item_ledger = relationship("ItemLedger")


class GoodsReceiptExtraCost(Base):
    """
    Extra costs for imported goods (freight, duties, port charges, etc.)
    These costs are allocated proportionally to GRN lines based on line value.
    """
    __tablename__ = "goods_receipt_extra_costs"

    id = Column(Integer, primary_key=True, index=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False)

    # Cost details
    cost_type = Column(String(50), nullable=False)  # freight, duty, port_handling, customs, insurance, other
    cost_description = Column(String(255), nullable=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default='USD')

    # Vendor who charged this cost (freight company, customs broker, etc.) - Address Book (search_type='V')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Reference documents
    reference_number = Column(String(100), nullable=True)  # Bill of lading, customs doc, invoice number

    notes = Column(Text, nullable=True)

    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    goods_receipt = relationship("GoodsReceipt", back_populates="extra_costs")
    address_book = relationship("AddressBook", backref="goods_receipt_extra_costs")
    creator = relationship("User", foreign_keys=[created_by])


# =============================================================================
# CRM MODELS
# =============================================================================

class LeadSource(Base):
    """
    Lead Source - Where leads come from (Website, Referral, Cold Call, etc.)
    """
    __tablename__ = "lead_sources"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    company = relationship("Company")
    leads = relationship("Lead", back_populates="source")


class PipelineStage(Base):
    """
    Pipeline Stage - Stages in the sales pipeline (New, Qualified, Proposal, Negotiation, Won, Lost)
    """
    __tablename__ = "pipeline_stages"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False)
    code = Column(String(20), nullable=True)
    color = Column(String(20), default="#6366f1")  # Hex color for UI
    probability = Column(Integer, default=0)  # Win probability percentage (0-100)
    is_won = Column(Boolean, default=False)  # Is this a "won" stage
    is_lost = Column(Boolean, default=False)  # Is this a "lost" stage
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    company = relationship("Company")
    opportunities = relationship("Opportunity", back_populates="stage")


class Lead(Base):
    """
    Lead - Potential customer/opportunity before qualification
    """
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Contact information
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    mobile = Column(String(50), nullable=True)
    job_title = Column(String(100), nullable=True)

    # Company information
    company_name = Column(String(255), nullable=True)
    industry = Column(String(100), nullable=True)
    website = Column(String(255), nullable=True)
    employee_count = Column(String(50), nullable=True)  # "1-10", "11-50", etc.

    # Address
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)

    # Lead details
    source_id = Column(Integer, ForeignKey("lead_sources.id"), nullable=True)
    status = Column(String(20), default="new")  # new, contacted, qualified, unqualified, converted
    rating = Column(String(10), nullable=True)  # hot, warm, cold

    # Value estimation
    estimated_value = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), default="USD")

    # Assignment
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Notes and description
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # Conversion tracking
    converted_to_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    converted_to_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)
    converted_to_opportunity_id = Column(Integer, nullable=True)  # Will reference opportunities.id
    converted_at = Column(DateTime, nullable=True)
    converted_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    source = relationship("LeadSource", back_populates="leads")
    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])
    converter = relationship("User", foreign_keys=[converted_by])
    converted_client = relationship("Client")
    converted_address_book = relationship("AddressBook", foreign_keys=[converted_to_address_book_id])
    activities = relationship("CRMActivity", back_populates="lead", foreign_keys="CRMActivity.lead_id")


class Opportunity(Base):
    """
    Opportunity - Qualified sales opportunity with pipeline tracking
    """
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Basic info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Related entities
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)  # If converted from lead
    contact_name = Column(String(200), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)

    # Pipeline
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"), nullable=True)
    probability = Column(Integer, default=0)  # Win probability percentage

    # Value
    amount = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(3), default="USD")

    # Dates
    expected_close_date = Column(Date, nullable=True)
    actual_close_date = Column(Date, nullable=True)

    # Status
    status = Column(String(20), default="open")  # open, won, lost
    lost_reason = Column(Text, nullable=True)
    competitor = Column(String(255), nullable=True)  # Who we lost to

    # Assignment
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Notes
    notes = Column(Text, nullable=True)
    next_step = Column(Text, nullable=True)

    # Conversion to contract
    converted_to_contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)
    converted_at = Column(DateTime, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    client = relationship("Client")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    lead = relationship("Lead")
    stage = relationship("PipelineStage", back_populates="opportunities")
    assignee = relationship("User", foreign_keys=[assigned_to])
    creator = relationship("User", foreign_keys=[created_by])
    converted_contract = relationship("Contract")
    activities = relationship("CRMActivity", back_populates="opportunity", foreign_keys="CRMActivity.opportunity_id")


class CRMActivity(Base):
    """
    CRM Activity - Interactions with leads/opportunities (calls, emails, meetings, tasks)
    """
    __tablename__ = "crm_activities"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Activity type
    activity_type = Column(String(20), nullable=False)  # call, email, meeting, task, note
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Related to (one of these should be set)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Scheduling
    due_date = Column(DateTime, nullable=True)
    due_time = Column(Time, nullable=True)
    duration_minutes = Column(Integer, nullable=True)

    # Status
    status = Column(String(20), default="planned")  # planned, completed, cancelled
    priority = Column(String(10), default="normal")  # low, normal, high

    # Outcome (for completed activities)
    outcome = Column(Text, nullable=True)

    # For calls
    call_direction = Column(String(10), nullable=True)  # inbound, outbound
    call_result = Column(String(20), nullable=True)  # answered, no_answer, voicemail, busy

    # For meetings
    location = Column(String(255), nullable=True)
    attendees = Column(Text, nullable=True)  # JSON array of attendee names/emails

    # Assignment
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Reminders
    reminder_date = Column(DateTime, nullable=True)
    reminder_sent = Column(Boolean, default=False)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    lead = relationship("Lead", back_populates="activities", foreign_keys=[lead_id])
    opportunity = relationship("Opportunity", back_populates="activities", foreign_keys=[opportunity_id])
    client = relationship("Client")
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    completer = relationship("User", foreign_keys=[completed_by])
    creator = relationship("User", foreign_keys=[created_by])


class Campaign(Base):
    """
    Marketing Campaign - Track marketing efforts and their results
    """
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Basic info
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)

    # Type and status
    campaign_type = Column(String(50), nullable=True)  # email, social, event, webinar, advertising, etc.
    status = Column(String(20), default="planned")  # planned, active, paused, completed, cancelled

    # Dates
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    # Budget
    budget = Column(Numeric(12, 2), nullable=True)
    actual_cost = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), default="USD")

    # Goals
    expected_revenue = Column(Numeric(14, 2), nullable=True)
    expected_response_rate = Column(Numeric(5, 2), nullable=True)  # Percentage
    target_audience = Column(Text, nullable=True)

    # Results
    sent_count = Column(Integer, default=0)  # Number sent/reached
    response_count = Column(Integer, default=0)  # Responses received
    leads_generated = Column(Integer, default=0)
    opportunities_created = Column(Integer, default=0)
    revenue_generated = Column(Numeric(14, 2), default=0)

    # Owner
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Notes
    notes = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    owner = relationship("User", foreign_keys=[owner_id])
    creator = relationship("User", foreign_keys=[created_by])
    campaign_leads = relationship("CampaignLead", back_populates="campaign")


class CampaignLead(Base):
    """
    Campaign Lead - Links leads to campaigns they originated from
    """
    __tablename__ = "campaign_leads"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(20), default="sent")  # sent, responded, converted
    responded_at = Column(DateTime, nullable=True)
    converted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Unique constraint
    __table_args__ = (
        UniqueConstraint('campaign_id', 'lead_id', name='uq_campaign_lead'),
    )

    # Relationships
    campaign = relationship("Campaign", back_populates="campaign_leads")
    lead = relationship("Lead")


# =============================================================================
# TOOLS MANAGEMENT
# =============================================================================

class ToolCategory(Base):
    """
    Tool Category - Classification of tools as fixed assets or consumables.
    Determines accounting treatment for purchases.
    """
    __tablename__ = "tool_categories"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    name = Column(String(100), nullable=False)  # e.g., "Power Tools", "Hand Tools"
    code = Column(String(20), nullable=True, index=True)  # e.g., "PWR", "HND"

    # Accounting classification
    asset_type = Column(String(20), nullable=False)  # "fixed_asset" or "consumable"

    # Fixed asset settings (only for asset_type = "fixed_asset")
    useful_life_months = Column(Integer, nullable=True)  # e.g., 60 months for 5 years
    depreciation_method = Column(String(30), nullable=True)  # "straight_line", "declining_balance"
    salvage_value_percentage = Column(Numeric(5, 2), nullable=True)  # e.g., 10.00 for 10%

    # Default accounts (can override DefaultAccountMapping)
    asset_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # DR for fixed assets: 1210
    expense_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # DR for consumables: 5250
    accumulated_depreciation_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # CR: 1290
    depreciation_expense_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # DR: 5330

    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_tool_category_code'),
    )

    # Relationships
    company = relationship("Company", backref="tool_categories")
    tools = relationship("Tool", back_populates="category")
    asset_account = relationship("Account", foreign_keys=[asset_account_id])
    expense_account = relationship("Account", foreign_keys=[expense_account_id])
    accumulated_depreciation_account = relationship("Account", foreign_keys=[accumulated_depreciation_account_id])
    depreciation_expense_account = relationship("Account", foreign_keys=[depreciation_expense_account_id])


class ToolPurchase(Base):
    """
    Tool Purchase - Dedicated purchase document for tools.
    Separate from existing PO system.
    """
    __tablename__ = "tool_purchases"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Document identification
    purchase_number = Column(String(30), nullable=False, index=True)  # TP-2025-00001
    purchase_date = Column(Date, nullable=False)

    # Vendor - Address Book (search_type='V')
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Financial
    currency = Column(String(10), default="USD")
    subtotal = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    total_amount = Column(Numeric(12, 2), default=0)

    # Initial allocation (where tools go after purchase)
    initial_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)

    # Status
    status = Column(String(20), default="draft")  # draft, approved, received, cancelled

    # Approval workflow
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    received_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    received_at = Column(DateTime, nullable=True)

    # Reference
    reference = Column(String(100), nullable=True)  # External reference number
    notes = Column(Text, nullable=True)

    # Journal entry tracking
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'purchase_number', name='uq_tool_purchase_number'),
    )

    # Relationships
    company = relationship("Company", backref="tool_purchases")
    address_book = relationship("AddressBook", backref="tool_purchases")
    initial_warehouse = relationship("Warehouse", backref="tool_purchase_receipts")
    approver = relationship("User", foreign_keys=[approved_by])
    receiver = relationship("User", foreign_keys=[received_by])
    creator = relationship("User", foreign_keys=[created_by])
    journal_entry = relationship("JournalEntry", backref="tool_purchase")
    lines = relationship("ToolPurchaseLine", back_populates="purchase", cascade="all, delete-orphan")
    tools = relationship("Tool", back_populates="purchase")


class ToolPurchaseLine(Base):
    """
    Tool Purchase Line - Individual line items on a tool purchase.
    """
    __tablename__ = "tool_purchase_lines"

    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("tool_purchases.id", ondelete="CASCADE"), nullable=False)

    line_number = Column(Integer, nullable=False)
    category_id = Column(Integer, ForeignKey("tool_categories.id"), nullable=False)

    # Item details
    description = Column(String(500), nullable=False)
    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)

    # Quantity and pricing
    quantity = Column(Integer, nullable=False, default=1)
    unit_cost = Column(Numeric(12, 2), nullable=False)
    total_cost = Column(Numeric(12, 2), nullable=False)

    # Individual serial numbers (comma-separated or JSON array for multiple items)
    serial_numbers = Column(Text, nullable=True)

    notes = Column(Text, nullable=True)

    # Relationships
    purchase = relationship("ToolPurchase", back_populates="lines")
    category = relationship("ToolCategory")


class Tool(Base):
    """
    Tool - Individual tool/equipment item.
    Can be assigned to ONE of: Site, Technician, or Warehouse.
    """
    __tablename__ = "tools"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("tool_categories.id"), nullable=False)

    # Identification
    tool_number = Column(String(50), nullable=False, index=True)  # e.g., "TL-2025-00001"
    name = Column(String(200), nullable=False)  # e.g., "DeWalt 20V MAX Drill"
    serial_number = Column(String(100), nullable=True)
    barcode = Column(String(100), nullable=True, index=True)

    # Details
    manufacturer = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    specifications = Column(Text, nullable=True)  # JSON for technical specs
    photo_url = Column(String(500), nullable=True)

    # Purchase info (linked from ToolPurchase, denormalized for quick access)
    purchase_id = Column(Integer, ForeignKey("tool_purchases.id"), nullable=True)
    purchase_date = Column(Date, nullable=True)
    purchase_cost = Column(Numeric(12, 2), nullable=True)
    # Vendor - Address Book (search_type='V')
    vendor_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Fixed asset fields (for asset_type = "fixed_asset")
    capitalization_date = Column(Date, nullable=True)  # Date tool was capitalized
    useful_life_months = Column(Integer, nullable=True)  # Can override category
    salvage_value = Column(Numeric(12, 2), nullable=True)
    accumulated_depreciation = Column(Numeric(12, 2), default=0)
    net_book_value = Column(Numeric(12, 2), nullable=True)
    last_depreciation_date = Column(Date, nullable=True)

    # Warranty
    warranty_expiry = Column(Date, nullable=True)
    warranty_notes = Column(Text, nullable=True)

    # Status
    status = Column(String(30), default="available")  # available, in_use, maintenance, retired, lost
    condition = Column(String(20), default="good")  # excellent, good, fair, poor

    # Single assignment - ONLY ONE of these should be set at a time
    assigned_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    assigned_technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy
    assigned_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    assigned_at = Column(DateTime, nullable=True)

    # Address Book employee assignment (replaces assigned_technician_id)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Disposal fields
    disposal_id = Column(Integer, ForeignKey("disposals.id"), nullable=True)
    disposal_date = Column(Date, nullable=True)
    is_disposed = Column(Boolean, default=False)

    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint('company_id', 'tool_number', name='uq_tool_number'),
    )

    # Relationships
    company = relationship("Company", backref="tools")
    category = relationship("ToolCategory", back_populates="tools")
    purchase = relationship("ToolPurchase", back_populates="tools")
    assigned_site = relationship("Site", backref="assigned_tools")
    assigned_technician = relationship("Technician", backref="assigned_tools")  # Legacy
    address_book = relationship("AddressBook", foreign_keys=[address_book_id])
    vendor_address_book = relationship("AddressBook", foreign_keys=[vendor_address_book_id])
    assigned_warehouse = relationship("Warehouse", backref="stored_tools")
    creator = relationship("User", foreign_keys=[created_by])
    allocation_history = relationship("ToolAllocationHistory", back_populates="tool", cascade="all, delete-orphan")
    disposal = relationship("Disposal", back_populates="disposed_tools", foreign_keys=[disposal_id])


class ToolAllocationHistory(Base):
    """
    Tool Allocation History - Tracks all location changes for a tool.
    No journal entries on transfer per requirements.
    """
    __tablename__ = "tool_allocation_history"

    id = Column(Integer, primary_key=True, index=True)
    tool_id = Column(Integer, ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)

    # Transfer details
    transfer_date = Column(DateTime, nullable=False, default=func.now())

    # From location (one of these or null for initial assignment)
    from_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    from_technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)

    # Address Book employee from (replaces from_technician_id)
    from_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # To location (one of these)
    to_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    to_technician_id = Column(Integer, ForeignKey("technicians.id"), nullable=True)  # Legacy
    to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)

    # Address Book employee to (replaces to_technician_id)
    to_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Transfer reason/notes
    reason = Column(String(100), nullable=True)  # initial_assignment, reassignment, return, maintenance
    notes = Column(Text, nullable=True)

    # Audit
    transferred_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    tool = relationship("Tool", back_populates="allocation_history")
    from_site = relationship("Site", foreign_keys=[from_site_id])
    from_technician = relationship("Technician", foreign_keys=[from_technician_id])  # Legacy
    from_address_book = relationship("AddressBook", foreign_keys=[from_address_book_id])
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_site = relationship("Site", foreign_keys=[to_site_id])
    to_technician = relationship("Technician", foreign_keys=[to_technician_id])  # Legacy
    to_address_book = relationship("AddressBook", foreign_keys=[to_address_book_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    transferred_by_user = relationship("User", foreign_keys=[transferred_by])


# ============================================================================
# DISPOSAL MODELS - Asset & Inventory Write-off/Destruction
# ============================================================================

class Disposal(Base):
    """
    Disposal - Unified disposal document for both tools and inventory items.
    Supports write-off, scrap, sale, donation with proper accounting entries.
    """
    __tablename__ = "disposals"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    disposal_number = Column(String(50), nullable=False, index=True)  # DSP-YYYY-NNNNN
    disposal_date = Column(Date, nullable=False)

    # Disposal details
    reason = Column(String(50), nullable=False)  # damaged, obsolete, lost, stolen, sold, scrapped, donated
    method = Column(String(50), nullable=True)  # scrap, sale, donation, return_to_vendor, destroy

    # Salvage/Sale info
    salvage_received = Column(Numeric(12, 2), default=0)  # Cash received from sale/scrap
    salvage_reference = Column(String(100), nullable=True)  # Check/receipt number

    # Status workflow
    status = Column(String(20), default="draft")  # draft, approved, posted, cancelled

    # Approval tracking
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    posted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)

    # Journal entry reference
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)

    # Audit
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'disposal_number', name='uq_disposal_number'),
    )

    # Relationships
    company = relationship("Company", backref="disposals")
    approver = relationship("User", foreign_keys=[approved_by])
    poster = relationship("User", foreign_keys=[posted_by])
    creator = relationship("User", foreign_keys=[created_by])
    journal_entry = relationship("JournalEntry", backref="disposal")
    tool_lines = relationship("DisposalToolLine", back_populates="disposal", cascade="all, delete-orphan")
    item_lines = relationship("DisposalItemLine", back_populates="disposal", cascade="all, delete-orphan")
    disposed_tools = relationship("Tool", back_populates="disposal", foreign_keys="[Tool.disposal_id]")


class DisposalToolLine(Base):
    """
    DisposalToolLine - Individual tool being disposed.
    Captures snapshot of tool value at disposal time.
    """
    __tablename__ = "disposal_tool_lines"

    id = Column(Integer, primary_key=True, index=True)
    disposal_id = Column(Integer, ForeignKey("disposals.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, nullable=False)

    tool_id = Column(Integer, ForeignKey("tools.id"), nullable=False)

    # Snapshot values at disposal time
    original_cost = Column(Numeric(12, 2), nullable=False)
    accumulated_depreciation = Column(Numeric(12, 2), default=0)
    net_book_value = Column(Numeric(12, 2), nullable=False)  # = original_cost - accumulated_depreciation

    # Disposal values
    salvage_value = Column(Numeric(12, 2), default=0)  # Portion of salvage allocated to this tool
    gain_loss = Column(Numeric(12, 2), default=0)  # = salvage_value - net_book_value

    notes = Column(Text, nullable=True)

    # Relationships
    disposal = relationship("Disposal", back_populates="tool_lines")
    tool = relationship("Tool", backref="disposal_lines")


class DisposalItemLine(Base):
    """
    DisposalItemLine - Inventory item being disposed.
    Captures quantity and cost at disposal time.
    """
    __tablename__ = "disposal_item_lines"

    id = Column(Integer, primary_key=True, index=True)
    disposal_id = Column(Integer, ForeignKey("disposals.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, nullable=False)

    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)  # Where item is being disposed from

    # Quantity and cost
    quantity = Column(Numeric(12, 3), nullable=False)
    unit_cost = Column(Numeric(12, 4), nullable=False)  # Average cost at disposal time
    total_cost = Column(Numeric(12, 2), nullable=False)  # = quantity * unit_cost

    # Disposal values
    salvage_value = Column(Numeric(12, 2), default=0)  # Portion of salvage allocated to this item
    gain_loss = Column(Numeric(12, 2), default=0)  # = salvage_value - total_cost (usually negative)

    notes = Column(Text, nullable=True)

    # Relationships
    disposal = relationship("Disposal", back_populates="item_lines")
    item = relationship("ItemMaster", backref="disposal_lines")
    warehouse = relationship("Warehouse", backref="disposal_item_lines")


class AddressBook(Base):
    """
    Address Book - Master repository for all business entities (Oracle JDE F0101 equivalent).
    Consolidates Vendors, Clients, and Site branches into a unified structure.
    Each entry has exactly one Search Type (not multi-type).

    Search Types:
    - V  = Vendor (supplier)
    - C  = Customer (client)
    - CB = Client Branch (site/location)
    - E  = Employee
    - MT = Maintenance Team
    """
    __tablename__ = "address_book"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Address Number - JDE AN8 equivalent (auto-generated or manual, unique per company)
    address_number = Column(String(20), nullable=False, index=True)

    # Search Type - Single type per entry (V, C, CB, E, MT)
    search_type = Column(String(5), nullable=False, index=True)

    # Names (JDE Alpha Name, Mailing Name)
    alpha_name = Column(String(100), nullable=False, index=True)  # Primary search name
    mailing_name = Column(String(100), nullable=True)  # Name for correspondence

    # Tax/Registration Information
    tax_id = Column(String(50), nullable=True, index=True)  # Tax ID / VAT number
    registration_number = Column(String(50), nullable=True)  # Company registration

    # Address Fields (JDE style - 4 lines)
    address_line_1 = Column(String(200), nullable=True)
    address_line_2 = Column(String(200), nullable=True)
    address_line_3 = Column(String(200), nullable=True)
    address_line_4 = Column(String(200), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(50), nullable=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(String(50), nullable=True)

    # Communication
    phone_primary = Column(String(30), nullable=True)
    phone_secondary = Column(String(30), nullable=True)
    fax = Column(String(30), nullable=True)
    email = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)

    # GPS Coordinates (for sites/branches)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Parent Address Book (for hierarchies: CB -> C, MT -> C, etc.)
    parent_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Business Unit Link - Each AB entry can have its own BU for cost tracking
    business_unit_id = Column(Integer, ForeignKey("business_units.id"), nullable=True)

    # Category Codes (JDE User Defined Codes - 10 fields for flexible classification)
    category_code_01 = Column(String(10), nullable=True)  # Industry/Type
    category_code_02 = Column(String(10), nullable=True)  # Region
    category_code_03 = Column(String(10), nullable=True)  # Credit Status
    category_code_04 = Column(String(10), nullable=True)  # Payment Terms
    category_code_05 = Column(String(10), nullable=True)  # Priority
    category_code_06 = Column(String(10), nullable=True)
    category_code_07 = Column(String(10), nullable=True)
    category_code_08 = Column(String(10), nullable=True)
    category_code_09 = Column(String(10), nullable=True)
    category_code_10 = Column(String(10), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)

    # Notes
    notes = Column(Text, nullable=True)

    # =========================================================================
    # Employee Salary Fields (only applicable for search_type='E')
    # =========================================================================

    # Base Compensation
    salary_type = Column(String(20), nullable=True)  # monthly, hourly, daily
    base_salary = Column(Numeric(12, 2), nullable=True)  # Base salary amount
    salary_currency = Column(String(3), default="USD")
    hourly_rate = Column(Numeric(10, 2), nullable=True)  # Calculated or manual hourly rate
    overtime_rate_multiplier = Column(Numeric(4, 2), default=1.5)  # e.g., 1.5x for overtime
    working_hours_per_day = Column(Numeric(4, 2), default=8.0)
    working_days_per_month = Column(Integer, default=22)

    # Allowances
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

    # Employee-specific fields
    employee_id = Column(String(50), nullable=True)  # Internal employee ID
    specialization = Column(String(100), nullable=True)  # e.g., "HVAC", "Electrical", "Plumbing"
    hire_date = Column(Date, nullable=True)
    termination_date = Column(Date, nullable=True)

    # Audit Fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Legacy IDs for migration/backward compatibility
    legacy_vendor_id = Column(Integer, nullable=True)
    legacy_client_id = Column(Integer, nullable=True)
    legacy_site_id = Column(Integer, nullable=True)
    legacy_technician_id = Column(Integer, nullable=True)

    # Unique constraint: address_number must be unique within company
    __table_args__ = (
        UniqueConstraint('company_id', 'address_number', name='uq_address_book_number'),
    )

    # Relationships
    company = relationship("Company", backref="address_book_entries")
    parent = relationship("AddressBook", foreign_keys=[parent_address_book_id],
                         remote_side=[id], backref="children")
    business_unit = relationship("BusinessUnit", backref="address_book_entry")
    contacts = relationship("AddressBookContact", back_populates="address_book",
                           cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class AddressBookContact(Base):
    """
    Address Book Contacts - Who's Who (Oracle JDE F0111 equivalent).
    Multiple contacts per Address Book entry with different roles/types.
    """
    __tablename__ = "address_book_contacts"

    id = Column(Integer, primary_key=True, index=True)
    address_book_id = Column(Integer, ForeignKey("address_book.id", ondelete="CASCADE"),
                            nullable=False)

    # Contact identification
    line_number = Column(Integer, nullable=False)  # Line ID within parent

    # Contact Details
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    full_name = Column(String(100), nullable=False)  # Display name
    title = Column(String(100), nullable=True)  # Job title

    # Contact Type/Role
    # primary, billing, shipping, technical, management, emergency, other
    contact_type = Column(String(20), nullable=False, default="primary")

    # Communication
    phone_primary = Column(String(30), nullable=True)
    phone_mobile = Column(String(30), nullable=True)
    phone_fax = Column(String(30), nullable=True)
    email = Column(String(255), nullable=True)

    # Preferences
    preferred_contact_method = Column(String(20), nullable=True)  # phone, email, mail
    language = Column(String(10), nullable=True)  # Preferred language code

    # Status
    is_primary = Column(Boolean, default=False)  # Primary contact for this type
    is_active = Column(Boolean, default=True)

    # Notes
    notes = Column(Text, nullable=True)

    # Audit
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    address_book = relationship("AddressBook", back_populates="contacts")


# =============================================================================
# SUPPLIER INVOICE & PAYMENT MODELS (Complete Procure-to-Pay Cycle)
# =============================================================================

class SupplierInvoice(Base):
    """
    Supplier Invoice - Formal invoice document from supplier for goods/services.
    Links to PO and GRN for three-way matching. Triggers GRNI clearing when matched.

    Workflow: draft → pending_approval → approved → partially_paid → paid → cancelled
    """
    __tablename__ = "supplier_invoices"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    invoice_number = Column(String(50), nullable=False)  # SI-YYYY-NNNNN (internal)

    # Supplier Details
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=False)  # Vendor
    supplier_invoice_number = Column(String(100), nullable=True)  # Supplier's own invoice number

    # Dates
    invoice_date = Column(Date, nullable=False)
    received_date = Column(Date, nullable=True)  # When invoice was received
    due_date = Column(Date, nullable=True)  # Payment due date (calculated from payment terms)

    # Payment Terms
    payment_terms = Column(String(50), nullable=True)  # Net30, Net60, 2/10Net30, etc.
    payment_terms_days = Column(Integer, default=30)  # Days until due
    early_payment_discount_percent = Column(Numeric(5, 2), default=0)  # e.g., 2% for 2/10
    early_payment_discount_days = Column(Integer, nullable=True)  # e.g., 10 days for 2/10

    # Linkages
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id"), nullable=True)  # Primary GRN for matching
    processed_image_id = Column(Integer, ForeignKey("processed_images.id"), nullable=True)  # Scanned invoice image

    # Financial Details
    currency = Column(String(3), default='USD')
    exchange_rate = Column(Numeric(18, 6), default=1.0)
    subtotal = Column(Numeric(18, 2), default=0)  # Before tax
    tax_amount = Column(Numeric(18, 2), default=0)
    total_amount = Column(Numeric(18, 2), default=0)  # subtotal + tax

    # Amounts in base currency
    subtotal_base = Column(Numeric(18, 2), default=0)
    tax_amount_base = Column(Numeric(18, 2), default=0)
    total_amount_base = Column(Numeric(18, 2), default=0)

    # Payment tracking
    amount_paid = Column(Numeric(18, 2), default=0)
    amount_remaining = Column(Numeric(18, 2), default=0)

    # Status workflow: draft → pending_approval → approved → partially_paid → paid → cancelled
    status = Column(String(30), default='draft')

    # Three-way match status
    match_status = Column(String(30), nullable=True)  # pending, matched, variance, failed
    po_variance_amount = Column(Numeric(18, 2), default=0)  # Difference from PO
    grn_variance_amount = Column(Numeric(18, 2), default=0)  # Difference from GRN
    variance_explanation = Column(Text, nullable=True)

    # Approval workflow
    approval_status = Column(String(20), default='pending')  # pending, approved, rejected
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Hold status (for payment hold)
    is_on_hold = Column(Boolean, default=False)
    hold_reason = Column(Text, nullable=True)
    hold_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    hold_at = Column(DateTime, nullable=True)

    # Journal entries
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)  # AP posting
    grni_clearing_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)  # GRNI clearing

    # GRNI clearing status
    is_grni_cleared = Column(Boolean, default=False)

    notes = Column(Text, nullable=True)

    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'invoice_number', name='uq_supplier_invoice_number'),
        UniqueConstraint('company_id', 'address_book_id', 'supplier_invoice_number',
                        name='uq_supplier_invoice_vendor_ref'),
    )

    # Relationships
    company = relationship("Company", backref="supplier_invoices")
    address_book = relationship("AddressBook", backref="supplier_invoices")
    purchase_order = relationship("PurchaseOrder", backref="supplier_invoices")
    goods_receipt = relationship("GoodsReceipt", backref="supplier_invoices")
    processed_image = relationship("ProcessedImage", backref="supplier_invoice")
    lines = relationship("SupplierInvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("SupplierPaymentAllocation", back_populates="invoice")
    journal_entry = relationship("JournalEntry", foreign_keys=[journal_entry_id])
    grni_clearing_entry = relationship("JournalEntry", foreign_keys=[grni_clearing_entry_id])
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    holder = relationship("User", foreign_keys=[hold_by])


class SupplierInvoiceLine(Base):
    """
    Supplier Invoice Line - Individual line items on an invoice.
    Links to PO line and GRN line for detailed matching.
    """
    __tablename__ = "supplier_invoice_lines"

    id = Column(Integer, primary_key=True, index=True)
    supplier_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, nullable=False)

    # Item details
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=True)
    item_code = Column(String(50), nullable=True)
    description = Column(String(500), nullable=False)

    # Quantities and pricing
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(20), default='EA')
    unit_price = Column(Numeric(18, 4), nullable=False)
    total_price = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), default=0)

    # Linkages for matching
    po_line_id = Column(Integer, ForeignKey("purchase_order_lines.id"), nullable=True)
    grn_line_id = Column(Integer, ForeignKey("goods_receipt_lines.id"), nullable=True)

    # Variance tracking
    quantity_variance = Column(Numeric(18, 4), default=0)  # Difference from PO/GRN
    price_variance = Column(Numeric(18, 4), default=0)  # Price difference
    has_variance = Column(Boolean, default=False)

    # GL Account override (if different from default)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    invoice = relationship("SupplierInvoice", back_populates="lines")
    item = relationship("ItemMaster")
    po_line = relationship("PurchaseOrderLine")
    grn_line = relationship("GoodsReceiptLine")
    account = relationship("Account")


class SupplierPayment(Base):
    """
    Supplier Payment - Payment made to a supplier for one or more invoices.
    Supports partial payments and multiple invoices per payment.

    Workflow: draft → pending_approval → approved → posted → cancelled
    """
    __tablename__ = "supplier_payments"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    payment_number = Column(String(50), nullable=False)  # PAY-YYYY-NNNNN

    # Supplier
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=False)

    # Payment Details
    payment_date = Column(Date, nullable=False)
    payment_method = Column(String(30), nullable=False)  # check, bank_transfer, wire, ach, card, cash

    # Bank/Check details
    bank_account = Column(String(100), nullable=True)  # Paying bank account
    check_number = Column(String(50), nullable=True)
    reference_number = Column(String(100), nullable=True)  # Wire ref, ACH trace, etc.

    # Financial
    currency = Column(String(3), default='USD')
    exchange_rate = Column(Numeric(18, 6), default=1.0)
    total_amount = Column(Numeric(18, 2), nullable=False)  # Total payment amount
    total_amount_base = Column(Numeric(18, 2), nullable=False)

    # Discount taken
    discount_taken = Column(Numeric(18, 2), default=0)  # Early payment discount

    # Status: draft → pending_approval → approved → posted → voided
    status = Column(String(20), default='draft')

    # Approval
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    # Posting
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    posted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    posted_at = Column(DateTime, nullable=True)

    # Void tracking
    voided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    voided_at = Column(DateTime, nullable=True)
    void_reason = Column(Text, nullable=True)

    notes = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'payment_number', name='uq_supplier_payment_number'),
    )

    # Relationships
    company = relationship("Company", backref="supplier_payments")
    address_book = relationship("AddressBook", backref="supplier_payments")
    allocations = relationship("SupplierPaymentAllocation", back_populates="payment", cascade="all, delete-orphan")
    journal_entry = relationship("JournalEntry", foreign_keys=[journal_entry_id])
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    poster = relationship("User", foreign_keys=[posted_by])
    voider = relationship("User", foreign_keys=[voided_by])


class SupplierPaymentAllocation(Base):
    """
    Payment Allocation - Links payments to invoices.
    Supports partial payments and multiple invoices per payment.
    """
    __tablename__ = "supplier_payment_allocations"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("supplier_payments.id", ondelete="CASCADE"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=False)

    # Allocation amounts
    allocated_amount = Column(Numeric(18, 2), nullable=False)  # Amount applied to this invoice
    discount_amount = Column(Numeric(18, 2), default=0)  # Early payment discount

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint('payment_id', 'invoice_id', name='uq_payment_invoice_allocation'),
    )

    # Relationships
    payment = relationship("SupplierPayment", back_populates="allocations")
    invoice = relationship("SupplierInvoice", back_populates="payments")


class DebitNote(Base):
    """
    Debit Note / Return to Vendor (RTV) - For returning goods to supplier.
    Creates a credit against supplier account.

    Workflow: draft → approved → posted → cancelled
    """
    __tablename__ = "debit_notes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    debit_note_number = Column(String(50), nullable=False)  # DN-YYYY-NNNNN

    # Supplier
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=False)

    # Source references
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id"), nullable=True)
    supplier_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)

    # Details
    debit_note_date = Column(Date, nullable=False)
    reason = Column(String(50), nullable=False)  # damaged, wrong_item, quality_reject, over_delivery, price_adjustment

    # Financial
    currency = Column(String(3), default='USD')
    exchange_rate = Column(Numeric(18, 6), default=1.0)
    subtotal = Column(Numeric(18, 2), default=0)
    tax_amount = Column(Numeric(18, 2), default=0)
    total_amount = Column(Numeric(18, 2), default=0)

    # Return shipping (if physical return)
    return_required = Column(Boolean, default=True)
    return_authorization_number = Column(String(100), nullable=True)  # Supplier's RA number
    return_tracking_number = Column(String(100), nullable=True)
    return_shipped_date = Column(Date, nullable=True)
    return_received_date = Column(Date, nullable=True)  # Confirmed by supplier

    # Status: draft → approved → posted → applied → cancelled
    status = Column(String(20), default='draft')

    # Approval
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    # Journal entry
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)

    # Application to invoice/payment
    applied_to_invoice_id = Column(Integer, ForeignKey("supplier_invoices.id"), nullable=True)
    applied_amount = Column(Numeric(18, 2), default=0)

    notes = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'debit_note_number', name='uq_debit_note_number'),
    )

    # Relationships
    company = relationship("Company", backref="debit_notes")
    address_book = relationship("AddressBook", backref="debit_notes")
    goods_receipt = relationship("GoodsReceipt", backref="debit_notes")
    supplier_invoice = relationship("SupplierInvoice", foreign_keys=[supplier_invoice_id], backref="debit_notes")
    purchase_order = relationship("PurchaseOrder", backref="debit_notes")
    lines = relationship("DebitNoteLine", back_populates="debit_note", cascade="all, delete-orphan")
    journal_entry = relationship("JournalEntry", foreign_keys=[journal_entry_id])
    applied_to_invoice = relationship("SupplierInvoice", foreign_keys=[applied_to_invoice_id])
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])


class DebitNoteLine(Base):
    """
    Debit Note Line - Individual items being returned or credited.
    """
    __tablename__ = "debit_note_lines"

    id = Column(Integer, primary_key=True, index=True)
    debit_note_id = Column(Integer, ForeignKey("debit_notes.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, nullable=False)

    # Item
    item_id = Column(Integer, ForeignKey("item_master.id"), nullable=True)
    item_code = Column(String(50), nullable=True)
    description = Column(String(500), nullable=False)

    # Quantities
    quantity = Column(Numeric(18, 4), nullable=False)
    unit = Column(String(20), default='EA')
    unit_price = Column(Numeric(18, 4), nullable=False)
    total_price = Column(Numeric(18, 2), nullable=False)

    # Source line references
    grn_line_id = Column(Integer, ForeignKey("goods_receipt_lines.id"), nullable=True)
    invoice_line_id = Column(Integer, ForeignKey("supplier_invoice_lines.id"), nullable=True)

    # Return details
    reason = Column(String(200), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)  # Where item was stored

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    debit_note = relationship("DebitNote", back_populates="lines")
    item = relationship("ItemMaster")
    grn_line = relationship("GoodsReceiptLine")
    invoice_line = relationship("SupplierInvoiceLine")
    warehouse = relationship("Warehouse")


class PurchaseOrderAmendment(Base):
    """
    Purchase Order Amendment - Track changes to PO after it has been sent.
    Maintains history of changes for audit purposes.
    """
    __tablename__ = "purchase_order_amendments"

    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    amendment_number = Column(Integer, nullable=False)  # Sequential per PO (1, 2, 3...)

    # Amendment details
    amendment_date = Column(Date, nullable=False)
    amendment_type = Column(String(30), nullable=False)  # quantity_change, price_change, date_change, line_add, line_remove, cancellation

    # What changed (JSON snapshot)
    changes_summary = Column(Text, nullable=False)  # JSON: {"field": "quantity", "old": 10, "new": 15, "line_id": 123}

    # Original vs New values
    original_total = Column(Numeric(18, 2), nullable=True)
    new_total = Column(Numeric(18, 2), nullable=True)

    # Reason
    reason = Column(Text, nullable=False)

    # Approval
    status = Column(String(20), default='pending')  # pending, approved, rejected
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint('purchase_order_id', 'amendment_number', name='uq_po_amendment_number'),
    )

    # Relationships
    purchase_order = relationship("PurchaseOrder", backref="amendments")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])


# ============================================================================
# Fleet Management Models
# ============================================================================

class Vehicle(Base):
    """
    Vehicle - Fleet vehicle for company operations
    Tracks vehicles used by technicians for work orders and site visits.
    """
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    # Vehicle Identification
    vehicle_number = Column(String(50), nullable=False, index=True)  # Fleet number, e.g., VEH-001
    license_plate = Column(String(20), nullable=False, index=True)
    vin = Column(String(50), nullable=True)  # Vehicle Identification Number

    # Vehicle Details
    make = Column(String(100), nullable=True)  # Toyota, Ford, etc.
    model = Column(String(100), nullable=True)  # Camry, F-150, etc.
    year = Column(Integer, nullable=True)
    color = Column(String(50), nullable=True)
    vehicle_type = Column(String(50), nullable=True)  # Sedan, SUV, Van, Truck, Pickup
    fuel_type = Column(String(30), nullable=True)  # Gasoline, Diesel, Electric, Hybrid

    # Capacity
    seating_capacity = Column(Integer, nullable=True)
    cargo_capacity_kg = Column(Float, nullable=True)

    # Purchase/Lease Info
    ownership_type = Column(String(20), default='owned')  # owned, leased, rented
    purchase_date = Column(Date, nullable=True)
    purchase_price = Column(Numeric(12, 2), nullable=True)
    lease_end_date = Column(Date, nullable=True)
    lease_monthly_cost = Column(Numeric(10, 2), nullable=True)

    # Current Status
    status = Column(String(30), default='available')  # available, in_use, maintenance, out_of_service, disposed
    current_odometer = Column(Float, default=0)  # Current mileage in km
    odometer_unit = Column(String(5), default='km')  # km or mi

    # Assignment
    assigned_driver_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)  # Primary driver (employee)
    assigned_site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)  # Assigned site/location

    # Insurance
    insurance_policy_number = Column(String(100), nullable=True)
    insurance_provider = Column(String(100), nullable=True)
    insurance_expiry = Column(Date, nullable=True)

    # Registration
    registration_number = Column(String(50), nullable=True)
    registration_expiry = Column(Date, nullable=True)

    # Maintenance Schedule
    last_service_date = Column(Date, nullable=True)
    last_service_odometer = Column(Float, nullable=True)
    next_service_due_date = Column(Date, nullable=True)
    next_service_due_odometer = Column(Float, nullable=True)
    service_interval_km = Column(Float, default=5000)  # Service every X km
    service_interval_months = Column(Integer, default=6)  # Or every X months

    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('company_id', 'vehicle_number', name='uq_company_vehicle_number'),
        UniqueConstraint('company_id', 'license_plate', name='uq_company_license_plate'),
    )

    # Relationships
    company = relationship("Company", backref="vehicles")
    assigned_driver = relationship("AddressBook", foreign_keys=[assigned_driver_id])
    assigned_site = relationship("Site", backref="vehicles")
    creator = relationship("User", foreign_keys=[created_by])
    maintenance_records = relationship("VehicleMaintenance", back_populates="vehicle", cascade="all, delete-orphan")
    fuel_records = relationship("VehicleFuelLog", back_populates="vehicle", cascade="all, delete-orphan")


class VehicleMaintenance(Base):
    """
    Vehicle Maintenance Record - Tracks all maintenance activities for vehicles
    """
    __tablename__ = "vehicle_maintenance"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)

    # Maintenance Details
    maintenance_number = Column(String(50), nullable=False, index=True)  # MNT-2025-00001
    maintenance_date = Column(Date, nullable=False)
    maintenance_type = Column(String(50), nullable=False)  # scheduled, unscheduled, repair, inspection, tire_change, oil_change

    # Odometer at service
    odometer_reading = Column(Float, nullable=True)

    # Description
    description = Column(Text, nullable=False)
    work_performed = Column(Text, nullable=True)

    # Costs
    labor_cost = Column(Numeric(10, 2), default=0)
    parts_cost = Column(Numeric(10, 2), default=0)
    total_cost = Column(Numeric(10, 2), default=0)

    # Service Provider
    service_provider = Column(String(200), nullable=True)  # Garage/workshop name
    service_provider_address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)  # Linked vendor
    invoice_number = Column(String(50), nullable=True)
    invoice_date = Column(Date, nullable=True)

    # Status
    status = Column(String(20), default='completed')  # scheduled, in_progress, completed, cancelled

    # Next Service
    next_service_date = Column(Date, nullable=True)
    next_service_odometer = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company")
    vehicle = relationship("Vehicle", back_populates="maintenance_records")
    service_provider_vendor = relationship("AddressBook", foreign_keys=[service_provider_address_book_id])
    creator = relationship("User", foreign_keys=[created_by])


class VehicleFuelLog(Base):
    """
    Vehicle Fuel Log - Tracks fuel consumption for vehicles
    """
    __tablename__ = "vehicle_fuel_logs"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)

    # Fuel Record Details
    fuel_log_number = Column(String(50), nullable=False, index=True)  # FUEL-2025-00001
    fuel_date = Column(Date, nullable=False)
    fuel_time = Column(Time, nullable=True)

    # Odometer
    odometer_reading = Column(Float, nullable=False)

    # Fuel Details
    fuel_type = Column(String(30), nullable=True)  # Gasoline, Diesel, Electric
    quantity_liters = Column(Numeric(8, 2), nullable=False)
    unit_price = Column(Numeric(8, 4), nullable=True)
    total_cost = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default='USD')

    # Full tank?
    is_full_tank = Column(Boolean, default=True)

    # Location
    fuel_station = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)

    # Driver
    driver_id = Column(Integer, ForeignKey("address_book.id"), nullable=True)

    # Efficiency (calculated)
    km_since_last_fill = Column(Float, nullable=True)
    liters_per_100km = Column(Float, nullable=True)  # Fuel consumption rate

    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    company = relationship("Company")
    vehicle = relationship("Vehicle", back_populates="fuel_records")
    driver = relationship("AddressBook", foreign_keys=[driver_id])
    creator = relationship("User", foreign_keys=[created_by])


# =============================================================================
# CLIENT PORTAL MODELS
# =============================================================================

class Service(Base):
    """
    Service types available for client portal ticket submission.
    Examples: HVAC Repair, Electrical, Plumbing, General Maintenance, etc.
    """
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    display_order = Column(Integer, default=0)  # For ordering in dropdowns

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    company = relationship("Company", backref="services")

    __table_args__ = (
        UniqueConstraint('company_id', 'name', name='uq_service_name_per_company'),
    )


class ClientUser(Base):
    """
    Client Portal User - Separate from internal Users, linked to AddressBook Customer/Branch.
    Clients can submit tickets and view work orders for their accessible sites.
    """
    __tablename__ = "client_users"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    address_book_id = Column(Integer, ForeignKey("address_book.id"), nullable=False)  # Customer (C) or Branch (CB)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    hashed_password = Column(String(255), nullable=True)  # Null until invitation accepted
    is_active = Column(Boolean, default=True)

    # Invitation tracking
    invitation_token = Column(String(255), nullable=True, index=True)
    invitation_sent_at = Column(DateTime, nullable=True)
    invitation_accepted_at = Column(DateTime, nullable=True)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Password reset
    reset_token = Column(String(255), nullable=True)
    reset_token_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    company = relationship("Company", backref="client_users")
    address_book = relationship("AddressBook", backref="client_user")
    inviter = relationship("User", foreign_keys=[invited_by])

    __table_args__ = (
        UniqueConstraint('company_id', 'email', name='uq_client_user_email_per_company'),
    )


class ClientRefreshToken(Base):
    """Refresh tokens for Client Portal authentication"""
    __tablename__ = "client_refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    client_user_id = Column(Integer, ForeignKey("client_users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    client_user = relationship("ClientUser", backref="refresh_tokens")
