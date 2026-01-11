"""
Company Seed Utility

Automatically populates default data for a new company:
- Chart of Accounts (Account Types and Accounts)
- Main Warehouse
- Default Item Categories
"""

from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging

from app.models import (
    AccountType, Account, Warehouse, ItemCategory, Client, Site, Company,
    AddressBook, BusinessUnit, DefaultAccountMapping
)

logger = logging.getLogger(__name__)


# =============================================================================
# DEFAULT ACCOUNT TYPES
# =============================================================================

DEFAULT_ACCOUNT_TYPES = [
    {"code": "ASSET", "name": "Assets", "normal_balance": "debit", "display_order": 1},
    {"code": "LIABILITY", "name": "Liabilities", "normal_balance": "credit", "display_order": 2},
    {"code": "EQUITY", "name": "Equity", "normal_balance": "credit", "display_order": 3},
    {"code": "REVENUE", "name": "Revenue", "normal_balance": "credit", "display_order": 4},
    {"code": "EXPENSE", "name": "Expenses", "normal_balance": "debit", "display_order": 5},
]


# =============================================================================
# DEFAULT CHART OF ACCOUNTS
# =============================================================================

DEFAULT_ACCOUNTS = [
    # Assets (1xxx)
    {"code": "1000", "name": "Assets", "type_code": "ASSET", "is_header": True},
    {"code": "1100", "name": "Current Assets", "type_code": "ASSET", "is_header": True, "parent_code": "1000"},
    {"code": "1110", "name": "Cash and Cash Equivalents", "type_code": "ASSET", "is_header": True, "parent_code": "1100"},
    {"code": "1111", "name": "Petty Cash", "type_code": "ASSET", "parent_code": "1110", "is_bank_account": True},
    {"code": "1112", "name": "Cash on Hand", "type_code": "ASSET", "parent_code": "1110", "is_bank_account": True},
    {"code": "1120", "name": "Bank Accounts", "type_code": "ASSET", "is_header": True, "parent_code": "1100"},
    {"code": "1121", "name": "Main Bank Account", "type_code": "ASSET", "parent_code": "1120", "is_bank_account": True},
    {"code": "1130", "name": "Accounts Receivable", "type_code": "ASSET", "is_header": True, "parent_code": "1100"},
    {"code": "1131", "name": "Trade Receivables", "type_code": "ASSET", "parent_code": "1130", "is_control_account": True},
    {"code": "1140", "name": "Inventory", "type_code": "ASSET", "is_header": True, "parent_code": "1100"},
    {"code": "1141", "name": "Spare Parts Inventory", "type_code": "ASSET", "parent_code": "1140"},
    {"code": "1142", "name": "Consumables Inventory", "type_code": "ASSET", "parent_code": "1140"},
    {"code": "1150", "name": "Prepaid Expenses", "type_code": "ASSET", "parent_code": "1100"},
    {"code": "1160", "name": "VAT Receivable", "type_code": "ASSET", "is_header": True, "parent_code": "1100"},
    {"code": "1161", "name": "VAT Input", "type_code": "ASSET", "parent_code": "1160", "description": "Input VAT on purchases - recoverable"},
    {"code": "1200", "name": "Fixed Assets", "type_code": "ASSET", "is_header": True, "parent_code": "1000"},
    {"code": "1210", "name": "Equipment", "type_code": "ASSET", "parent_code": "1200"},
    {"code": "1220", "name": "Vehicles", "type_code": "ASSET", "parent_code": "1200"},
    {"code": "1230", "name": "Furniture & Fixtures", "type_code": "ASSET", "parent_code": "1200"},
    {"code": "1290", "name": "Accumulated Depreciation", "type_code": "ASSET", "parent_code": "1200"},

    # Liabilities (2xxx)
    {"code": "2000", "name": "Liabilities", "type_code": "LIABILITY", "is_header": True},
    {"code": "2100", "name": "Current Liabilities", "type_code": "LIABILITY", "is_header": True, "parent_code": "2000"},
    {"code": "2110", "name": "Accounts Payable", "type_code": "LIABILITY", "is_header": True, "parent_code": "2100"},
    {"code": "2111", "name": "Trade Payables", "type_code": "LIABILITY", "parent_code": "2110", "is_control_account": True},
    {"code": "2115", "name": "Goods Received Not Invoiced (GRNI)", "type_code": "LIABILITY", "parent_code": "2110", "description": "Accrual for goods received but not yet invoiced"},
    {"code": "2120", "name": "Accrued Expenses", "type_code": "LIABILITY", "parent_code": "2100"},
    {"code": "2130", "name": "Unearned Revenue", "type_code": "LIABILITY", "parent_code": "2100"},
    {"code": "2140", "name": "Taxes Payable", "type_code": "LIABILITY", "is_header": True, "parent_code": "2100"},
    {"code": "2141", "name": "VAT Payable", "type_code": "LIABILITY", "parent_code": "2140"},
    {"code": "2142", "name": "Income Tax Payable", "type_code": "LIABILITY", "parent_code": "2140"},
    {"code": "2200", "name": "Long-term Liabilities", "type_code": "LIABILITY", "is_header": True, "parent_code": "2000"},
    {"code": "2210", "name": "Bank Loans", "type_code": "LIABILITY", "parent_code": "2200"},

    # Equity (3xxx)
    {"code": "3000", "name": "Equity", "type_code": "EQUITY", "is_header": True},
    {"code": "3100", "name": "Owner's Capital", "type_code": "EQUITY", "parent_code": "3000"},
    {"code": "3200", "name": "Retained Earnings", "type_code": "EQUITY", "parent_code": "3000"},
    {"code": "3300", "name": "Current Year Earnings", "type_code": "EQUITY", "parent_code": "3000"},

    # Revenue (4xxx)
    {"code": "4000", "name": "Revenue", "type_code": "REVENUE", "is_header": True},
    {"code": "4100", "name": "Service Revenue", "type_code": "REVENUE", "is_header": True, "parent_code": "4000"},
    {"code": "4110", "name": "Maintenance Contract Revenue", "type_code": "REVENUE", "parent_code": "4100", "is_site_specific": True},
    {"code": "4120", "name": "Reactive Work Revenue", "type_code": "REVENUE", "parent_code": "4100", "is_site_specific": True},
    {"code": "4130", "name": "Project Revenue", "type_code": "REVENUE", "parent_code": "4100", "is_site_specific": True},
    {"code": "4200", "name": "Other Revenue", "type_code": "REVENUE", "is_header": True, "parent_code": "4000"},
    {"code": "4210", "name": "Parts Sales Revenue", "type_code": "REVENUE", "parent_code": "4200"},

    # Expenses (5xxx)
    {"code": "5000", "name": "Expenses", "type_code": "EXPENSE", "is_header": True},
    {"code": "5100", "name": "Cost of Services", "type_code": "EXPENSE", "is_header": True, "parent_code": "5000"},
    {"code": "5110", "name": "Labor Costs", "type_code": "EXPENSE", "is_header": True, "parent_code": "5100"},
    {"code": "5111", "name": "Technician Salaries", "type_code": "EXPENSE", "parent_code": "5110", "is_site_specific": True},
    {"code": "5112", "name": "Overtime", "type_code": "EXPENSE", "parent_code": "5110", "is_site_specific": True},
    {"code": "5120", "name": "Materials & Parts", "type_code": "EXPENSE", "is_header": True, "parent_code": "5100"},
    {"code": "5121", "name": "Spare Parts Used", "type_code": "EXPENSE", "parent_code": "5120", "is_site_specific": True},
    {"code": "5122", "name": "Consumables Used", "type_code": "EXPENSE", "parent_code": "5120", "is_site_specific": True},
    {"code": "5130", "name": "Subcontractor Costs", "type_code": "EXPENSE", "parent_code": "5100", "is_site_specific": True},
    {"code": "5200", "name": "Operating Expenses", "type_code": "EXPENSE", "is_header": True, "parent_code": "5000"},
    {"code": "5210", "name": "Rent Expense", "type_code": "EXPENSE", "parent_code": "5200"},
    {"code": "5220", "name": "Utilities", "type_code": "EXPENSE", "parent_code": "5200"},
    {"code": "5230", "name": "Insurance", "type_code": "EXPENSE", "parent_code": "5200"},
    {"code": "5240", "name": "Vehicle Expenses", "type_code": "EXPENSE", "is_header": True, "parent_code": "5200"},
    {"code": "5241", "name": "Fuel", "type_code": "EXPENSE", "parent_code": "5240"},
    {"code": "5242", "name": "Vehicle Maintenance", "type_code": "EXPENSE", "parent_code": "5240"},
    {"code": "5250", "name": "Office Supplies", "type_code": "EXPENSE", "parent_code": "5200"},
    {"code": "5260", "name": "Communication", "type_code": "EXPENSE", "parent_code": "5200"},
    {"code": "5300", "name": "Administrative Expenses", "type_code": "EXPENSE", "is_header": True, "parent_code": "5000"},
    {"code": "5310", "name": "Admin Salaries", "type_code": "EXPENSE", "parent_code": "5300"},
    {"code": "5320", "name": "Professional Fees", "type_code": "EXPENSE", "parent_code": "5300"},
    {"code": "5330", "name": "Bank Charges", "type_code": "EXPENSE", "parent_code": "5300"},
    {"code": "5400", "name": "Depreciation Expense", "type_code": "EXPENSE", "parent_code": "5000"},
    # Procurement Variances (5500)
    {"code": "5500", "name": "Procurement Variances", "type_code": "EXPENSE", "is_header": True, "parent_code": "5000"},
    {"code": "5510", "name": "Purchase Price Variance", "type_code": "EXPENSE", "parent_code": "5500", "description": "Variance between PO price and invoice price"},
    {"code": "5520", "name": "Purchase Discount", "type_code": "EXPENSE", "parent_code": "5500", "description": "Early payment discounts earned"},

    # Other Revenue (for purchase discounts - contra expense)
    {"code": "4220", "name": "Purchase Discounts Earned", "type_code": "REVENUE", "parent_code": "4200", "description": "Early payment discounts taken"},
]


