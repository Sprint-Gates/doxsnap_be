from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging
import google.generativeai as genai

from app.api import auth, images, otp, admin, document_types, technician_site_shifts, vendors, plans, companies, clients, branches, projects, operators, technicians, handheld_devices, assets, attendance, work_orders, warehouses, pm_checklists, pm_work_orders, dashboard, item_master, cycle_count, dummy, hhd_auth, users, sites, contracts, tickets, calendar, condition_reports
from app.database import engine
from app.models import Base, User, ProcessedImage, DocumentType, Vendor, Warehouse, Plan, Company, Client, Branch, Project, Technician, HandHeldDevice, Floor, Room, Equipment, SubEquipment, TechnicianAttendance, SparePart, WorkOrder, WorkOrderSparePart, WorkOrderTimeEntry, PMSchedule, ItemCategory, ItemMaster, ItemStock, ItemLedger, ItemTransfer, ItemTransferLine, InvoiceItem, CycleCount, CycleCountItem, RefreshToken, Site, Building, Space, Scope, Contract, ContractScope, Ticket, CalendarSlot, WorkOrderSlotAssignment, CalendarTemplate
from app.config import settings
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

app = FastAPI(title="Image Processor API", version="1.0.0")

# CORS middleware - must be added after all other middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200","http://localhost:4201", "http://127.0.0.1:4200", "http://localhost:8100", "http://127.0.0.1:8100"],
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
app.include_router(vendors.router, prefix="/api/vendors", tags=["Vendors"])
app.include_router(plans.router, prefix="/api", tags=["Plans"])
app.include_router(companies.router, prefix="/api", tags=["Companies"])
app.include_router(clients.router, prefix="/api", tags=["Clients"])
app.include_router(branches.router, prefix="/api", tags=["Branches"])
app.include_router(projects.router, prefix="/api", tags=["Projects"])
app.include_router(operators.router, prefix="/api", tags=["Operators"])
app.include_router(technicians.router, prefix="/api", tags=["Technicians"])
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
app.include_router(dummy.router, prefix="/api", tags=["dummy"])
app.include_router(hhd_auth.router, prefix="/api", tags=["HHD Auth"])
app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(sites.router, prefix="/api/sites", tags=["Sites"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["Contracts"])
app.include_router(tickets.router, prefix="/api", tags=["Tickets"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["Calendar"])
app.include_router(technician_site_shifts.router, prefix="/api", tags=["Technicians Site Shifts"])
app.include_router(condition_reports.router, prefix="/api/condition-reports", tags=["Condition Reports"])

@app.get("/")
async def root():
    return {
        "message": "Image Processor API is running",
        "google_api_enabled": google_api_valid
    }

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "services": {
            "google_ai": google_api_valid
        }
    }