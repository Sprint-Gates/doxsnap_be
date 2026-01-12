"""
Permissions Seed Utility

Automatically populates the permissions table from a static
(module, action) dictionary.

Permissions are global system vocabulary and are NOT company-specific.
Admins can later assign these permissions to roles.
"""

import logging
from sqlalchemy.orm import Session

from app.models import Permission

logger = logging.getLogger(__name__)

# =============================================================================
# PERMISSIONS DICTIONARY
# =============================================================================
# Single source of truth for all system permissions.
# DO NOT rename existing module/action pairs once deployed.
# Add new permissions instead.
# =============================================================================
PERMISSIONS_DICTIONARY = {
    # =============================================================================
    # AUTHENTICATION & USER MANAGEMENT
    # =============================================================================
    # Note: "auth" and "otp" modules are public (in PUBLIC_PATHS) - no permissions needed

    "users": {
        "view": "View users",
        "create": "Create users",
        "update": "Edit users",
        "delete": "Delete users",
        "reset_password": "Reset user password",
    },

    # =============================================================================
    # COMPANY & ORGANIZATION
    # =============================================================================
    "companies": {
        "view": "View companies",
        "create": "Create companies",
        "update": "Edit companies",
        "delete": "Delete companies",
        "upload_logo": "Upload company logo",
    },

    "branches": {
        "view": "View branches",
        "create": "Create branches",
        "update": "Edit branches",
        "delete": "Delete branches",
        "toggle_status": "Toggle branch status",
    },

    "business_units": {
        "view": "View business units",
        "create": "Create business units",
        "update": "Edit business units",
        "delete": "Delete business units",
        "link_warehouse": "Link warehouse to business unit",
        "unlink_warehouse": "Unlink warehouse from business unit",
    },

    # =============================================================================
    # CLIENTS & SITES
    # =============================================================================
    "clients": {
        "view": "View clients",
        "create": "Create clients",
        "update": "Edit clients",
        "delete": "Delete clients",
        "toggle_status": "Toggle client status",
    },

    "sites": {
        "view": "View sites",
        "create": "Create sites",
        "update": "Edit sites",
        "delete": "Delete sites",
    },

    # =============================================================================
    # PROJECTS & CONTRACTS
    # =============================================================================
    "projects": {
        "view": "View projects",
        "create": "Create projects",
        "update": "Edit projects",
        "delete": "Archive projects",
        "link_invoice": "Link invoices to projects",
        "unlink_invoice": "Unlink invoices from projects",
    },

    "contracts": {
        "view": "View contracts",
        "create": "Create contracts",
        "update": "Edit contracts",
        "delete": "Delete contracts",
        "activate": "Activate draft contracts",
        "terminate": "Terminate contracts",
        "renew": "Renew contracts",
        "seed": "seed scopes",
    },

    # =============================================================================
    # ASSETS & EQUIPMENT
    # =============================================================================
    "assets": {
        "view": "View assets",
        "create": "Create assets",
        "update": "Edit assets",
        "delete": "Delete assets",
        "bulk_import": "Bulk import assets",
    },

    "equipment": {
        "view": "View equipment",
        "create": "Create equipment",
        "update": "Edit equipment",
        "delete": "Delete equipment",
    },

    "condition_reports": {
        "view": "View condition reports",
        "create": "Create condition reports",
        "update": "Edit condition reports",
        "delete": "Delete condition reports",
    },

    # =============================================================================
    # TECHNICIANS & PERSONNEL
    # =============================================================================
    "technicians": {
        "view": "View technicians",
        "create": "Create technicians",
        "update": "Edit technicians",
        "delete": "Delete technicians",
        "toggle_status": "Toggle technician status",
    },

    "operators": {
        "view": "View operators",
        "create": "Create operators",
        "update": "Edit operators",
        "delete": "Delete operators",
        "toggle_status": "Toggle operator status",
    },

    "technician-evaluations": {
        "view": "View technician evaluations",
        "create": "Create technician evaluations",
        "update": "Edit technician evaluations",
        "delete": "Delete technician evaluations",
        "submit": "Submit technician evaluations",
        "acknowledge": "Acknowledge technician evaluations",
        "finalize": "Finalize technician evaluations",
    },

    "shifts": {
        "view": "View technician shifts",
        "create": "Create technician shifts",
        "update": "Edit technician shifts",
        "delete": "Delete technician shifts",
    },

    "attendance": {
        "view": "View attendance records",
        "create": "Create attendance records",
        "update": "Edit attendance records",
        "delete": "Delete attendance records",
        "approve": "Approve leave requests",
    },

    # =============================================================================
    # WORK ORDERS & MAINTENANCE
    # =============================================================================
    "work_orders": {
        "view": "View work orders",
        "create": "Create work orders",
        "update": "Edit work orders",
        "delete": "Delete work orders",
        "approve": "Approve work orders",
        "cancel": "Cancel work orders",
        "issue_item": "Issue items to work orders",
        "return_item": "Return items from work orders",
    },

    "pm_work_orders": {
        "view": "View PM work orders",
        "generate": "Generate PM work orders",
        "complete": "Complete PM work orders",
    },

    "pm": {
        "view": "View PM checklists",
        "create": "Create PM checklists",
        "update": "Edit PM checklists",
        "delete": "Delete PM checklists",
        "seed": "Seed PM checklists",
    },

    "calendar": {
        "view": "View calendar",
        "create": "Create calendar slots",
        "update": "Edit calendar slots",
        "delete": "Delete calendar slots",
        "assign": "Assign work orders to slots",
        "unassign": "Unassign work orders from slots",
        "generate": "Generate calendar slots",
    },

    # =============================================================================
    # TICKETS & SERVICE REQUESTS
    # =============================================================================
    "tickets": {
        "view": "View tickets",
        "create": "Create tickets",
        "update": "Edit tickets",
        "delete": "Delete tickets",
        "convert": "Convert tickets to work orders",
        "cancel": "Cancel tickets",
    },

    # =============================================================================
    # INVENTORY & WAREHOUSES
    # =============================================================================
    "warehouses": {
        "view": "View warehouses",
        "create": "Create warehouses",
        "update": "Edit warehouses",
        "delete": "Delete warehouses",
        "toggle_status": "Toggle warehouse status",
        "set_main": "Set main warehouse",
    },

    "item_master": {
        "view": "View items",
        "create": "Create items",
        "update": "Edit items",
        "delete": "Delete items",
        "adjust_stock": "Adjust item stock",
        "transfer": "Transfer items between locations",
        "bulk_import": "Bulk import items",
    },

    "cycle-counts": {
        "view": "View cycle counts",
        "create": "Create cycle counts",
        "update": "Edit cycle counts",
        "delete": "Delete cycle counts",
        "complete": "Complete cycle counts",
        "cancel": "Cancel cycle counts",
    },

    "tools": {
        "view": "View tools",
        "create": "Create tools",
        "update": "Edit tools",
        "delete": "Delete tools",
        "allocate": "Allocate tools",
        "calculate_depreciation": "Calculate tool depreciation",
    },

    "disposals": {
        "view": "View disposals",
        "create": "Create disposals",
        "update": "Edit disposals",
        "delete": "Delete disposals",
        "approve": "Approve disposals",
        "post": "Post disposals",
        "cancel": "Cancel disposals",
    },

    # =============================================================================
    # PROCUREMENT
    # =============================================================================
    "purchase-requests": {
        "view": "View purchase requests",
        "create": "Create purchase requests",
        "update": "Edit purchase requests",
        "delete": "Delete purchase requests",
        "submit": "Submit purchase requests",
        "approve": "Approve purchase requests",
        "reject": "Reject purchase requests",
        "convert_to_po": "Convert to purchase order",
        "cancel": "Cancel purchase requests",
    },

    "purchase-orders": {
        "view": "View purchase orders",
        "create": "Create purchase orders",
        "update": "Edit purchase orders",
        "delete": "Delete purchase orders",
        "send": "Send purchase orders",
        "acknowledge": "Acknowledge purchase orders",
        "receive": "Receive purchase orders",
        "cancel": "Cancel purchase orders",
        "reverse": "Reverse purchase orders",
        "link_invoice": "Link invoice to purchase order",
    },

    "goods-receipts": {
        "view": "View goods receipts",
        "create": "Create goods receipts",
        "update": "Edit goods receipts",
        "delete": "Delete goods receipts",
        "post": "Post goods receipts",
        "inspect": "Inspect goods receipts",
        "reverse": "Reverse goods receipts",
        "three_way_match": "Perform three-way match",
    },

    "supplier-invoices": {
        "view": "View supplier invoices",
        "create": "Create supplier invoices",
        "delete": "Delete supplier invoices",
        "match": "Match supplier invoices",
        "approve": "Approve supplier invoices",
        "submit": "Submit supplier invoices",
        "hold": "Hold supplier invoices",
        "three_way_match": "Perform three-way match",
        "clear_grni": "Clear GRNI",
    },

    "supplier_payments": {
        "view": "View supplier payments",
        "create": "Create supplier payments",
        "delete": "Delete supplier payments",
        "approve": "Approve supplier payments",
        "post": "Post supplier payments",
        "void": "Void supplier payments",
    },

    # =============================================================================
    # ADDRESS BOOK & CONTACTS
    # =============================================================================
    "address-book": {
        "view": "View address book",
        "create": "Create address book entries",
        "update": "Edit address book entries",
        "delete": "Delete address book entries",
        "toggle_status": "Toggle address book status",
        "lookup": "Lookup address book entries",
    },

    # =============================================================================
    # ACCOUNTING & FINANCE
    # =============================================================================
    "accounting": {
        "view": "View accounting data",
        "create": "Create accounting entries",
        "update": "Edit accounting entries",
        "delete": "Delete accounting entries",
        "post": "Post journal entries",
        "reverse": "Reverse journal entries",
        "initialize": "Initialize chart of accounts",
        "recompute_balances": "Recompute account balances",
    },

    "petty-cash": {
        "view": "View petty cash",
        "create": "Create petty cash transactions",
        "update": "Edit petty cash transactions",
        "delete": "Delete petty cash transactions",
        "approve": "Approve petty cash transactions",
        "reject": "Reject petty cash transactions",
        "reverse": "Reverse petty cash transactions",
        "replenish": "Replenish petty cash",
    },

    "allocations": {
        "view": "View invoice allocations",
        "create": "Create invoice allocations",
        "update": "Edit invoice allocations",
        "delete": "Delete invoice allocations",
        "cancel": "Cancel invoice allocations",
        "recognize": "Recognize allocation periods",
        "unrecognize": "Unrecognize allocation periods",
    },

    "exchange_rates": {
        "view": "View exchange rates",
        "create": "Create manual exchange rates",
        "delete": "Delete manual exchange rates",
        "convert": "Convert currencies",
    },

    # =============================================================================
    # CRM
    # =============================================================================
    "crm": {
        "view": "View CRM leads",
        "create": "Create CRM leads",
        "update": "Edit CRM leads",
        "delete": "Delete CRM leads",
        "convert": "Convert CRM leads",
    },

    "crm_opportunities": {
        "view": "View CRM opportunities",
        "create": "Create CRM opportunities",
        "update": "Edit CRM opportunities",
        "delete": "Delete CRM opportunities",
        "close": "Close CRM opportunities",
    },

    "crm_activities": {
        "view": "View CRM activities",
        "create": "Create CRM activities",
        "update": "Edit CRM activities",
        "delete": "Delete CRM activities",
        "complete": "Complete CRM activities",
        "cancel": "Cancel CRM activities",
    },

    "crm_campaigns": {
        "view": "View CRM campaigns",
        "create": "Create CRM campaigns",
        "update": "Edit CRM campaigns",
        "delete": "Delete CRM campaigns",
    },

    # =============================================================================
    # FLEET MANAGEMENT
    # =============================================================================
    "fleet": {
        "view": "View fleet vehicles",
        "create": "Create fleet vehicles",
        "update": "Edit fleet vehicles",
        "delete": "Delete fleet vehicles",
    },

    # =============================================================================
    # HANDHELD DEVICES
    # =============================================================================
    "handheld-devices": {
        "view": "View handheld devices",
        "create": "Create handheld devices",
        "update": "Edit handheld devices",
        "delete": "Delete handheld devices",
        "assign": "Assign handheld devices",
        "toggle_status": "Toggle device status",
    },

    # =============================================================================
    # DOCUMENT MANAGEMENT
    # =============================================================================
    "images": {
        "view": "View images",
        "create": "Create images",
        "update": "Edit images",
        "delete": "Delete images",
        "upload": "Upload images",
        "link_vendor": "Link vendor to image",
        "send_email": "Send image via email",
    },

    "document_types": {
        "view": "View document types",
        "create": "Create document types",
        "update": "Edit document types",
        "delete": "Delete document types",
        "seed": "Seed document types",
    },

    # =============================================================================
    # IMPORT/EXPORT
    # =============================================================================
    "import_export": {
        "import": "Import data",
        "export": "Export data",
        "download_template": "Download import template",
    },

    # =============================================================================
    # DASHBOARD & REPORTS
    # =============================================================================
    "dashboard": {
        "view": "View dashboard",
    },

    # =============================================================================
    # NPS (NET PROMOTER SCORE)
    # =============================================================================
    "nps": {
        "view": "View NPS surveys",
        "create": "Create NPS surveys",
        "update": "Edit NPS surveys",
        "delete": "Delete NPS surveys",
        "follow_up": "Follow up on NPS surveys",
    },
}

# =============================================================================
# SEED FUNCTION
# =============================================================================

def seed_permissions(db: Session):
    """
    Seed permissions from PERMISSIONS_DICTIONARY.

    This function is idempotent:
    - Existing permissions are not modified
    - Missing permissions are created
    - No permissions are deleted

    Args:
        db: SQLAlchemy database session
    """
    logger.info("Seeding permissions...")

    try:
        for module, actions in PERMISSIONS_DICTIONARY.items():
            for action in actions.keys():
                exists = (
                    db.query(Permission)
                    .filter_by(module=module, action=action)
                    .first()
                )
                if exists:
                    continue

                db.add(Permission(module=module, action=action))

        db.commit()
        logger.info("Permissions seeding completed successfully.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding permissions: {e}")
        raise