# =============================================================================
# DEFAULT ITEM CATEGORIES
# =============================================================================

DEFAULT_ITEM_CATEGORIES = [
    {"code": "CV", "name": "Civil", "sort_order": 1},
    {"code": "EL", "name": "Electrical", "sort_order": 2},
    {"code": "TL", "name": "Tool", "sort_order": 3},
    {"code": "PL", "name": "Plumbing", "sort_order": 4},
    {"code": "MC", "name": "Mechanical", "sort_order": 5},
    {"code": "LGH", "name": "Lighting", "sort_order": 6},
    {"code": "SAN", "name": "Sanitary", "sort_order": 7},
    {"code": "HVC", "name": "HVAC", "sort_order": 8},
]


# =============================================================================
# DEFAULT ACCOUNT MAPPINGS
# =============================================================================

DEFAULT_ACCOUNT_MAPPINGS = [
    # ==========================================================================
    # GOODS RECEIPT (GRN) - Stage 1 of Procurement
    # ==========================================================================
    # Goods Receipt / PO Receiving - DR: Inventory, CR: GRNI
    {
        "transaction_type": "po_receive_inventory",
        "category": None,
        "debit_account_code": "1141",  # Spare Parts Inventory (detail account)
        "credit_account_code": "2115",  # GRNI
        "description": "Goods Receipt - Inventory items received"
    },
    {
        "transaction_type": "inventory_increase",
        "category": None,
        "debit_account_code": "1141",  # Spare Parts Inventory
        "credit_account_code": "2115",  # GRNI
        "description": "Inventory increase from receiving"
    },
    # Invoice Auto-Receive - Direct inventory receipt from invoice (no PO)
    {
        "transaction_type": "invoice_receive_inventory",
        "category": None,
        "debit_account_code": "1141",  # Spare Parts Inventory
        "credit_account_code": "2115",  # GRNI
        "description": "Invoice Auto-Receive - Inventory received directly from invoice"
    },
    # GRNI account reference
    {
        "transaction_type": "grni",
        "category": None,
        "debit_account_code": "2115",  # For clearing
        "credit_account_code": "2115",  # For GRN posting
        "description": "Goods Received Not Invoiced - interim liability"
    },

    # ==========================================================================
    # SUPPLIER INVOICE - Stage 2 of Procurement (GRNI Clearing)
    # ==========================================================================
    # Invoice matching - clear GRNI to AP
    {
        "transaction_type": "invoice_match",
        "category": None,
        "debit_account_code": "2115",  # GRNI (clear)
        "credit_account_code": "2111",  # Trade Payables (create AP)
        "description": "Invoice matched to GRN - clear GRNI to AP"
    },
    # Accounts Payable reference
    {
        "transaction_type": "accounts_payable",
        "category": None,
        "debit_account_code": "2111",  # For payment
        "credit_account_code": "2111",  # For invoice
        "description": "Accounts Payable - Trade Payables"
    },
    # Purchase Price Variance
    {
        "transaction_type": "purchase_price_variance",
        "category": None,
        "debit_account_code": "5510",  # PPV expense
        "credit_account_code": "5510",  # PPV (contra if credit)
        "description": "Purchase Price Variance - invoice vs PO/GRN"
    },
    # VAT Payable - Input VAT on purchases
    {
        "transaction_type": "vat_payable",
        "category": None,
        "debit_account_code": "2141",  # VAT Payable (debit for input VAT)
        "credit_account_code": "2141",  # VAT Payable (credit for output VAT)
        "description": "VAT Payable - Input/Output VAT"
    },
    # VAT Input - Recoverable VAT on purchases (debit when receiving invoices)
    {
        "transaction_type": "vat_input",
        "category": None,
        "debit_account_code": "1161",  # VAT Input (asset - recoverable)
        "credit_account_code": "1161",  # VAT Input
        "description": "VAT Input - Recoverable VAT on purchases"
    },
    # Tax Input - Alternative name for VAT Input
    {
        "transaction_type": "tax_input",
        "category": None,
        "debit_account_code": "1161",  # VAT Input (asset - recoverable)
        "credit_account_code": "1161",  # VAT Input
        "description": "Tax Input - Recoverable tax on purchases"
    },

    # ==========================================================================
    # SUPPLIER PAYMENT - Stage 3 of Procurement
    # ==========================================================================
    # Cash/Bank for payments
    {
        "transaction_type": "cash",
        "category": None,
        "debit_account_code": "1121",  # Main Bank Account
        "credit_account_code": "1121",  # Main Bank Account
        "description": "Cash/Bank Account for payments"
    },
    # Purchase Discount earned
    {
        "transaction_type": "purchase_discount",
        "category": None,
        "debit_account_code": "5520",  # Purchase Discount expense (contra)
        "credit_account_code": "4220",  # Purchase Discounts Earned (revenue)
        "description": "Early payment discount taken"
    },

    # ==========================================================================
    # LANDED COST (Import Extra Costs)
    # ==========================================================================
    {
        "transaction_type": "landed_cost_freight",
        "category": None,
        "debit_account_code": "1141",  # Added to Spare Parts Inventory
        "credit_account_code": "2111",  # Trade Payables
        "description": "Freight cost on imports"
    },
    {
        "transaction_type": "landed_cost_duty",
        "category": None,
        "debit_account_code": "1141",  # Added to Spare Parts Inventory
        "credit_account_code": "2111",  # Trade Payables
        "description": "Customs duty on imports"
    },
    {
        "transaction_type": "landed_cost_customs",
        "category": None,
        "debit_account_code": "1141",  # Added to Spare Parts Inventory
        "credit_account_code": "2111",  # Trade Payables
        "description": "Customs charges on imports"
    },
    {
        "transaction_type": "landed_cost_insurance",
        "category": None,
        "debit_account_code": "1141",  # Added to Spare Parts Inventory
        "credit_account_code": "2111",  # Trade Payables
        "description": "Insurance cost on imports"
    },

    # ==========================================================================
    # INVENTORY ADJUSTMENTS
    # ==========================================================================
    {
        "transaction_type": "inventory_adjustment_increase",
        "category": None,
        "debit_account_code": "1141",  # Spare Parts Inventory
        "credit_account_code": "5121",  # Spare Parts Used (variance)
        "description": "Inventory adjustment - increase"
    },
    {
        "transaction_type": "inventory_adjustment_decrease",
        "category": None,
        "debit_account_code": "5121",  # Spare Parts Used
        "credit_account_code": "1141",  # Spare Parts Inventory
        "description": "Inventory adjustment - decrease"
    },

    # ==========================================================================
    # WORK ORDER
    # ==========================================================================
    {
        "transaction_type": "wo_parts_consumption",
        "category": None,
        "debit_account_code": "5121",  # Spare Parts Used
        "credit_account_code": "1141",  # Spare Parts Inventory
        "description": "Work order - spare parts consumed"
    },

    # ==========================================================================
    # PETTY CASH
    # ==========================================================================
    # Generic petty cash expense (fallback)
    {
        "transaction_type": "petty_cash_expense",
        "category": None,
        "debit_account_code": "5250",  # Office Supplies (default expense)
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash expense (general)"
    },
    # Category-specific petty cash expenses
    {
        "transaction_type": "petty_cash_expense",
        "category": "supplies",
        "debit_account_code": "5250",  # Office Supplies
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - supplies"
    },
    {
        "transaction_type": "petty_cash_expense",
        "category": "transport",
        "debit_account_code": "5241",  # Fuel (under Vehicle Expenses)
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - transport"
    },
    {
        "transaction_type": "petty_cash_expense",
        "category": "meals",
        "debit_account_code": "5250",  # Office Supplies (meals/entertainment)
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - meals"
    },
    {
        "transaction_type": "petty_cash_expense",
        "category": "tools",
        "debit_account_code": "5121",  # Spare Parts Used (tools)
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - tools"
    },
    {
        "transaction_type": "petty_cash_expense",
        "category": "materials",
        "debit_account_code": "5121",  # Spare Parts Used
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - materials"
    },
    {
        "transaction_type": "petty_cash_expense",
        "category": "services",
        "debit_account_code": "5130",  # Subcontractor Costs
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - services"
    },
    {
        "transaction_type": "petty_cash_expense",
        "category": "other",
        "debit_account_code": "5250",  # Office Supplies (miscellaneous)
        "credit_account_code": "1111",  # Petty Cash
        "description": "Petty cash - other expenses"
    },
    # Petty cash replenishment
    {
        "transaction_type": "petty_cash_replenishment",
        "category": None,
        "debit_account_code": "1111",  # Petty Cash
        "credit_account_code": "1121",  # Main Bank Account
        "description": "Petty cash replenishment"
    },
]


