#!/usr/bin/env python3
"""
Migration to fix converted clients from leads.
This script creates Address Book entries for clients that were converted from leads
but don't have corresponding Address Book entries, making them visible in contracts
and other pages that query the Address Book.

Execute this script from the doxsnap_be directory:
    python run_migration_fix_converted_clients.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database import engine, SessionLocal
from app.models import Client, AddressBook, Lead


def generate_next_address_number(db: Session, company_id: int) -> str:
    """Generate next sequential address number for company (8-digit padded)"""
    entries = db.query(AddressBook.address_number).filter(
        AddressBook.company_id == company_id
    ).all()

    max_num = 0
    for (addr_num,) in entries:
        try:
            num = int(addr_num)
            if num > max_num:
                max_num = num
        except (ValueError, TypeError):
            pass

    return str(max_num + 1).zfill(8)


def run_migration():
    print("="*70)
    print("Starting migration: Creating Address Book entries for converted clients")
    print("="*70)

    db = SessionLocal()

    try:
        # Find all clients that don't have an address_book_id
        clients_without_ab = db.query(Client).filter(
            Client.address_book_id == None
        ).all()

        print(f"\nFound {len(clients_without_ab)} clients without Address Book entries")

        if len(clients_without_ab) == 0:
            print("\nNo clients to migrate. All clients already have Address Book entries.")
            return

        migrated_count = 0
        skipped_count = 0

        for client in clients_without_ab:
            try:
                # Check if this client was converted from a lead
                lead = db.query(Lead).filter(
                    Lead.converted_to_client_id == client.id
                ).first()

                client_source = "converted from lead" if lead else "created directly"

                print(f"\nProcessing client: {client.name} (ID: {client.id}, {client_source})")

                # Check if there's already an Address Book entry for this client
                # (by checking if alpha_name matches and company_id matches)
                existing_ab = db.query(AddressBook).filter(
                    AddressBook.company_id == client.company_id,
                    AddressBook.alpha_name == client.name,
                    AddressBook.search_type == 'C'
                ).first()

                if existing_ab:
                    # Link existing Address Book entry to client
                    client.address_book_id = existing_ab.id
                    if lead:
                        lead.converted_to_address_book_id = existing_ab.id
                    print(f"  → Linked to existing Address Book entry (ID: {existing_ab.id})")
                    migrated_count += 1
                else:
                    # Create new Address Book entry
                    address_number = client.code if client.code else generate_next_address_number(db, client.company_id)

                    address_book_entry = AddressBook(
                        company_id=client.company_id,
                        address_number=address_number,
                        search_type='C',  # Customer type
                        alpha_name=client.name,
                        mailing_name=client.contact_person,
                        email=client.email,
                        phone_primary=client.phone,
                        address_line_1=client.address,
                        city=client.city,
                        country=client.country,
                        tax_id=client.tax_number,
                        notes=client.notes or "Migrated from legacy client record",
                        is_active=client.is_active if hasattr(client, 'is_active') else True,
                        legacy_client_id=client.id
                    )
                    db.add(address_book_entry)
                    db.flush()

                    # Link client to new Address Book entry
                    client.address_book_id = address_book_entry.id

                    # Update lead if this was a converted client
                    if lead:
                        lead.converted_to_address_book_id = address_book_entry.id

                    print(f"  → Created new Address Book entry (ID: {address_book_entry.id}, Number: {address_number})")
                    migrated_count += 1

                db.commit()

            except Exception as e:
                print(f"  ✗ Error processing client {client.id}: {e}")
                db.rollback()
                skipped_count += 1

        print("\n" + "="*70)
        print("Migration completed!")
        print(f"  ✓ Successfully migrated: {migrated_count} clients")
        if skipped_count > 0:
            print(f"  ✗ Skipped (errors): {skipped_count} clients")
        print("="*70)
        print("\nConverted clients should now be visible in:")
        print("  • Contracts page")
        print("  • All other pages that query the Address Book")
        print("="*70)

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
