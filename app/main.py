from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from datetime import datetime
import os
import logging
import google.generativeai as genai

from app.api import auth, images, otp, admin, document_types, technician_site_shifts, plans, companies, projects, operators, handheld_devices, assets, attendance, work_orders, warehouses, pm_checklists, pm_work_orders, dashboard, item_master, cycle_count, hhd_auth, users, sites, contracts, tickets, ticket_timeline, calendar, condition_reports, technician_evaluations, nps, petty_cash, docs, allocations, accounting, exchange_rates, purchase_requests, purchase_orders, goods_receipts, crm_leads, crm_opportunities, crm_activities, crm_campaigns, tools, disposals, business_units, address_book, supplier_invoices, supplier_payments, technicians, import_export, fleet, client_portal, client_admin, platform_admin, upgrade_requests, rfq, hhd_rfq
from app.database import engine, get_db
from app.models import Base, User, ProcessedImage, DocumentType, Warehouse, Plan, Company, Client, Project, Technician, HandHeldDevice, Floor, Room, Equipment, SubEquipment, TechnicianAttendance, SparePart, WorkOrder, WorkOrderSparePart, WorkOrderTimeEntry, PMSchedule, ItemCategory, ItemMaster, ItemStock, ItemLedger, ItemTransfer, ItemTransferLine, InvoiceItem, CycleCount, CycleCountItem, RefreshToken, Site, Building, Space, Scope, Contract, ContractScope, Ticket, CalendarSlot, WorkOrderSlotAssignment, CalendarTemplate, InvoiceAllocation, AllocationPeriod, RecognitionLog, AccountType, Account, FiscalPeriod, JournalEntry, JournalEntryLine, AccountBalance, DefaultAccountMapping, ExchangeRate, ExchangeRateLog, PurchaseRequest, PurchaseRequestLine, PurchaseOrder, PurchaseOrderLine, PurchaseOrderInvoice, GoodsReceipt, GoodsReceiptLine, LeadSource, PipelineStage, Lead, Opportunity, CRMActivity, Campaign, CampaignLead, ToolCategory, Tool, ToolPurchase, ToolPurchaseLine, ToolAllocationHistory, Disposal, DisposalToolLine, DisposalItemLine, BusinessUnit, AddressBook, AddressBookContact, SupplierInvoice, SupplierInvoiceLine, SupplierPayment, SupplierPaymentAllocation, DebitNote, DebitNoteLine, PurchaseOrderAmendment, Service, ClientUser, ClientRefreshToken, RFQ, RFQItem, RFQVendor, RFQQuote, RFQQuoteLine, RFQAuditTrail, RFQSiteVisit, RFQSiteVisitPhoto, RFQComparison, RFQDocument
from app.config import settings
from app.utils.security import verify_token
from app.utils.rate_limiter import limiter, rate_limit_exceeded_handler
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