def seed_account_types(company_id: int, db: Session) -> dict:
    """
    Create default account types for a company.

    Returns:
        dict mapping type_code to AccountType object
    """
    account_types = {}

    for at_data in DEFAULT_ACCOUNT_TYPES:
        existing = db.query(AccountType).filter(
            AccountType.company_id == company_id,
            AccountType.code == at_data["code"]
        ).first()

        if existing:
            account_types[at_data["code"]] = existing
            continue

        at = AccountType(
            company_id=company_id,
            code=at_data["code"],
            name=at_data["name"],
            normal_balance=at_data["normal_balance"],
            display_order=at_data["display_order"],
            is_active=True
        )
        db.add(at)
        db.flush()
        account_types[at_data["code"]] = at

    return account_types


def seed_chart_of_accounts(company_id: int, db: Session) -> dict:
    """
    Create default chart of accounts for a company.

    Returns:
        dict with statistics about what was created
    """
    stats = {
        "account_types": 0,
        "accounts": 0,
        "skipped": 0
    }

    # First, create account types
    account_types = seed_account_types(company_id, db)
    stats["account_types"] = len(account_types)

    # Track created accounts by code for parent references
    accounts_by_code = {}

    # Create accounts in order (parents first)
    for acc_data in DEFAULT_ACCOUNTS:
        existing = db.query(Account).filter(
            Account.company_id == company_id,
            Account.code == acc_data["code"]
        ).first()

        if existing:
            accounts_by_code[acc_data["code"]] = existing
            stats["skipped"] += 1
            continue

        # Get account type
        type_code = acc_data.get("type_code", "ASSET")
        account_type = account_types.get(type_code)
        if not account_type:
            logger.warning(f"Account type {type_code} not found for account {acc_data['code']}")
            continue

        # Get parent if specified
        parent_id = None
        parent_code = acc_data.get("parent_code")
        if parent_code and parent_code in accounts_by_code:
            parent_id = accounts_by_code[parent_code].id

        account = Account(
            company_id=company_id,
            code=acc_data["code"],
            name=acc_data["name"],
            account_type_id=account_type.id,
            parent_id=parent_id,
            is_header=acc_data.get("is_header", False),
            is_bank_account=acc_data.get("is_bank_account", False),
            is_control_account=acc_data.get("is_control_account", False),
            is_site_specific=acc_data.get("is_site_specific", False),
            is_system=True,  # Mark as system account
            is_active=True
        )
        db.add(account)
        db.flush()
        accounts_by_code[acc_data["code"]] = account
        stats["accounts"] += 1

    return stats


