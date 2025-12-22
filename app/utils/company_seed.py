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
    AccountType, Account, Warehouse, ItemCategory
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


def seed_company_defaults(company_id: int, db: Session) -> dict:
    """
    Seed all default data for a new company.

    This includes:
    - Chart of Accounts (Account Types and Accounts)
    - Main Warehouse
    - Default Item Categories

    Args:
        company_id: The company ID to seed data for
        db: Database session

    Returns:
        dict with statistics about what was created
    """
    logger.info(f"Seeding defaults for company {company_id}")

    results = {
        "chart_of_accounts": None,
        "warehouse": None,
        "item_categories": None,
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
        # Seed Main Warehouse
        warehouse_result = seed_main_warehouse(company_id, db)
        results["warehouse"] = warehouse_result
        logger.info(f"Warehouse seeded for company {company_id}: {warehouse_result}")
    except Exception as e:
        logger.error(f"Error seeding warehouse for company {company_id}: {e}")
        results["errors"].append(f"Warehouse: {str(e)}")

    try:
        # Seed Item Categories
        cat_stats = seed_item_categories(company_id, db)
        results["item_categories"] = cat_stats
        logger.info(f"Item categories seeded for company {company_id}: {cat_stats}")
    except Exception as e:
        logger.error(f"Error seeding item categories for company {company_id}: {e}")
        results["errors"].append(f"Item categories: {str(e)}")

    return results
