from pydantic import BaseModel, EmailStr, Field, computed_field, model_validator
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Literal, Any


class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class UserCreate(UserBase):
    password: str
    name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class PasswordReset(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class User(UserBase):
    id: int
    is_active: bool
    is_admin: bool = False
    remaining_documents: int
    phone: Optional[str] = None
    role: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserInfo(BaseModel):
    """User info returned with login token"""
    id: int
    email: str
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: bool
    phone: Optional[str] = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int  # Access token expiry in seconds
    user: Optional[UserInfo] = None  # User info returned on login


class TokenData(BaseModel):
    email: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ProcessedImageBase(BaseModel):
    original_filename: str
    processing_status: str


class ProcessedImageCreate(ProcessedImageBase):
    pass


class ProcessedImage(ProcessedImageBase):
    id: int
    user_id: int
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None
    ocr_extracted_words: int = 0
    ocr_average_confidence: float = 0.0
    ocr_preprocessing_methods: int = 1
    patterns_detected: int = 0
    has_structured_data: bool = False
    structured_data: Optional[str] = None
    extraction_confidence: float = 0.0
    processing_method: str = "basic"
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProcessedImageList(BaseModel):
    images: List[ProcessedImage]
    total: int
    page: int
    size: int


class OTPRequest(BaseModel):
    email: EmailStr
    purpose: Optional[str] = "email_verification"


class OTPVerification(BaseModel):
    email: EmailStr
    otp_code: str
    purpose: Optional[str] = "email_verification"


class OTPResponse(BaseModel):
    message: str
    expires_in_minutes: int
    max_attempts: int

# ============================================================================
# Client Schemas
# ============================================================================

class ClientBase(BaseModel):
    name: str
    code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    contact_person: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Client(ClientBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================================
# Site Schemas
# ============================================================================

class SiteBase(BaseModel):
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    site_manager: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class SiteCreate(SiteBase):
    client_id: int


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    site_manager: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Site(SiteBase):
    id: int
    client_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Block Schemas
# ============================================================================

class BlockBase(BaseModel):
    name: str
    code: Optional[str] = None
    block_type: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class BlockCreate(BlockBase):
    site_id: int


class BlockUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    block_type: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Block(BlockBase):
    id: int
    site_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Building Schemas
# ============================================================================

class BuildingBase(BaseModel):
    name: str
    code: Optional[str] = None
    building_type: Optional[str] = None
    address: Optional[str] = None
    total_floors: Optional[int] = None
    total_area_sqm: Optional[float] = None
    year_built: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class BuildingCreate(BuildingBase):
    site_id: Optional[int] = None  # For direct site-level buildings
    block_id: Optional[int] = None  # For buildings within a block


class BuildingUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    building_type: Optional[str] = None
    address: Optional[str] = None
    total_floors: Optional[int] = None
    total_area_sqm: Optional[float] = None
    year_built: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Building(BuildingBase):
    id: int
    site_id: Optional[int] = None
    block_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Space Schemas
# ============================================================================

class SpaceBase(BaseModel):
    name: str
    code: Optional[str] = None
    space_type: Optional[str] = None
    area_sqm: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class SpaceCreate(SpaceBase):
    site_id: Optional[int] = None  # For site-level spaces
    building_id: Optional[int] = None  # For building-level spaces


class SpaceUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    space_type: Optional[str] = None
    area_sqm: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Space(SpaceBase):
    id: int
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Floor Schemas
# ============================================================================

class FloorBase(BaseModel):
    name: str
    code: Optional[str] = None
    level: int = 0
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class FloorCreate(FloorBase):
    building_id: Optional[int] = None  # Optional because it comes from URL path


class FloorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    level: Optional[int] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Floor(FloorBase):
    id: int
    building_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Unit Schemas
# ============================================================================

class UnitBase(BaseModel):
    name: str
    code: Optional[str] = None
    unit_type: Optional[str] = None
    area_sqm: Optional[float] = None
    tenant_name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class UnitCreate(UnitBase):
    floor_id: Optional[int] = None  # Optional because it comes from URL path


class UnitUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    unit_type: Optional[str] = None
    area_sqm: Optional[float] = None
    tenant_name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Unit(UnitBase):
    id: int
    floor_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Room Schemas
# ============================================================================

class RoomBase(BaseModel):
    name: str
    code: Optional[str] = None
    room_type: Optional[str] = None
    area_sqm: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class RoomCreate(RoomBase):
    floor_id: Optional[int] = None  # Direct parent floor (if not in a unit)
    unit_id: Optional[int] = None   # Parent unit (if in a unit)


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    room_type: Optional[str] = None
    area_sqm: Optional[float] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Room(RoomBase):
    id: int
    floor_id: Optional[int] = None
    unit_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Desk Schemas
# ============================================================================

class DeskBase(BaseModel):
    name: str
    code: Optional[str] = None
    desk_type: Optional[str] = None
    occupant_name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class DeskCreate(DeskBase):
    room_id: Optional[int] = None  # Optional because it comes from URL path


class DeskUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    desk_type: Optional[str] = None
    occupant_name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Desk(DeskBase):
    id: int
    room_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Equipment Schemas
# ============================================================================

class EquipmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    category: str
    equipment_type: Optional[str] = None
    pm_equipment_class_id: Optional[int] = None
    pm_asset_type_id: Optional[int] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installation_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    status: str = "operational"
    condition_rating: Optional[int] = None
    notes: Optional[str] = None
    is_active: bool = True


class EquipmentCreate(EquipmentBase):
    # Only one parent should be set
    client_id: Optional[int] = None
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    space_id: Optional[int] = None
    floor_id: Optional[int] = None
    unit_id: Optional[int] = None
    room_id: Optional[int] = None
    desk_id: Optional[int] = None


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[str] = None
    equipment_type: Optional[str] = None
    pm_equipment_class_id: Optional[int] = None
    pm_asset_type_id: Optional[int] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installation_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    status: Optional[str] = None
    condition_rating: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class Equipment(EquipmentBase):
    id: int
    client_id: Optional[int] = None
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    space_id: Optional[int] = None
    floor_id: Optional[int] = None
    unit_id: Optional[int] = None
    room_id: Optional[int] = None
    desk_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# SubEquipment Schemas
# ============================================================================

class SubEquipmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    component_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    status: str = "operational"
    notes: Optional[str] = None
    is_active: bool = True


class SubEquipmentCreate(SubEquipmentBase):
    equipment_id: Optional[int] = None
    # Direct parent assignment (alternative to equipment_id)
    client_id: Optional[int] = None
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    space_id: Optional[int] = None
    floor_id: Optional[int] = None
    room_id: Optional[int] = None


class SubEquipmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    component_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SubEquipment(SubEquipmentBase):
    id: int
    equipment_id: Optional[int] = None
    client_id: Optional[int] = None
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    space_id: Optional[int] = None
    floor_id: Optional[int] = None
    room_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Scope Schemas (Reference table for contract scopes)
# ============================================================================

class ScopeBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class ScopeCreate(ScopeBase):
    pass


class ScopeUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class Scope(ScopeBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Contract Scope Schemas (with SLA)
# ============================================================================

class ContractScopeBase(BaseModel):
    scope_id: int
    allocated_budget: Optional[float] = None
    # SLA - Response Time
    sla_response_time_hours: Optional[int] = None
    sla_response_time_priority_low: Optional[int] = None
    sla_response_time_priority_medium: Optional[int] = None
    sla_response_time_priority_high: Optional[int] = None
    sla_response_time_priority_critical: Optional[int] = None
    # SLA - Resolution Time
    sla_resolution_time_hours: Optional[int] = None
    sla_resolution_time_priority_low: Optional[int] = None
    sla_resolution_time_priority_medium: Optional[int] = None
    sla_resolution_time_priority_high: Optional[int] = None
    sla_resolution_time_priority_critical: Optional[int] = None
    # SLA - Availability
    sla_availability_percent: Optional[float] = None
    # SLA - Penalties
    sla_penalty_response_breach: Optional[float] = None
    sla_penalty_resolution_breach: Optional[float] = None
    sla_penalty_availability_breach: Optional[float] = None
    sla_penalty_calculation: Optional[str] = None  # fixed, percentage, per_hour
    notes: Optional[str] = None
    is_active: bool = True


class ContractScopeCreate(ContractScopeBase):
    pass


class ContractScopeUpdate(BaseModel):
    scope_id: Optional[int] = None
    allocated_budget: Optional[float] = None
    sla_response_time_hours: Optional[int] = None
    sla_response_time_priority_low: Optional[int] = None
    sla_response_time_priority_medium: Optional[int] = None
    sla_response_time_priority_high: Optional[int] = None
    sla_response_time_priority_critical: Optional[int] = None
    sla_resolution_time_hours: Optional[int] = None
    sla_resolution_time_priority_low: Optional[int] = None
    sla_resolution_time_priority_medium: Optional[int] = None
    sla_resolution_time_priority_high: Optional[int] = None
    sla_resolution_time_priority_critical: Optional[int] = None
    sla_availability_percent: Optional[float] = None
    sla_penalty_response_breach: Optional[float] = None
    sla_penalty_resolution_breach: Optional[float] = None
    sla_penalty_availability_breach: Optional[float] = None
    sla_penalty_calculation: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ContractScope(ContractScopeBase):
    id: int
    contract_id: int
    created_at: datetime
    updated_at: datetime
    scope: Optional[Scope] = None  # Include related scope for display

    class Config:
        from_attributes = True


# ============================================================================
# Contract Schemas
# ============================================================================

class ContractBase(BaseModel):
    contract_number: str
    name: str
    description: Optional[str] = None
    contract_type: str = "comprehensive"  # comprehensive, non_comprehensive, with_threshold
    threshold_amount: Optional[float] = None
    threshold_period: Optional[str] = None  # per_work_order, monthly, yearly, contract_period
    start_date: date
    end_date: date
    contract_value: Optional[float] = None
    budget: Optional[float] = None
    currency: str = "USD"
    status: str = "draft"  # draft, active, expired, terminated, renewed
    is_renewable: bool = False
    renewal_notice_days: Optional[int] = None
    auto_renew: bool = False
    document_url: Optional[str] = None
    notes: Optional[str] = None
    terms_conditions: Optional[str] = None
    is_active: bool = True


class ContractCreate(ContractBase):
    client_id: int
    site_ids: Optional[List[int]] = []  # Sites covered by this contract
    scopes: Optional[List[ContractScopeCreate]] = []  # Scopes with SLAs


class ContractUpdate(BaseModel):
    contract_number: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    contract_type: Optional[str] = None
    threshold_amount: Optional[float] = None
    threshold_period: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    contract_value: Optional[float] = None
    budget: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    is_renewable: Optional[bool] = None
    renewal_notice_days: Optional[int] = None
    auto_renew: Optional[bool] = None
    document_url: Optional[str] = None
    notes: Optional[str] = None
    terms_conditions: Optional[str] = None
    is_active: Optional[bool] = None
    site_ids: Optional[List[int]] = None  # Update sites covered
    scopes: Optional[List[ContractScopeCreate]] = None  # Update scopes


class Contract(ContractBase):
    id: int
    company_id: int
    client_id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    sites: List[Site] = []
    scopes: List[ContractScope] = []

    class Config:
        from_attributes = True


class ContractList(BaseModel):
    contracts: List[Contract]
    total: int
    page: int
    size: int


# ============================================================================
# Ticket Schemas
# ============================================================================

class TicketBase(BaseModel):
    title: str
    description: str
    category: str  # maintenance, repair, installation, inspection, other
    priority: str = "medium"  # low, medium, high, urgent
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    room_id: Optional[int] = None
    location_description: Optional[str] = None
    equipment_id: Optional[int] = None
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None
    requester_phone: Optional[str] = None
    preferred_date: Optional[date] = None
    preferred_time_slot: Optional[str] = None  # morning, afternoon, evening, anytime


class TicketCreate(TicketBase):
    pass


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    site_id: Optional[int] = None
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    room_id: Optional[int] = None
    location_description: Optional[str] = None
    equipment_id: Optional[int] = None
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None
    requester_phone: Optional[str] = None
    preferred_date: Optional[date] = None
    preferred_time_slot: Optional[str] = None
    internal_notes: Optional[str] = None


class TicketStatusUpdate(BaseModel):
    status: str  # open, in_review, approved, converted, rejected, closed
    review_notes: Optional[str] = None
    rejection_reason: Optional[str] = None


class TicketConvertToWorkOrder(BaseModel):
    work_order_type: str = "corrective"  # corrective, preventive, operations
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    technician_ids: Optional[List[int]] = None
    assigned_hhd_id: Optional[int] = None
    is_billable: bool = False
    contract_id: Optional[int] = None
    notes: Optional[str] = None


class TicketRequester(BaseModel):
    id: int
    email: str
    name: Optional[str] = None

    class Config:
        from_attributes = True


class TicketSite(BaseModel):
    id: int
    name: str
    code: Optional[str] = None

    class Config:
        from_attributes = True


class TicketEquipment(BaseModel):
    id: int
    name: str
    code: Optional[str] = None

    class Config:
        from_attributes = True


class TicketWorkOrder(BaseModel):
    id: int
    wo_number: str
    title: str
    status: str

    class Config:
        from_attributes = True


class Ticket(TicketBase):
    id: int
    company_id: int
    ticket_number: str
    status: str
    attachments: Optional[str] = None
    work_order_id: Optional[int] = None
    converted_at: Optional[datetime] = None
    converted_by: Optional[int] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    internal_notes: Optional[str] = None
    requested_by: int
    created_at: datetime
    updated_at: datetime

    # Related objects
    requester: Optional[TicketRequester] = None
    site: Optional[TicketSite] = None
    equipment: Optional[TicketEquipment] = None
    work_order: Optional[TicketWorkOrder] = None

    class Config:
        from_attributes = True


class TicketList(BaseModel):
    tickets: List[Ticket]
    total: int
    page: int
    size: int


# ============================================================================
# Accounting Ledger Schemas
# ============================================================================

# Account Type Schemas
class AccountTypeBase(BaseModel):
    code: str
    name: str
    normal_balance: str  # debit or credit
    display_order: int = 0
    is_active: bool = True


class AccountTypeCreate(AccountTypeBase):
    pass


class AccountTypeUpdate(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class AccountType(AccountTypeBase):
    id: int
    company_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Account Schemas
class AccountBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    account_type_id: int
    parent_id: Optional[int] = None
    is_site_specific: bool = False
    is_header: bool = False
    is_bank_account: bool = False
    is_control_account: bool = False
    is_active: bool = True


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None
    is_site_specific: Optional[bool] = None
    is_header: Optional[bool] = None
    is_bank_account: Optional[bool] = None
    is_control_account: Optional[bool] = None
    is_active: Optional[bool] = None


class AccountBrief(BaseModel):
    id: int
    code: str
    name: str
    account_type_id: int

    class Config:
        from_attributes = True


class Account(AccountBase):
    id: int
    company_id: int
    is_system: bool = False
    created_at: datetime
    updated_at: datetime
    account_type: Optional[AccountType] = None

    class Config:
        from_attributes = True


class AccountWithChildren(Account):
    children: List["AccountWithChildren"] = []


# Fiscal Period Schemas
class FiscalPeriodBase(BaseModel):
    fiscal_year: int
    period_number: int
    period_name: str
    start_date: date
    end_date: date


class FiscalPeriodCreate(FiscalPeriodBase):
    pass


class FiscalPeriodUpdate(BaseModel):
    period_name: Optional[str] = None
    status: Optional[str] = None


class FiscalPeriod(FiscalPeriodBase):
    id: int
    company_id: int
    status: str = "open"
    closed_at: Optional[datetime] = None
    closed_by: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Journal Entry Line Schemas
class JournalEntryLineBase(BaseModel):
    account_id: int
    debit: float = 0
    credit: float = 0
    description: Optional[str] = None
    business_unit_id: Optional[int] = None  # Primary dimension (JDE concept)
    site_id: Optional[int] = None  # Legacy - kept for backward compatibility
    contract_id: Optional[int] = None
    work_order_id: Optional[int] = None
    vendor_id: Optional[int] = None
    project_id: Optional[int] = None
    technician_id: Optional[int] = None
    line_number: int = 1


class JournalEntryLineCreate(JournalEntryLineBase):
    pass


class JournalEntryLineBrief(BaseModel):
    id: int
    account_id: int
    debit: float
    credit: float
    description: Optional[str] = None
    business_unit_id: Optional[int] = None
    site_id: Optional[int] = None
    line_number: int
    account: Optional[AccountBrief] = None

    class Config:
        from_attributes = True


class JournalEntryLine(JournalEntryLineBase):
    id: int
    journal_entry_id: int
    created_at: datetime
    account: Optional[AccountBrief] = None

    class Config:
        from_attributes = True


# Journal Entry Schemas
class JournalEntryBase(BaseModel):
    entry_date: date
    description: str
    reference: Optional[str] = None


class JournalEntryCreate(JournalEntryBase):
    lines: List[JournalEntryLineCreate]
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_number: Optional[str] = None


class JournalEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    description: Optional[str] = None
    reference: Optional[str] = None
    lines: Optional[List[JournalEntryLineCreate]] = None


class JournalEntryBrief(BaseModel):
    id: int
    entry_number: str
    entry_date: date
    description: str
    status: str
    total_debit: float
    total_credit: float
    source_type: Optional[str] = None
    source_number: Optional[str] = None
    is_auto_generated: bool = False

    class Config:
        from_attributes = True


class JournalEntry(JournalEntryBase):
    id: int
    company_id: int
    entry_number: str
    fiscal_period_id: Optional[int] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_number: Optional[str] = None
    status: str = "draft"
    is_auto_generated: bool = False
    total_debit: float = 0
    total_credit: float = 0
    is_reversal: bool = False
    reversal_of_id: Optional[int] = None
    reversed_by_id: Optional[int] = None
    posted_at: Optional[datetime] = None
    posted_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    lines: List[JournalEntryLine] = []

    class Config:
        from_attributes = True


class JournalEntryList(BaseModel):
    entries: List[JournalEntryBrief]
    total: int
    page: int
    size: int


# Account Balance Schemas
class AccountBalanceBase(BaseModel):
    account_id: int
    fiscal_period_id: int
    business_unit_id: Optional[int] = None  # Primary dimension (JDE concept)
    site_id: Optional[int] = None  # Legacy - kept for backward compatibility
    period_debit: float = 0
    period_credit: float = 0
    opening_balance: float = 0
    closing_balance: float = 0


class AccountBalance(AccountBalanceBase):
    id: int
    company_id: int
    updated_at: datetime

    class Config:
        from_attributes = True


# Default Account Mapping Schemas
class DefaultAccountMappingBase(BaseModel):
    transaction_type: str
    category: Optional[str] = None
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None
    is_active: bool = True
    description: Optional[str] = None


class DefaultAccountMappingCreate(DefaultAccountMappingBase):
    pass


class DefaultAccountMappingUpdate(BaseModel):
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class DefaultAccountMapping(DefaultAccountMappingBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime
    debit_account: Optional[AccountBrief] = None
    credit_account: Optional[AccountBrief] = None

    class Config:
        from_attributes = True


# Site Ledger Report Schemas
class SiteLedgerEntry(BaseModel):
    entry_date: date
    entry_number: str
    description: str
    account_code: str
    account_name: str
    debit: float
    credit: float
    balance: float
    source_type: Optional[str] = None
    source_number: Optional[str] = None


class SiteLedgerReport(BaseModel):
    site_id: int
    site_name: str
    site_code: Optional[str] = None
    period_start: date
    period_end: date
    opening_balance: float
    total_debits: float
    total_credits: float
    closing_balance: float
    entries: List[SiteLedgerEntry]


# Trial Balance Report Schemas
class TrialBalanceRow(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    account_type: str
    debit: float
    credit: float


class TrialBalanceReport(BaseModel):
    as_of_date: date
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    business_unit_id: Optional[int] = None
    business_unit_name: Optional[str] = None
    rows: List[TrialBalanceRow]
    total_debit: float
    total_credit: float


# Profit & Loss Report
class PLLineItem(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    amount: float
    percentage: float = 0.0  # percentage of revenue


class PLSection(BaseModel):
    name: str
    items: List[PLLineItem]
    total: float


class ProfitLossReport(BaseModel):
    start_date: date
    end_date: date
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    business_unit_id: Optional[int] = None
    business_unit_name: Optional[str] = None

    # Revenue section
    revenue: PLSection
    total_revenue: float

    # Cost of Sales / Direct Costs section
    cost_of_sales: PLSection
    total_cost_of_sales: float
    gross_profit: float
    gross_profit_margin: float

    # Operating Expenses section
    operating_expenses: PLSection
    total_operating_expenses: float

    # Summary
    net_income: float
    net_profit_margin: float


# Balance Sheet Report
class BSLineItem(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    balance: float


class BSSection(BaseModel):
    name: str
    items: List[BSLineItem]
    total: float


class BalanceSheetReport(BaseModel):
    as_of_date: date
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    business_unit_id: Optional[int] = None
    business_unit_name: Optional[str] = None

    # Assets
    current_assets: BSSection
    total_current_assets: float
    fixed_assets: BSSection
    total_fixed_assets: float
    total_assets: float

    # Liabilities
    current_liabilities: BSSection
    total_current_liabilities: float
    total_liabilities: float

    # Equity
    equity: BSSection
    retained_earnings: float
    current_period_earnings: float
    total_equity: float

    # Balance check
    total_liabilities_and_equity: float
    is_balanced: bool


# Balance Sheet Diagnostic Schemas
class UnbalancedJournalEntry(BaseModel):
    id: int
    entry_number: str
    entry_date: date
    description: Optional[str] = None
    source_type: Optional[str] = None
    source_number: Optional[str] = None
    total_debit: float
    total_credit: float
    difference: float


class AccountBalanceIssue(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    account_type: str
    normal_balance: str
    computed_balance: float
    issue_description: str


class BalanceSheetDiagnostic(BaseModel):
    as_of_date: date
    total_assets: float
    total_liabilities_and_equity: float
    imbalance_amount: float
    is_balanced: bool
    unbalanced_entries: List[UnbalancedJournalEntry]
    total_unbalanced_amount: float
    account_issues: List[AccountBalanceIssue]
    recommendations: List[str]


# Chart of Accounts initialization
class ChartOfAccountsInit(BaseModel):
    template: str = "default"  # default, property_management, service_company


# Auto-posting request
class AutoPostRequest(BaseModel):
    source_type: str  # invoice, work_order, petty_cash
    source_id: int
    post_immediately: bool = False


# ============================================================================
# Purchase Request Schemas
# ============================================================================

class PurchaseRequestLineCreate(BaseModel):
    item_id: Optional[int] = None
    item_number: Optional[str] = None
    description: str
    quantity_requested: float
    unit: str = "EA"
    estimated_unit_cost: Optional[float] = None
    notes: Optional[str] = None


class PurchaseRequestLineUpdate(BaseModel):
    item_id: Optional[int] = None
    item_number: Optional[str] = None
    description: Optional[str] = None
    quantity_requested: Optional[float] = None
    quantity_approved: Optional[float] = None
    unit: Optional[str] = None
    estimated_unit_cost: Optional[float] = None
    notes: Optional[str] = None


class PurchaseRequestLine(BaseModel):
    id: int
    purchase_request_id: int
    item_id: Optional[int] = None
    item_number: Optional[str] = None
    description: str
    quantity_requested: float
    quantity_approved: Optional[float] = None
    unit: str
    estimated_unit_cost: Optional[float] = None
    estimated_total: Optional[float] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class PurchaseRequestCreate(BaseModel):
    title: str
    description: Optional[str] = None
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    vendor_id: Optional[int] = None
    required_date: Optional[date] = None
    priority: str = "normal"
    currency: str = "USD"
    notes: Optional[str] = None
    lines: Optional[List[PurchaseRequestLineCreate]] = None


class PurchaseRequestUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    vendor_id: Optional[int] = None
    required_date: Optional[date] = None
    priority: Optional[str] = None
    notes: Optional[str] = None


class PurchaseRequest(BaseModel):
    id: int
    company_id: int
    pr_number: str
    status: str
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    vendor_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    required_date: Optional[date] = None
    priority: str
    estimated_total: Optional[float] = 0
    currency: str
    created_by: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    submitted_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[int] = None
    rejection_reason: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by: Optional[int] = None
    notes: Optional[str] = None
    lines: List[PurchaseRequestLine] = []

    @model_validator(mode='before')
    @classmethod
    def map_address_book_to_vendor(cls, data: Any) -> Any:
        """Map address_book_id from ORM model to vendor_id for the schema"""
        if hasattr(data, '__dict__'):
            # It's an ORM model, convert to dict-like access
            obj_dict = {}
            for key in ['id', 'company_id', 'pr_number', 'status', 'work_order_id',
                       'contract_id', 'address_book_id', 'title', 'description',
                       'required_date', 'priority', 'estimated_total', 'currency',
                       'created_by', 'created_at', 'updated_at', 'submitted_at',
                       'submitted_by', 'approved_at', 'approved_by', 'rejection_reason',
                       'rejected_at', 'rejected_by', 'notes', 'lines']:
                if hasattr(data, key):
                    obj_dict[key] = getattr(data, key)
            # Map address_book_id to vendor_id
            if 'address_book_id' in obj_dict:
                obj_dict['vendor_id'] = obj_dict.pop('address_book_id')
            return obj_dict
        elif isinstance(data, dict):
            # It's already a dict
            if 'address_book_id' in data and 'vendor_id' not in data:
                data['vendor_id'] = data.pop('address_book_id')
        return data

    class Config:
        from_attributes = True


class PurchaseRequestList(BaseModel):
    id: int
    pr_number: str
    status: str
    title: str
    priority: str
    estimated_total: float
    currency: str
    required_date: Optional[date] = None
    vendor_name: Optional[str] = None
    work_order_number: Optional[str] = None
    contract_number: Optional[str] = None
    created_by_name: str
    created_at: datetime
    line_count: int = 0

    class Config:
        from_attributes = True


class PurchaseRequestApproval(BaseModel):
    line_approvals: Optional[dict] = None  # {line_id: approved_quantity}
    notes: Optional[str] = None


class PurchaseRequestRejection(BaseModel):
    reason: str


# ============================================================================
# Purchase Order Schemas
# ============================================================================

class PurchaseOrderLineCreate(BaseModel):
    pr_line_id: Optional[int] = None
    item_id: Optional[int] = None
    item_number: Optional[str] = None
    description: str
    quantity_ordered: float
    unit: str = "EA"
    unit_price: float
    notes: Optional[str] = None


class PurchaseOrderLineUpdate(BaseModel):
    item_id: Optional[int] = None
    item_number: Optional[str] = None
    description: Optional[str] = None
    quantity_ordered: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    notes: Optional[str] = None


class PurchaseOrderLineReceive(BaseModel):
    quantity_received: float


class PurchaseOrderLine(BaseModel):
    id: int
    purchase_order_id: int
    pr_line_id: Optional[int] = None
    item_id: Optional[int] = None
    item_number: Optional[str] = None
    description: str
    quantity_ordered: float
    quantity_received: float
    unit: str
    unit_price: float
    total_price: float
    receive_status: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class PurchaseOrderCreate(BaseModel):
    purchase_request_id: Optional[int] = None
    vendor_id: int
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    order_date: Optional[date] = None
    expected_date: Optional[date] = None
    payment_terms: Optional[str] = None
    shipping_address: Optional[str] = None
    currency: str = "USD"
    notes: Optional[str] = None
    lines: Optional[List[PurchaseOrderLineCreate]] = None


class PurchaseOrderUpdate(BaseModel):
    vendor_id: Optional[int] = None
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    order_date: Optional[date] = None
    expected_date: Optional[date] = None
    payment_terms: Optional[str] = None
    shipping_address: Optional[str] = None
    notes: Optional[str] = None


class PurchaseOrder(BaseModel):
    id: int
    company_id: int
    po_number: str
    purchase_request_id: Optional[int] = None
    status: str
    vendor_id: Optional[int] = None  # Vendor from Address Book (mapped from address_book_id)
    work_order_id: Optional[int] = None
    contract_id: Optional[int] = None
    order_date: Optional[date] = None
    expected_date: Optional[date] = None
    subtotal: float
    tax_amount: float
    total_amount: float
    currency: str
    payment_terms: Optional[str] = None
    shipping_address: Optional[str] = None
    created_by: int
    created_at: datetime
    updated_at: datetime
    notes: Optional[str] = None
    lines: List[PurchaseOrderLine] = []
    has_grn: bool = False  # True if PO has any Goods Receipt Notes

    @model_validator(mode='before')
    @classmethod
    def map_address_book_to_vendor(cls, data: Any) -> Any:
        """Map address_book_id from ORM model to vendor_id for the schema"""
        if hasattr(data, '__dict__'):
            # It's an ORM model, convert to dict-like access
            obj_dict = {}
            for key in ['id', 'company_id', 'po_number', 'purchase_request_id', 'status',
                       'address_book_id', 'work_order_id', 'contract_id', 'order_date',
                       'expected_date', 'subtotal', 'tax_amount', 'total_amount', 'currency',
                       'payment_terms', 'shipping_address', 'created_by', 'created_at',
                       'updated_at', 'notes', 'lines', 'has_grn']:
                if hasattr(data, key):
                    obj_dict[key] = getattr(data, key)
            # Map address_book_id to vendor_id
            if 'address_book_id' in obj_dict:
                obj_dict['vendor_id'] = obj_dict.pop('address_book_id')
            return obj_dict
        elif isinstance(data, dict):
            # It's already a dict
            if 'address_book_id' in data and 'vendor_id' not in data:
                data['vendor_id'] = data.pop('address_book_id')
        return data

    class Config:
        from_attributes = True


class PurchaseOrderList(BaseModel):
    id: int
    po_number: str
    pr_number: Optional[str] = None
    status: str
    vendor_name: str
    total_amount: float
    currency: str
    order_date: Optional[date] = None
    expected_date: Optional[date] = None
    work_order_number: Optional[str] = None
    contract_number: Optional[str] = None
    created_by_name: str
    created_at: datetime
    line_count: int = 0
    invoices_linked: int = 0

    class Config:
        from_attributes = True


class POInvoiceLink(BaseModel):
    invoice_id: int
    notes: Optional[str] = None


class PurchaseOrderInvoice(BaseModel):
    id: int
    purchase_order_id: int
    invoice_id: int
    linked_by: int
    linked_at: datetime
    notes: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_vendor_name: Optional[str] = None
    invoice_total: Optional[float] = None

    class Config:
        from_attributes = True


class ConvertToPORequest(BaseModel):
    vendor_id: int
    order_date: Optional[date] = None
    expected_date: Optional[date] = None
    payment_terms: Optional[str] = None
    shipping_address: Optional[str] = None
    line_prices: Optional[dict] = None  # {pr_line_id: unit_price}


# =============================================================================
# TOOLS MANAGEMENT SCHEMAS
# =============================================================================

# Tool Category Schemas
class ToolCategoryBase(BaseModel):
    name: str
    code: Optional[str] = None
    asset_type: str  # "fixed_asset" or "consumable"
    useful_life_months: Optional[int] = None
    depreciation_method: Optional[str] = None
    salvage_value_percentage: Optional[float] = None
    asset_account_id: Optional[int] = None
    expense_account_id: Optional[int] = None
    accumulated_depreciation_account_id: Optional[int] = None
    depreciation_expense_account_id: Optional[int] = None
    description: Optional[str] = None
    is_active: bool = True


class ToolCategoryCreate(ToolCategoryBase):
    pass


class ToolCategoryUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    asset_type: Optional[str] = None
    useful_life_months: Optional[int] = None
    depreciation_method: Optional[str] = None
    salvage_value_percentage: Optional[float] = None
    asset_account_id: Optional[int] = None
    expense_account_id: Optional[int] = None
    accumulated_depreciation_account_id: Optional[int] = None
    depreciation_expense_account_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ToolCategory(ToolCategoryBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ToolCategoryList(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    asset_type: str
    useful_life_months: Optional[int] = None
    is_active: bool
    tool_count: int = 0

    class Config:
        from_attributes = True


# Tool Schemas
class ToolBase(BaseModel):
    category_id: int
    name: str
    serial_number: Optional[str] = None
    barcode: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    specifications: Optional[str] = None
    photo_url: Optional[str] = None
    warranty_expiry: Optional[date] = None
    warranty_notes: Optional[str] = None
    useful_life_months: Optional[int] = None
    salvage_value: Optional[float] = None
    notes: Optional[str] = None


class ToolCreate(ToolBase):
    # Initial assignment (optional, only one can be set)
    assigned_site_id: Optional[int] = None
    assigned_technician_id: Optional[int] = None
    assigned_warehouse_id: Optional[int] = None


class ToolUpdate(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = None
    serial_number: Optional[str] = None
    barcode: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    specifications: Optional[str] = None
    photo_url: Optional[str] = None
    warranty_expiry: Optional[date] = None
    warranty_notes: Optional[str] = None
    useful_life_months: Optional[int] = None
    salvage_value: Optional[float] = None
    status: Optional[str] = None
    condition: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ToolAllocation(BaseModel):
    """Schema for assigning/transferring a tool"""
    assigned_site_id: Optional[int] = None
    assigned_technician_id: Optional[int] = None
    assigned_warehouse_id: Optional[int] = None
    reason: Optional[str] = None
    notes: Optional[str] = None


class Tool(ToolBase):
    id: int
    company_id: int
    tool_number: str
    purchase_id: Optional[int] = None
    purchase_date: Optional[date] = None
    purchase_cost: Optional[float] = None
    vendor_id: Optional[int] = None
    capitalization_date: Optional[date] = None
    accumulated_depreciation: float = 0
    net_book_value: Optional[float] = None
    last_depreciation_date: Optional[date] = None
    status: str
    condition: str
    assigned_site_id: Optional[int] = None
    assigned_technician_id: Optional[int] = None
    assigned_warehouse_id: Optional[int] = None
    assigned_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Nested names
    category_name: Optional[str] = None
    asset_type: Optional[str] = None
    assigned_site_name: Optional[str] = None
    assigned_technician_name: Optional[str] = None
    assigned_warehouse_name: Optional[str] = None
    vendor_name: Optional[str] = None

    class Config:
        from_attributes = True


class ToolList(BaseModel):
    id: int
    tool_number: str
    name: str
    category_id: int
    category_name: str
    asset_type: str
    serial_number: Optional[str] = None
    status: str
    condition: str
    assigned_to: Optional[str] = None  # "Site: ABC" or "Technician: John" or "Warehouse: Main"
    purchase_cost: Optional[float] = None
    net_book_value: Optional[float] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# Tool Purchase Line Schemas
class ToolPurchaseLineBase(BaseModel):
    category_id: int
    description: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    quantity: int = 1
    unit_cost: float
    serial_numbers: Optional[str] = None
    notes: Optional[str] = None


class ToolPurchaseLineCreate(ToolPurchaseLineBase):
    pass


class ToolPurchaseLineUpdate(BaseModel):
    category_id: Optional[int] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    quantity: Optional[int] = None
    unit_cost: Optional[float] = None
    serial_numbers: Optional[str] = None
    notes: Optional[str] = None


class ToolPurchaseLine(ToolPurchaseLineBase):
    id: int
    purchase_id: int
    line_number: int
    total_cost: float
    category_name: Optional[str] = None
    category_asset_type: Optional[str] = None

    class Config:
        from_attributes = True


# Tool Purchase Schemas
class ToolPurchaseBase(BaseModel):
    vendor_id: int
    purchase_date: Optional[date] = None
    currency: str = "USD"
    initial_warehouse_id: Optional[int] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class ToolPurchaseCreate(ToolPurchaseBase):
    lines: List[ToolPurchaseLineCreate] = []


class ToolPurchaseUpdate(BaseModel):
    vendor_id: Optional[int] = None
    purchase_date: Optional[date] = None
    currency: Optional[str] = None
    initial_warehouse_id: Optional[int] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class ToolPurchase(ToolPurchaseBase):
    id: int
    company_id: int
    purchase_number: str
    subtotal: float
    tax_amount: float
    total_amount: float
    status: str
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    received_by: Optional[int] = None
    received_at: Optional[datetime] = None
    journal_entry_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Nested
    vendor_name: Optional[str] = None
    initial_warehouse_name: Optional[str] = None
    lines: List[ToolPurchaseLine] = []

    class Config:
        from_attributes = True


class ToolPurchaseList(BaseModel):
    id: int
    purchase_number: str
    purchase_date: date
    vendor_id: int
    vendor_name: str
    total_amount: float
    currency: str
    status: str
    line_count: int = 0
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Tool Allocation History Schema
class ToolAllocationHistoryItem(BaseModel):
    id: int
    tool_id: int
    transfer_date: datetime
    from_location: Optional[str] = None  # "Site: X" or "Technician: Y" or "Warehouse: Z"
    to_location: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    transferred_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Depreciation Schemas
class DepreciationPreview(BaseModel):
    tool_id: int
    tool_number: str
    tool_name: str
    purchase_cost: float
    accumulated_depreciation: float
    net_book_value: float
    monthly_depreciation: float
    depreciation_this_run: float


class DepreciationRunRequest(BaseModel):
    run_date: Optional[date] = None  # Defaults to today


class DepreciationRunResult(BaseModel):
    run_date: date
    tools_processed: int
    total_depreciation: float
    journal_entry_id: Optional[int] = None
    journal_entry_number: Optional[str] = None
    details: List[DepreciationPreview] = []


# ============================================================================
# DISPOSAL SCHEMAS - Asset & Inventory Write-off/Destruction
# ============================================================================

# Disposal enums as Literals
DisposalReason = Literal["damaged", "obsolete", "lost", "stolen", "sold", "scrapped", "donated"]
DisposalMethod = Literal["scrap", "sale", "donation", "return_to_vendor", "destroy"]
DisposalStatus = Literal["draft", "approved", "posted", "cancelled"]


# Disposal Tool Line Schemas
class DisposalToolLineCreate(BaseModel):
    tool_id: int
    salvage_value: float = 0
    notes: Optional[str] = None


class DisposalToolLineUpdate(BaseModel):
    salvage_value: Optional[float] = None
    notes: Optional[str] = None


class DisposalToolLine(BaseModel):
    id: int
    line_number: int
    tool_id: int
    tool_number: Optional[str] = None
    tool_name: Optional[str] = None
    original_cost: float
    accumulated_depreciation: float
    net_book_value: float
    salvage_value: float
    gain_loss: float
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# Disposal Item Line Schemas
class DisposalItemLineCreate(BaseModel):
    item_id: int
    warehouse_id: int
    quantity: float
    salvage_value: float = 0
    notes: Optional[str] = None


class DisposalItemLineUpdate(BaseModel):
    quantity: Optional[float] = None
    salvage_value: Optional[float] = None
    notes: Optional[str] = None


class DisposalItemLine(BaseModel):
    id: int
    line_number: int
    item_id: int
    item_number: Optional[str] = None
    item_name: Optional[str] = None
    warehouse_id: int
    warehouse_name: Optional[str] = None
    quantity: float
    unit_cost: float
    total_cost: float
    salvage_value: float
    gain_loss: float
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# Disposal Header Schemas
class DisposalBase(BaseModel):
    disposal_date: date
    reason: str
    method: Optional[str] = None
    salvage_received: float = 0
    salvage_reference: Optional[str] = None
    notes: Optional[str] = None


class DisposalCreate(DisposalBase):
    tool_lines: List[DisposalToolLineCreate] = []
    item_lines: List[DisposalItemLineCreate] = []


class DisposalUpdate(BaseModel):
    disposal_date: Optional[date] = None
    reason: Optional[str] = None
    method: Optional[str] = None
    salvage_received: Optional[float] = None
    salvage_reference: Optional[str] = None
    notes: Optional[str] = None


class Disposal(DisposalBase):
    id: int
    company_id: int
    disposal_number: str
    status: str
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    posted_by: Optional[int] = None
    posted_at: Optional[datetime] = None
    journal_entry_id: Optional[int] = None
    journal_entry_number: Optional[str] = None
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Nested lines
    tool_lines: List[DisposalToolLine] = []
    item_lines: List[DisposalItemLine] = []
    # Computed totals
    total_tool_value: float = 0
    total_tool_nbv: float = 0
    total_item_value: float = 0
    total_gain_loss: float = 0
    tool_count: int = 0
    item_count: int = 0

    class Config:
        from_attributes = True


class DisposalList(BaseModel):
    id: int
    disposal_number: str
    disposal_date: date
    reason: str
    method: Optional[str] = None
    status: str
    salvage_received: float
    tool_count: int = 0
    item_count: int = 0
    total_value: float = 0
    total_gain_loss: float = 0
    created_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Available items for disposal
class AvailableToolForDisposal(BaseModel):
    id: int
    tool_number: str
    name: str
    serial_number: Optional[str] = None
    category_name: str
    asset_type: str
    purchase_cost: float
    accumulated_depreciation: float
    net_book_value: float
    status: str
    current_location: Optional[str] = None

    class Config:
        from_attributes = True


class AvailableItemForDisposal(BaseModel):
    item_id: int
    item_number: str
    item_name: str
    warehouse_id: int
    warehouse_name: str
    quantity_on_hand: float
    average_cost: float
    total_value: float

    class Config:
        from_attributes = True


# =============================================================================
# Business Unit Schemas (JD Edwards concept)
# =============================================================================

class BusinessUnitBase(BaseModel):
    """Base schema for Business Unit - the smallest accounting unit in the ERP"""
    code: str  # 12-char alphanumeric identifier
    name: str
    description: Optional[str] = None

    # Hierarchy
    parent_id: Optional[int] = None
    level_of_detail: int = 1  # 1-9 for hierarchy depth

    # Type classification
    bu_type: Literal["balance_sheet", "profit_loss"] = "profit_loss"

    # Model/Consolidated flag
    model_flag: Literal["", "M", "C", "1"] = ""  # "", M=Model, C=Consolidated, 1=Target

    # Posting control
    posting_edit: Literal["", "K", "N", "P"] = ""  # "", K=Budget locked, N=No posting, P=Purge
    is_adjustment_only: bool = False

    # Status
    is_active: bool = True

    # Subsequent BU (for closed BUs)
    subsequent_bu_id: Optional[int] = None

    # Address/Location info
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    # Category codes (up to 10)
    category_code_01: Optional[str] = None
    category_code_02: Optional[str] = None
    category_code_03: Optional[str] = None
    category_code_04: Optional[str] = None
    category_code_05: Optional[str] = None
    category_code_06: Optional[str] = None
    category_code_07: Optional[str] = None
    category_code_08: Optional[str] = None
    category_code_09: Optional[str] = None
    category_code_10: Optional[str] = None


class BusinessUnitCreate(BusinessUnitBase):
    """Schema for creating a new Business Unit"""
    pass


class BusinessUnitUpdate(BaseModel):
    """Schema for updating a Business Unit"""
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None
    level_of_detail: Optional[int] = None
    bu_type: Optional[Literal["balance_sheet", "profit_loss"]] = None
    model_flag: Optional[Literal["", "M", "C", "1"]] = None
    posting_edit: Optional[Literal["", "K", "N", "P"]] = None
    is_adjustment_only: Optional[bool] = None
    is_active: Optional[bool] = None
    subsequent_bu_id: Optional[int] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    category_code_01: Optional[str] = None
    category_code_02: Optional[str] = None
    category_code_03: Optional[str] = None
    category_code_04: Optional[str] = None
    category_code_05: Optional[str] = None
    category_code_06: Optional[str] = None
    category_code_07: Optional[str] = None
    category_code_08: Optional[str] = None
    category_code_09: Optional[str] = None
    category_code_10: Optional[str] = None


class BusinessUnitBrief(BaseModel):
    """Brief Business Unit info for dropdowns and references"""
    id: int
    code: str
    name: str
    bu_type: str
    is_active: bool

    class Config:
        from_attributes = True


class BusinessUnit(BusinessUnitBase):
    """Full Business Unit schema with all fields"""
    id: int
    company_id: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BusinessUnitWithChildren(BusinessUnit):
    """Business Unit with nested children for hierarchy display"""
    children: List["BusinessUnitWithChildren"] = []
    parent_name: Optional[str] = None
    warehouse_count: int = 0  # Number of warehouses linked to this BU

    class Config:
        from_attributes = True


class BusinessUnitHierarchy(BaseModel):
    """Full hierarchy tree for a company"""
    company_id: int
    total_business_units: int
    balance_sheet_units: List[BusinessUnitWithChildren] = []
    profit_loss_units: List[BusinessUnitWithChildren] = []


class BusinessUnitLedgerEntry(BaseModel):
    """Ledger entry for Business Unit report"""
    entry_date: date
    entry_number: str
    account_code: str
    account_name: str
    description: Optional[str] = None
    debit: float
    credit: float
    source_type: Optional[str] = None
    source_number: Optional[str] = None


class BusinessUnitLedgerReport(BaseModel):
    """Business Unit Ledger Report"""
    business_unit_id: int
    business_unit_code: str
    business_unit_name: str
    bu_type: str
    start_date: date
    end_date: date
    opening_balance: float
    total_debits: float
    total_credits: float
    closing_balance: float
    entries: List[BusinessUnitLedgerEntry] = []


class BusinessUnitSummary(BaseModel):
    """Summary info for a Business Unit"""
    id: int
    code: str
    name: str
    bu_type: str
    total_debits: float
    total_credits: float
    net_balance: float
    warehouse_count: int
    transaction_count: int


# ============================================================================
# Address Book Schemas (Oracle JDE F0101/F0111 equivalent)
# ============================================================================

# Type literals for validation
AddressBookSearchType = Literal["V", "C", "CB", "E", "MT"]
ContactType = Literal["primary", "billing", "shipping", "technical", "management", "emergency", "other"]


class AddressBookContactBase(BaseModel):
    """Base schema for Address Book Contact (Who's Who)"""
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    contact_type: ContactType = "primary"
    phone_primary: Optional[str] = None
    phone_mobile: Optional[str] = None
    phone_fax: Optional[str] = None
    email: Optional[EmailStr] = None
    preferred_contact_method: Optional[str] = None
    language: Optional[str] = None
    is_primary: bool = False
    is_active: bool = True
    notes: Optional[str] = None


class AddressBookContactCreate(AddressBookContactBase):
    """Create schema for Address Book Contact"""
    pass


class AddressBookContactUpdate(BaseModel):
    """Update schema for Address Book Contact - all fields optional"""
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    contact_type: Optional[ContactType] = None
    phone_primary: Optional[str] = None
    phone_mobile: Optional[str] = None
    phone_fax: Optional[str] = None
    email: Optional[EmailStr] = None
    preferred_contact_method: Optional[str] = None
    language: Optional[str] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class AddressBookContact(AddressBookContactBase):
    """Full Address Book Contact response schema"""
    id: int
    address_book_id: int
    line_number: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AddressBookBase(BaseModel):
    """Base schema for Address Book entry"""
    search_type: AddressBookSearchType
    alpha_name: str
    mailing_name: Optional[str] = None
    tax_id: Optional[str] = None
    registration_number: Optional[str] = None

    # Address
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    address_line_3: Optional[str] = None
    address_line_4: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    # Communication
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None

    # Location (GPS)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Hierarchy
    parent_address_book_id: Optional[int] = None

    # Category Codes
    category_code_01: Optional[str] = None
    category_code_02: Optional[str] = None
    category_code_03: Optional[str] = None
    category_code_04: Optional[str] = None
    category_code_05: Optional[str] = None
    category_code_06: Optional[str] = None
    category_code_07: Optional[str] = None
    category_code_08: Optional[str] = None
    category_code_09: Optional[str] = None
    category_code_10: Optional[str] = None

    # Employee Salary Fields (only for search_type='E')
    salary_type: Optional[str] = None  # monthly, hourly, daily
    base_salary: Optional[Decimal] = None
    salary_currency: Optional[str] = "USD"
    hourly_rate: Optional[Decimal] = None
    overtime_rate_multiplier: Optional[Decimal] = Field(default=Decimal("1.5"))
    working_hours_per_day: Optional[Decimal] = Field(default=Decimal("8.0"))
    working_days_per_month: Optional[int] = 22

    # Allowances
    transport_allowance: Optional[Decimal] = None
    housing_allowance: Optional[Decimal] = None
    food_allowance: Optional[Decimal] = None
    other_allowances: Optional[Decimal] = None
    allowances_notes: Optional[str] = None

    # Deductions
    social_security_rate: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    other_deductions: Optional[Decimal] = None
    deductions_notes: Optional[str] = None

    # Employee-specific fields
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    hire_date: Optional[date] = None
    termination_date: Optional[date] = None

    # Other
    notes: Optional[str] = None
    is_active: bool = True


class AddressBookCreate(AddressBookBase):
    """Create schema - address_number can be auto-generated"""
    address_number: Optional[str] = None  # If None, auto-generate
    auto_create_bu: bool = True  # Auto-create linked Business Unit
    contacts: Optional[List[AddressBookContactCreate]] = []


class AddressBookUpdate(BaseModel):
    """Update schema - all fields optional"""
    alpha_name: Optional[str] = None
    mailing_name: Optional[str] = None
    tax_id: Optional[str] = None
    registration_number: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    address_line_3: Optional[str] = None
    address_line_4: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[EmailStr] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    parent_address_book_id: Optional[int] = None
    business_unit_id: Optional[int] = None
    category_code_01: Optional[str] = None
    category_code_02: Optional[str] = None
    category_code_03: Optional[str] = None
    category_code_04: Optional[str] = None
    category_code_05: Optional[str] = None
    category_code_06: Optional[str] = None
    category_code_07: Optional[str] = None
    category_code_08: Optional[str] = None
    category_code_09: Optional[str] = None
    category_code_10: Optional[str] = None

    # Employee Salary Fields (only for search_type='E')
    salary_type: Optional[str] = None
    base_salary: Optional[Decimal] = None
    salary_currency: Optional[str] = None
    hourly_rate: Optional[Decimal] = None
    overtime_rate_multiplier: Optional[Decimal] = None
    working_hours_per_day: Optional[Decimal] = None
    working_days_per_month: Optional[int] = None

    # Allowances
    transport_allowance: Optional[Decimal] = None
    housing_allowance: Optional[Decimal] = None
    food_allowance: Optional[Decimal] = None
    other_allowances: Optional[Decimal] = None
    allowances_notes: Optional[str] = None

    # Deductions
    social_security_rate: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    other_deductions: Optional[Decimal] = None
    deductions_notes: Optional[str] = None

    # Employee-specific fields
    employee_id: Optional[str] = None
    specialization: Optional[str] = None
    hire_date: Optional[date] = None
    termination_date: Optional[date] = None

    notes: Optional[str] = None
    is_active: Optional[bool] = None


class AddressBookBrief(BaseModel):
    """Brief schema for dropdowns and quick references"""
    id: int
    address_number: str
    search_type: str
    alpha_name: str
    city: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class AddressBookResponse(AddressBookBase):
    """Full Address Book response schema"""
    id: int
    company_id: int
    address_number: str
    business_unit_id: Optional[int] = None
    legacy_vendor_id: Optional[int] = None
    legacy_client_id: Optional[int] = None
    legacy_site_id: Optional[int] = None
    legacy_technician_id: Optional[int] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Nested
    contacts: List[AddressBookContact] = []
    parent_name: Optional[str] = None  # Parent's alpha_name
    business_unit_code: Optional[str] = None

    # Calculated salary fields (for convenience)
    total_allowances: Optional[Decimal] = None
    total_deductions: Optional[Decimal] = None
    net_salary: Optional[Decimal] = None

    class Config:
        from_attributes = True


class AddressBookWithChildren(AddressBookResponse):
    """Address Book with nested children for hierarchy display"""
    children: List["AddressBookWithChildren"] = []

    class Config:
        from_attributes = True


class AddressBookHierarchy(BaseModel):
    """Hierarchical view of Address Book entries grouped by type"""
    vendors: List[AddressBookWithChildren] = []
    customers: List[AddressBookWithChildren] = []
    branches: List[AddressBookWithChildren] = []
    employees: List[AddressBookWithChildren] = []
    teams: List[AddressBookWithChildren] = []


class AddressBookList(BaseModel):
    """Paginated list response"""
    entries: List[AddressBookResponse]
    total: int
    page: int
    size: int