def seed_main_warehouse(company_id: int, db: Session) -> dict:
    """
    Create a main warehouse for a company.

    Returns:
        dict with the created warehouse info
    """
    # Check if main warehouse already exists (by code or is_main flag)
    existing = db.query(Warehouse).filter(
        Warehouse.company_id == company_id,
        or_(Warehouse.code == "MAIN", Warehouse.is_main == True)
    ).first()

    if existing:
        return {"created": False, "warehouse_id": existing.id, "name": existing.name}

    warehouse = Warehouse(
        company_id=company_id,
        code="MAIN",
        name="Main Warehouse",
        notes="Primary warehouse for inventory storage",
        is_main=True,
        is_active=True
    )
    db.add(warehouse)
    db.flush()

    return {"created": True, "warehouse_id": warehouse.id, "name": warehouse.name}


def seed_item_categories(company_id: int, db: Session) -> dict:
    """
    Create default item categories for a company.

    Returns:
        dict with statistics about what was created
    """
    stats = {
        "created": [],
        "skipped": []
    }

    for cat_data in DEFAULT_ITEM_CATEGORIES:
        existing = db.query(ItemCategory).filter(
            ItemCategory.company_id == company_id,
            ItemCategory.code == cat_data["code"]
        ).first()

        if existing:
            stats["skipped"].append(cat_data["code"])
            continue

        category = ItemCategory(
            company_id=company_id,
            code=cat_data["code"],
            name=cat_data["name"],
            sort_order=cat_data["sort_order"]
        )
        db.add(category)
        stats["created"].append(cat_data["code"])

    return stats