# Run simple migrations for new columns
def run_migrations():
    """Add new columns to existing tables if they don't exist"""
    migrations = [
        # Add code column to clients table
        ("clients", "code", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS code VARCHAR"),
        # Add mobile_pin column to handheld_devices table
        ("handheld_devices", "mobile_pin", "ALTER TABLE handheld_devices ADD COLUMN IF NOT EXISTS mobile_pin VARCHAR"),
        # Add primary_currency column to companies table
        ("companies", "primary_currency", "ALTER TABLE companies ADD COLUMN IF NOT EXISTS primary_currency VARCHAR(3) DEFAULT 'USD'"),
        # Business Unit implementation (JD Edwards concept)
        ("warehouses", "business_unit_id", "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS business_unit_id INTEGER REFERENCES business_units(id)"),
        ("journal_entry_lines", "business_unit_id", "ALTER TABLE journal_entry_lines ADD COLUMN IF NOT EXISTS business_unit_id INTEGER REFERENCES business_units(id)"),
        ("account_balances", "business_unit_id", "ALTER TABLE account_balances ADD COLUMN IF NOT EXISTS business_unit_id INTEGER REFERENCES business_units(id)"),
        ("item_ledger", "business_unit_id", "ALTER TABLE item_ledger ADD COLUMN IF NOT EXISTS business_unit_id INTEGER REFERENCES business_units(id)"),
        # Address Book link for clients (master data management)
        ("clients", "address_book_id", "ALTER TABLE clients ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        # Address Book vendor references (replacing legacy vendor_id)
        ("processed_images", "address_book_id", "ALTER TABLE processed_images ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        ("purchase_requests", "address_book_id", "ALTER TABLE purchase_requests ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        ("purchase_orders", "address_book_id", "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        ("item_master", "primary_address_book_id", "ALTER TABLE item_master ADD COLUMN IF NOT EXISTS primary_address_book_id INTEGER REFERENCES address_book(id)"),
        ("item_aliases", "address_book_id", "ALTER TABLE item_aliases ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        ("tool_purchases", "address_book_id", "ALTER TABLE tool_purchases ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        ("tools", "vendor_address_book_id", "ALTER TABLE tools ADD COLUMN IF NOT EXISTS vendor_address_book_id INTEGER REFERENCES address_book(id)"),
        ("goods_receipt_extra_costs", "address_book_id", "ALTER TABLE goods_receipt_extra_costs ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        ("journal_entry_lines", "address_book_id", "ALTER TABLE journal_entry_lines ADD COLUMN IF NOT EXISTS address_book_id INTEGER REFERENCES address_book(id)"),
        # Petty cash vendor linking
        ("petty_cash_transactions", "vendor_address_book_id", "ALTER TABLE petty_cash_transactions ADD COLUMN IF NOT EXISTS vendor_address_book_id INTEGER REFERENCES address_book(id)"),
        # Make sites.client_id nullable (sites can now use address_book_id instead)
        ("sites", "client_id_nullable", "ALTER TABLE sites ALTER COLUMN client_id DROP NOT NULL"),
        # Migrate floors from branch_id to site_id (replacing Branch with Site for asset hierarchy)
        ("floors", "site_id", "ALTER TABLE floors ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id)"),
        # Make condition_reports.client_id nullable (can now use address_book_id instead)
        ("condition_reports", "client_id_nullable", "ALTER TABLE condition_reports ALTER COLUMN client_id DROP NOT NULL"),
        # Client Portal: Add source and client_user_id to tickets table
        ("tickets", "source", "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'admin_portal'"),
        ("tickets", "client_user_id", "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS client_user_id INTEGER REFERENCES client_users(id)"),
        ("tickets", "service_id", "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS service_id INTEGER REFERENCES services(id)"),
        # Client Portal: Make tickets.requested_by nullable (for client portal submissions)
        ("tickets", "requested_by_nullable", "ALTER TABLE tickets ALTER COLUMN requested_by DROP NOT NULL"),
        # FCM Push Notifications
        ("handheld_devices", "fcm_token", "ALTER TABLE handheld_devices ADD COLUMN IF NOT EXISTS fcm_token VARCHAR"),
        ("handheld_devices", "fcm_token_updated_at", "ALTER TABLE handheld_devices ADD COLUMN IF NOT EXISTS fcm_token_updated_at TIMESTAMP"),
        # Company code for mobile app login
        ("companies", "company_code", "ALTER TABLE companies ADD COLUMN IF NOT EXISTS company_code VARCHAR UNIQUE"),
    ]

    with engine.connect() as conn:
        for table, column, sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
                logger.info(f"Migration: Added {column} to {table}")
            except Exception as e:
                # Column might already exist or other error
                logger.debug(f"Migration skipped for {table}.{column}: {e}")

try:
    run_migrations()
except Exception as e:
    logger.warning(f"Migration runner error: {e}")

# Validate Google API Key on startup
def validate_google_api_key():
    """Validate Google API key by making a test request"""
    if not settings.google_api_key:
        logger.warning("GOOGLE_API_KEY is not configured. AI processing will be disabled.")
        return False

    try:
        genai.configure(api_key=settings.google_api_key)
        # Test the API key by listing models
        models = list(genai.list_models())
        if models:
            logger.info(f"Google API key validated successfully. {len(models)} models available.")
            return True
        else:
            logger.warning("Google API key configured but no models available.")
            return False
    except Exception as e:
        logger.error(f"Google API key validation failed: {e}")
        return False

google_api_valid = validate_google_api_key()

app = FastAPI(title="Image Processor API", version="1.0.0", redirect_slashes=False)

# Add rate limiter to app state and register exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# Subscription enforcement middleware
class SubscriptionEnforcementMiddleware(BaseHTTPMiddleware):
    """Middleware to enforce subscription/trial period for protected API routes."""

    # Routes that don't require subscription check (must be exact prefixes)
    EXEMPT_PATHS = [
        "/api/auth/",
        "/api/auth",
        "/api/plans",
        "/api/companies/register",
        "/api/health",
        "/api/otp",
        "/api/docs",
        "/api/platform-admin",  # Platform admin has its own auth
        "/uploads/",
        "/uploads",
        "/openapi.json",
        "/docs",
        "/redoc",
    ]

    # Exact match only paths (not prefix match)
    EXEMPT_EXACT = ["/", "/health"]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        logger.info(f"[SubscriptionMiddleware] Request: {request.method} {path}")

        # Check exact matches first
        if path in self.EXEMPT_EXACT:
            logger.info(f"[SubscriptionMiddleware] Exempt exact path, skipping: {path}")
            return await call_next(request)

        # Skip check for exempt path prefixes
        for exempt in self.EXEMPT_PATHS:
            if path.startswith(exempt):
                logger.info(f"[SubscriptionMiddleware] Exempt path prefix, skipping: {path}")
                return await call_next(request)

        logger.info(f"[SubscriptionMiddleware] Checking subscription for path: {path}")

        # Skip check for non-API routes
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Get authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.info(f"[SubscriptionMiddleware] No auth header, passing through")
            # Let the route handler deal with missing auth
            return await call_next(request)

        token = auth_header.split(" ")[1]
        email = verify_token(token)

        if not email:
            logger.info(f"[SubscriptionMiddleware] Invalid token, passing through")
            # Invalid token - let route handler deal with it
            return await call_next(request)

        logger.info(f"[SubscriptionMiddleware] Valid token for: {email}")

        # Check subscription status
        db = next(get_db())
        try:
            user = db.query(User).filter(User.email == email).first()
            if not user or not user.company_id:
                return await call_next(request)

            company = db.query(Company).filter(Company.id == user.company_id).first()
            if not company:
                return await call_next(request)

            # Check subscription status
            if company.subscription_status in ["cancelled", "suspended"]:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"Subscription has been {company.subscription_status}. Please contact support.",
                        "subscription_status": company.subscription_status
                    }
                )

            # Check if trial/subscription has expired
            if company.subscription_end and company.subscription_end < datetime.utcnow():
                logger.info(f"[SubscriptionMiddleware] Blocking expired user: {email}, company: {company.name}, status: {company.subscription_status}")
                if company.subscription_status == "trial":
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Your 5-day trial period has expired. Please upgrade to continue using the application.",
                            "subscription_status": "trial_expired"
                        }
                    )
                else:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Your subscription has expired. Please renew to continue.",
                            "subscription_status": "expired"
                        }
                    )
        finally:
            db.close()

        return await call_next(request)


