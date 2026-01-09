"""
Seed Sites for Address Book Customers
Creates sample sites for each customer (search_type='C') in Address Book
"""
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import AddressBook, Site, Company

def seed_sites():
    """Create sample sites for Address Book customers"""
    db: Session = SessionLocal()

    try:
        # Get the first company
        company = db.query(Company).first()
        if not company:
            print("ERROR: No company found. Please create a company first.")
            return

        print(f"Seeding sites for company: {company.name} (ID: {company.id})")

        # Get all customers from Address Book
        customers = db.query(AddressBook).filter(
            AddressBook.company_id == company.id,
            AddressBook.search_type == 'C'
        ).all()

        print(f"Found {len(customers)} customers in Address Book")

        created_count = 0
        skipped_count = 0

        for customer in customers:
            # Check if a site already exists for this customer
            existing = db.query(Site).filter(
                Site.address_book_id == customer.id
            ).first()

            if existing:
                print(f"  SKIP: {customer.alpha_name} - already has site: {existing.name}")
                skipped_count += 1
                continue

            # Create a main site for each customer
            site = Site(
                address_book_id=customer.id,
                name=f"{customer.alpha_name} - Main Office",
                code=f"SITE-{customer.address_number}",
                address=customer.address_line_1,
                city=customer.city,
                country=customer.country,
                phone=customer.phone_primary,
                email=customer.email,
                is_active=True
            )
            db.add(site)
            created_count += 1
            print(f"  CREATE: {site.name} for {customer.alpha_name}")

        db.commit()
        print(f"\nSummary:")
        print(f"  Created: {created_count} sites")
        print(f"  Skipped: {skipped_count} sites (already exist)")
        print(f"\nDone!")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_sites()