def seed_account_mappings(company_id: int, db: Session) -> dict:
    """
    Create default account mappings for a company.

    These mappings define which accounts are used for automatic journal entries
    when processing transactions like goods receipts, invoices, etc.

    Returns:
        dict with statistics about what was created
    """
    stats = {
        "created": [],
        "skipped": [],
        "errors": []
    }

    # Get accounts by code for this company
    accounts = db.query(Account).filter(Account.company_id == company_id).all()
    accounts_by_code = {acc.code: acc for acc in accounts}

    for mapping_data in DEFAULT_ACCOUNT_MAPPINGS:
        # Check if mapping already exists
        existing = db.query(DefaultAccountMapping).filter(
            DefaultAccountMapping.company_id == company_id,
            DefaultAccountMapping.transaction_type == mapping_data["transaction_type"],
            DefaultAccountMapping.category == mapping_data["category"]
        ).first()

        if existing:
            stats["skipped"].append(mapping_data["transaction_type"])
            continue

        # Get debit and credit accounts
        debit_account = accounts_by_code.get(mapping_data["debit_account_code"])
        credit_account = accounts_by_code.get(mapping_data["credit_account_code"])

        if not debit_account:
            error_msg = f"{mapping_data['transaction_type']}: Debit account {mapping_data['debit_account_code']} not found"
            stats["errors"].append(error_msg)
            logger.warning(error_msg)
            continue

        if not credit_account:
            error_msg = f"{mapping_data['transaction_type']}: Credit account {mapping_data['credit_account_code']} not found"
            stats["errors"].append(error_msg)
            logger.warning(error_msg)
            continue

        # Create the mapping
        mapping = DefaultAccountMapping(
            company_id=company_id,
            transaction_type=mapping_data["transaction_type"],
            category=mapping_data["category"],
            debit_account_id=debit_account.id,
            credit_account_id=credit_account.id,
            description=mapping_data["description"],
            is_active=True
        )
        db.add(mapping)
        stats["created"].append(mapping_data["transaction_type"])

    return stats


