"""
Migration: Add VAT Input account and mappings for existing companies

This script adds:
1. VAT Input account (1161) to the chart of accounts
2. vat_input and invoice_receive_inventory account mappings

Run with: python run_migration_vat_input.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Company, Account, AccountType, DefaultAccountMapping
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_company(company_id: int, db: Session):
    """Add VAT Input account and mappings for a single company"""

    logger.info(f"Processing company {company_id}...")

    # Get ASSET account type
    asset_type = db.query(AccountType).filter(
        AccountType.company_id == company_id,
        AccountType.code == "ASSET"
    ).first()

    if not asset_type:
        logger.warning(f"Company {company_id}: No ASSET account type found, skipping")
        return

    # Get parent account (1100 Current Assets) for the new VAT header
    parent_1100 = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "1100"
    ).first()

    # Check if VAT Receivable header (1160) exists
    vat_header = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "1160"
    ).first()

    if not vat_header:
        vat_header = Account(
            company_id=company_id,
            code="1160",
            name="VAT Receivable",
            account_type_id=asset_type.id,
            parent_id=parent_1100.id if parent_1100 else None,
            is_header=True,
            is_system=True,
            is_active=True
        )
        db.add(vat_header)
        db.flush()
        logger.info(f"Company {company_id}: Created VAT Receivable header (1160)")

    # Check if VAT Input account (1161) exists
    vat_input = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "1161"
    ).first()

    if not vat_input:
        vat_input = Account(
            company_id=company_id,
            code="1161",
            name="VAT Input",
            account_type_id=asset_type.id,
            parent_id=vat_header.id,
            is_header=False,
            is_system=True,
            is_active=True,
            description="Input VAT on purchases - recoverable"
        )
        db.add(vat_input)
        db.flush()
        logger.info(f"Company {company_id}: Created VAT Input account (1161)")

    # Get accounts needed for mappings
    inventory_account = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "1141"  # Spare Parts Inventory
    ).first()

    grni_account = db.query(Account).filter(
        Account.company_id == company_id,
        Account.code == "2115"  # GRNI
    ).first()

    # Add invoice_receive_inventory mapping if not exists
    existing_mapping = db.query(DefaultAccountMapping).filter(
        DefaultAccountMapping.company_id == company_id,
        DefaultAccountMapping.transaction_type == "invoice_receive_inventory"
    ).first()

    if not existing_mapping and inventory_account and grni_account:
        mapping = DefaultAccountMapping(
            company_id=company_id,
            transaction_type="invoice_receive_inventory",
            category=None,
            debit_account_id=inventory_account.id,
            credit_account_id=grni_account.id,
            description="Invoice Auto-Receive - Inventory received directly from invoice",
            is_active=True
        )
        db.add(mapping)
        logger.info(f"Company {company_id}: Created invoice_receive_inventory mapping")

    # Add vat_input mapping if not exists
    existing_vat_mapping = db.query(DefaultAccountMapping).filter(
        DefaultAccountMapping.company_id == company_id,
        DefaultAccountMapping.transaction_type == "vat_input"
    ).first()

    if not existing_vat_mapping and vat_input:
        mapping = DefaultAccountMapping(
            company_id=company_id,
            transaction_type="vat_input",
            category=None,
            debit_account_id=vat_input.id,
            credit_account_id=vat_input.id,
            description="VAT Input - Recoverable VAT on purchases",
            is_active=True
        )
        db.add(mapping)
        logger.info(f"Company {company_id}: Created vat_input mapping")

    # Add tax_input mapping if not exists (alias for vat_input)
    existing_tax_mapping = db.query(DefaultAccountMapping).filter(
        DefaultAccountMapping.company_id == company_id,
        DefaultAccountMapping.transaction_type == "tax_input"
    ).first()

    if not existing_tax_mapping and vat_input:
        mapping = DefaultAccountMapping(
            company_id=company_id,
            transaction_type="tax_input",
            category=None,
            debit_account_id=vat_input.id,
            credit_account_id=vat_input.id,
            description="Tax Input - Recoverable tax on purchases",
            is_active=True
        )
        db.add(mapping)
        logger.info(f"Company {company_id}: Created tax_input mapping")


def run_migration():
    """Run migration for all companies"""
    db = SessionLocal()

    try:
        # Get all companies
        companies = db.query(Company).all()
        logger.info(f"Found {len(companies)} companies to process")

        for company in companies:
            try:
                migrate_company(company.id, db)
            except Exception as e:
                logger.error(f"Error processing company {company.id}: {e}")
                continue

        db.commit()
        logger.info("Migration completed successfully!")

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