# Add subscription enforcement middleware
app.add_middleware(SubscriptionEnforcementMiddleware)

# CORS middleware - must be added after all other middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:4201",
        "http://127.0.0.1:4200",
        "http://localhost:8100",
        "http://127.0.0.1:8100",
        "https://coresrp.com",
        "http://coresrp.com",
        "capacitor://localhost",  # iOS Capacitor
        "ionic://localhost",  # iOS Ionic
        "http://localhost",  # Android Capacitor
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Create uploads directory if it doesn't exist
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(images.router, prefix="/api/images", tags=["Images"])
app.include_router(otp.router, prefix="/api/otp", tags=["OTP"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])
app.include_router(document_types.router, prefix="/api/document-types", tags=["Document Types"])
# REMOVED: Vendor API - Use Address Book with search_type='V' instead
# app.include_router(vendors.router, prefix="/api/vendors", tags=["Vendors"])
app.include_router(plans.router, prefix="/api", tags=["Plans"])
app.include_router(companies.router, prefix="/api", tags=["Companies"])
# REMOVED: Branches API - Use Sites with Address Book instead
# app.include_router(branches.router, prefix="/api", tags=["Branches"])
app.include_router(projects.router, prefix="/api", tags=["Projects"])
app.include_router(operators.router, prefix="/api", tags=["Operators"])
app.include_router(handheld_devices.router, prefix="/api", tags=["HandHeld Devices"])
app.include_router(assets.router, prefix="/api/assets", tags=["Assets"])
app.include_router(attendance.router, prefix="/api", tags=["Attendance"])
app.include_router(work_orders.router, prefix="/api", tags=["Work Orders"])
app.include_router(warehouses.router, prefix="/api", tags=["Warehouses"])
app.include_router(pm_checklists.router, prefix="/api", tags=["PM Checklists"])
app.include_router(pm_work_orders.router, prefix="/api", tags=["PM Work Orders"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])
app.include_router(item_master.router, prefix="/api", tags=["Item Master"])
app.include_router(cycle_count.router, prefix="/api", tags=["Cycle Count"])
app.include_router(hhd_auth.router, prefix="/api", tags=["HHD Auth"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(sites.router, prefix="/api/sites", tags=["Sites"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["Contracts"])
app.include_router(tickets.router, prefix="/api", tags=["Tickets"])
app.include_router(ticket_timeline.router, prefix="/api", tags=["Ticket Timeline"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(technician_site_shifts.router, prefix="/api", tags=["Technicians Site Shifts"])
app.include_router(technicians.router, prefix="/api", tags=["Technicians"])
app.include_router(condition_reports.router, prefix="/api/condition-reports", tags=["Condition Reports"])
app.include_router(technician_evaluations.router, prefix="/api/technician-evaluations", tags=["Technician Evaluations"])
app.include_router(nps.router, prefix="/api/nps", tags=["Net Promoter Score"])
app.include_router(petty_cash.router, prefix="/api/petty-cash", tags=["Petty Cash"])
app.include_router(docs.router, prefix="/api/docs", tags=["Documentation"])
app.include_router(allocations.router, prefix="/api/allocations", tags=["Invoice Allocations"])
app.include_router(accounting.router, prefix="/api/accounting", tags=["Accounting"])
app.include_router(business_units.router, prefix="/api", tags=["Business Units"])
app.include_router(exchange_rates.router, prefix="/api", tags=["Exchange Rates"])
app.include_router(purchase_requests.router, prefix="/api/purchase-requests", tags=["Purchase Requests"])
app.include_router(purchase_orders.router, prefix="/api/purchase-orders", tags=["Purchase Orders"])
app.include_router(goods_receipts.router, prefix="/api/goods-receipts", tags=["Goods Receipts"])
app.include_router(rfq.router, prefix="/api/rfqs", tags=["RFQ - Request for Quotation"])

# Mobile HHD RFQ (Parts Requests for Technicians)
app.include_router(hhd_rfq.router, prefix="/api/hhd", tags=["HHD - Mobile Parts Requests"])

# CRM Routers
app.include_router(crm_leads.router, prefix="/api", tags=["CRM - Leads"])
app.include_router(crm_opportunities.router, prefix="/api", tags=["CRM - Opportunities"])
app.include_router(crm_activities.router, prefix="/api", tags=["CRM - Activities"])
app.include_router(crm_campaigns.router, prefix="/api", tags=["CRM - Campaigns"])

# Tools Management Router
app.include_router(tools.router, prefix="/api", tags=["Tools Management"])

# Disposals Router
app.include_router(disposals.router, prefix="/api", tags=["Disposals"])

# Address Book Router (Oracle JDE F0101 equivalent)
# NOTE: Clients are managed via Address Book with search_type='C' (Customer)
app.include_router(address_book.router, prefix="/api", tags=["Address Book"])

# REMOVED: Clients API - Use Address Book with search_type='C' instead
# app.include_router(clients.router, prefix="/api/clients", tags=["Clients"])

# Supplier Invoice & Payment Routers (Procure-to-Pay)
app.include_router(supplier_invoices.router, prefix="/api/supplier-invoices", tags=["Supplier Invoices"])
app.include_router(supplier_payments.router, prefix="/api/supplier-payments", tags=["Supplier Payments"])

# Import/Export Router
app.include_router(import_export.router, prefix="/api", tags=["Import Export"])

# Fleet Management Router
app.include_router(fleet.router, prefix="/api/fleet", tags=["Fleet Management"])

# Client Portal Routers
app.include_router(client_portal.router, prefix="/api", tags=["Client Portal"])
app.include_router(client_admin.router, prefix="/api", tags=["Client Admin"])

# Platform Admin Router (Super Admin for managing subscriptions)
app.include_router(platform_admin.router, prefix="/api", tags=["Platform Admin"])

# Upgrade Requests Router
app.include_router(upgrade_requests.router, prefix="/api", tags=["Upgrade Requests"])

@app.get("/")
async def root():
    return {
        "message": "Image Processor API is running",
        "google_api_enabled": google_api_valid
    }

@app.get("/api/health")
async def health_check():
    from app.services.cache import cache_service
    return {
        "status": "healthy",
        "services": {
            "google_ai": google_api_valid,
            "redis_cache": cache_service.is_connected
        }
    }


# Redis Cache Lifecycle Events
@app.on_event("startup")
async def startup_event():
    """Initialize Redis cache connection on app startup"""
    from app.services.cache import cache_service
    await cache_service.connect()


@app.on_event("shutdown")
async def shutdown_event():
    """Close Redis cache connection on app shutdown"""
    from app.services.cache import cache_service
    await cache_service.disconnect()