def generate_address_number(company_id: int, db: Session) -> str:
    """
    Generate the next sequential address number for a company.
    Format: 8-digit zero-padded number (e.g., "00000001")
    """
    # Get the highest address number for this company
    last_entry = db.query(AddressBook).filter(
        AddressBook.company_id == company_id
    ).order_by(AddressBook.address_number.desc()).first()

    if last_entry and last_entry.address_number:
        try:
            next_num = int(last_entry.address_number) + 1
        except ValueError:
            next_num = 1
    else:
        next_num = 1

    return f"{next_num:08d}"


def seed_default_client_and_site(company_id: int, db: Session) -> dict:
    """
    Create a default client and site for a company using Address Book.

    This creates:
    1. Address Book entry (type 'C' - Customer) as the master record
    2. Legacy Client record linked to Address Book (for backward compatibility)
    3. Address Book entry (type 'CB' - Branch) for the site
    4. Legacy Site record linked to Address Book (for backward compatibility)

    Each Address Book entry also gets a linked Business Unit for cost tracking.

    Returns:
        dict with the created entries info
    """
    result = {
        "address_book_customer": None,
        "address_book_branch": None,
        "client": None,
        "site": None
    }

    # Get company info for naming
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"Company {company_id} not found for seeding client/site")
        return result

    # Check if Address Book customer entry already exists
    existing_ab_customer = db.query(AddressBook).filter(
        AddressBook.company_id == company_id,
        AddressBook.search_type == 'C'
    ).first()

    if existing_ab_customer:
        result["address_book_customer"] = {
            "created": False,
            "id": existing_ab_customer.id,
            "address_number": existing_ab_customer.address_number,
            "name": existing_ab_customer.alpha_name
        }
        ab_customer = existing_ab_customer
    else:
        # Generate address number for customer
        customer_address_number = generate_address_number(company_id, db)

        # Create Business Unit for the customer
        customer_bu = BusinessUnit(
            company_id=company_id,
            code=customer_address_number,
            name=f"{company.name} - Main Operations",
            description="Default customer business unit",
            is_active=True
        )
        db.add(customer_bu)
        db.flush()

        # Create Address Book entry for Customer (type C)
        ab_customer = AddressBook(
            company_id=company_id,
            address_number=customer_address_number,
            search_type='C',  # Customer
            alpha_name=f"{company.name} - Main Operations",
            mailing_name=company.name,
            tax_id=company.tax_number,
            address_line_1=company.address,
            city=company.city,
            country=company.country,
            phone_primary=company.phone,
            email=company.email,
            business_unit_id=customer_bu.id,
            is_active=True,
            notes="Default customer created during company setup"
        )
        db.add(ab_customer)
        db.flush()

        result["address_book_customer"] = {
            "created": True,
            "id": ab_customer.id,
            "address_number": ab_customer.address_number,
            "name": ab_customer.alpha_name,
            "business_unit_id": customer_bu.id
        }
        logger.info(f"Created Address Book customer '{ab_customer.alpha_name}' (#{ab_customer.address_number}) for company {company_id}")

    # Check if legacy client already exists
    existing_client = db.query(Client).filter(
        Client.company_id == company_id
    ).first()

    if existing_client:
        result["client"] = {
            "created": False,
            "client_id": existing_client.id,
            "name": existing_client.name
        }
        client = existing_client
        # Link to Address Book if not already linked
        if not existing_client.address_book_id and ab_customer:
            existing_client.address_book_id = ab_customer.id
            db.flush()
    else:
        # Create legacy Client linked to Address Book
        client = Client(
            company_id=company_id,
            name=ab_customer.alpha_name,
            code=ab_customer.address_number,
            email=company.email,
            phone=company.phone,
            address=company.address,
            city=company.city,
            country=company.country,
            contact_person="Main Office",
            address_book_id=ab_customer.id,
            is_active=True
        )
        db.add(client)
        db.flush()
        result["client"] = {
            "created": True,
            "client_id": client.id,
            "name": client.name,
            "address_book_id": ab_customer.id
        }
        logger.info(f"Created legacy client '{client.name}' linked to Address Book #{ab_customer.address_number}")

    # Check if Address Book branch entry already exists
    existing_ab_branch = db.query(AddressBook).filter(
        AddressBook.company_id == company_id,
        AddressBook.search_type == 'CB',
        AddressBook.parent_address_book_id == ab_customer.id
    ).first()

    if existing_ab_branch:
        result["address_book_branch"] = {
            "created": False,
            "id": existing_ab_branch.id,
            "address_number": existing_ab_branch.address_number,
            "name": existing_ab_branch.alpha_name
        }
        ab_branch = existing_ab_branch
    else:
        # Generate address number for branch
        branch_address_number = generate_address_number(company_id, db)

        # Create Business Unit for the branch/site
        branch_bu = BusinessUnit(
            company_id=company_id,
            code=branch_address_number,
            name="Headquarters",
            description="Default headquarters site",
            is_active=True
        )
        db.add(branch_bu)
        db.flush()

        # Create Address Book entry for Branch (type CB)
        ab_branch = AddressBook(
            company_id=company_id,
            address_number=branch_address_number,
            search_type='CB',  # Customer Branch
            alpha_name="Headquarters",
            mailing_name="Headquarters",
            address_line_1=company.address,
            city=company.city,
            country=company.country,
            phone_primary=company.phone,
            email=company.email,
            parent_address_book_id=ab_customer.id,  # Link to parent customer
            business_unit_id=branch_bu.id,
            is_active=True,
            notes="Default headquarters created during company setup"
        )
        db.add(ab_branch)
        db.flush()

        result["address_book_branch"] = {
            "created": True,
            "id": ab_branch.id,
            "address_number": ab_branch.address_number,
            "name": ab_branch.alpha_name,
            "parent_id": ab_customer.id,
            "business_unit_id": branch_bu.id
        }
        logger.info(f"Created Address Book branch '{ab_branch.alpha_name}' (#{ab_branch.address_number}) for company {company_id}")

    # Check if legacy site already exists
    existing_site = db.query(Site).filter(
        Site.client_id == client.id
    ).first()

    if existing_site:
        result["site"] = {
            "created": False,
            "site_id": existing_site.id,
            "name": existing_site.name
        }
        # Link to Address Book if not already linked
        if not existing_site.address_book_id and ab_branch:
            existing_site.address_book_id = ab_branch.id
            db.flush()
    else:
        # Create legacy Site linked to Address Book
        site = Site(
            client_id=client.id,
            name=ab_branch.alpha_name,
            code=ab_branch.address_number,
            address=company.address,
            city=company.city,
            country=company.country,
            email=company.email,
            phone=company.phone,
            address_book_id=ab_branch.id,
            is_active=True
        )
        db.add(site)
        db.flush()
        result["site"] = {
            "created": True,
            "site_id": site.id,
            "name": site.name,
            "address_book_id": ab_branch.id
        }
        logger.info(f"Created legacy site '{site.name}' linked to Address Book #{ab_branch.address_number}")

    return result


