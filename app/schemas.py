from pydantic import BaseModel, EmailStr
from datetime import datetime, date
from typing import Optional, List


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
    site_id: Optional[int] = None
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
    site_id: Optional[int] = None
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


# Chart of Accounts initialization
class ChartOfAccountsInit(BaseModel):
    template: str = "default"  # default, property_management, service_company


# Auto-posting request
class AutoPostRequest(BaseModel):
    source_type: str  # invoice, work_order, petty_cash
    source_id: int
    post_immediately: bool = False