def seed_default_business_units(company_id: int, db: Session) -> dict:
    """
    Seed default Business Units (Cost Centers) for a new company.

    Creates two default BUs:
    - CORP (balance_sheet) - For assets, liabilities, equity accounts
    - MAIN (profit_loss) - For revenue and expense accounts

    Args:
        company_id: The company ID to seed data for
        db: Database session

    Returns:
        dict with statistics about what was created
    """
    result = {
        "created": 0,
        "skipped": 0,
        "business_units": []
    }

    default_bus = [
        {
            "code": "CORP",
            "name": "Corporate",
            "description": "Default balance sheet cost center for assets, liabilities, and equity",
            "bu_type": "balance_sheet",
            "level_of_detail": 1,
            "is_active": True
        },
        {
            "code": "MAIN",
            "name": "Main Operations",
            "description": "Default profit & loss cost center for revenue and expenses",
            "bu_type": "profit_loss",
            "level_of_detail": 1,
            "is_active": True
        }
    ]

    for bu_data in default_bus:
        # Check if BU already exists
        existing = db.query(BusinessUnit).filter(
            BusinessUnit.company_id == company_id,
            BusinessUnit.code == bu_data["code"]
        ).first()

        if existing:
            result["skipped"] += 1
            result["business_units"].append({
                "code": bu_data["code"],
                "name": bu_data["name"],
                "created": False,
                "id": existing.id
            })
            logger.info(f"Business Unit '{bu_data['code']}' already exists for company {company_id}")
        else:
            bu = BusinessUnit(
                company_id=company_id,
                **bu_data
            )
            db.add(bu)
            db.flush()
            result["created"] += 1
            result["business_units"].append({
                "code": bu_data["code"],
                "name": bu_data["name"],
                "created": True,
                "id": bu.id
            })
            logger.info(f"Created Business Unit '{bu_data['code']}' for company {company_id}")

    # Link the main warehouse to CORP if it exists and isn't linked
    corp_bu = db.query(BusinessUnit).filter(
        BusinessUnit.company_id == company_id,
        BusinessUnit.code == "CORP"
    ).first()

    if corp_bu:
        unlinked_warehouses = db.query(Warehouse).filter(
            Warehouse.company_id == company_id,
            Warehouse.business_unit_id == None
        ).all()

        for wh in unlinked_warehouses:
            wh.business_unit_id = corp_bu.id
            logger.info(f"Linked warehouse '{wh.name}' to CORP business unit")

        if unlinked_warehouses:
            result["warehouses_linked"] = len(unlinked_warehouses)
            db.flush()

    return result


def seed_company_defaults(company_id: int, db: Session) -> dict:
    """
    Seed all default data for a new company.

    This includes:
    - Chart of Accounts (Account Types and Accounts)
    - Default Account Mappings (for automatic journal entries)
    - Main Warehouse
    - Default Business Units / Cost Centers (CORP and MAIN)
    - Default Item Categories
    - Default Client and Site (for cost allocations)

    Args:
        company_id: The company ID to seed data for
        db: Database session

    Returns:
        dict with statistics about what was created
    """
    logger.info(f"Seeding defaults for company {company_id}")

    results = {
        "chart_of_accounts": None,
        "account_mappings": None,
        "warehouse": None,
        "business_units": None,
        "item_categories": None,
        "client_and_site": None,
        "errors": []
    }

    try:
        # Seed Chart of Accounts
        coa_stats = seed_chart_of_accounts(company_id, db)
        results["chart_of_accounts"] = coa_stats
        logger.info(f"Chart of accounts seeded for company {company_id}: {coa_stats}")
    except Exception as e:
        logger.error(f"Error seeding chart of accounts for company {company_id}: {e}")
        results["errors"].append(f"Chart of accounts: {str(e)}")

    try:
        # Seed Account Mappings (must be after chart of accounts)
        mapping_stats = seed_account_mappings(company_id, db)
        results["account_mappings"] = mapping_stats
        logger.info(f"Account mappings seeded for company {company_id}: {mapping_stats}")
    except Exception as e:
        logger.error(f"Error seeding account mappings for company {company_id}: {e}")
        results["errors"].append(f"Account mappings: {str(e)}")

    try:
        # Seed Main Warehouse
        warehouse_result = seed_main_warehouse(company_id, db)
        results["warehouse"] = warehouse_result
        logger.info(f"Warehouse seeded for company {company_id}: {warehouse_result}")
    except Exception as e:
        logger.error(f"Error seeding warehouse for company {company_id}: {e}")
        results["errors"].append(f"Warehouse: {str(e)}")

    try:
        # Seed Default Business Units (Cost Centers) - after warehouse so it can link them
        bu_stats = seed_default_business_units(company_id, db)
        results["business_units"] = bu_stats
        logger.info(f"Business units seeded for company {company_id}: {bu_stats}")
    except Exception as e:
        logger.error(f"Error seeding business units for company {company_id}: {e}")
        results["errors"].append(f"Business units: {str(e)}")

    try:
        # Seed Item Categories
        cat_stats = seed_item_categories(company_id, db)
        results["item_categories"] = cat_stats
        logger.info(f"Item categories seeded for company {company_id}: {cat_stats}")
    except Exception as e:
        logger.error(f"Error seeding item categories for company {company_id}: {e}")
        results["errors"].append(f"Item categories: {str(e)}")

    try:
        # Seed Default Client and Site (required for cost allocations)
        client_site_result = seed_default_client_and_site(company_id, db)
        results["client_and_site"] = client_site_result
        logger.info(f"Client and site seeded for company {company_id}: {client_site_result}")
    except Exception as e:
        logger.error(f"Error seeding client and site for company {company_id}: {e}")
        results["errors"].append(f"Client and site: {str(e)}")

    return results
