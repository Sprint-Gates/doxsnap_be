"""
Seed Vendors in Address Book
Creates 10 sample vendors with search_type='V' in the Address Book
Similar to how clients are managed with search_type='C'
"""
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import AddressBook, Company

def seed_vendors():
    """Create sample vendors in Address Book for testing"""
    db: Session = SessionLocal()

    try:
        # Get the first company (DoxSnap Demo Company)
        company = db.query(Company).first()
        if not company:
            print("ERROR: No company found. Please create a company first.")
            return

        print(f"Seeding vendors for company: {company.name} (ID: {company.id})")

        # Sample vendors data
        vendors = [
            {
                "alpha_name": "ABC Industrial Supplies",
                "address_number": "V-001",
                "search_type": "V",
                "email": "sales@abcindustrial.com",
                "phone_primary": "+1-555-0101",
                "address_line_1": "123 Industrial Blvd",
                "city": "Houston",
                "country": "USA",
                "tax_id": "TAX-V001",
                "payment_terms": "Net 30"
            },
            {
                "alpha_name": "TechParts International",
                "address_number": "V-002",
                "search_type": "V",
                "email": "orders@techparts.com",
                "phone_primary": "+1-555-0102",
                "address_line_1": "456 Tech Park Drive",
                "city": "San Jose",
                "country": "USA",
                "tax_id": "TAX-V002",
                "payment_terms": "Net 45"
            },
            {
                "alpha_name": "Global HVAC Solutions",
                "address_number": "V-003",
                "search_type": "V",
                "email": "info@globalhvac.com",
                "phone_primary": "+1-555-0103",
                "address_line_1": "789 Climate Control Ave",
                "city": "Chicago",
                "country": "USA",
                "tax_id": "TAX-V003",
                "payment_terms": "Net 30"
            },
            {
                "alpha_name": "Precision Tools & Equipment",
                "address_number": "V-004",
                "search_type": "V",
                "email": "sales@precisiontools.com",
                "phone_primary": "+1-555-0104",
                "address_line_1": "321 Toolmaker Lane",
                "city": "Detroit",
                "country": "USA",
                "tax_id": "TAX-V004",
                "payment_terms": "Net 15"
            },
            {
                "alpha_name": "ElectroPower Systems",
                "address_number": "V-005",
                "search_type": "V",
                "email": "contact@electropower.com",
                "phone_primary": "+1-555-0105",
                "address_line_1": "567 Power Grid Road",
                "city": "Dallas",
                "country": "USA",
                "tax_id": "TAX-V005",
                "payment_terms": "Net 30"
            },
            {
                "alpha_name": "Plumbing Wholesale Co",
                "address_number": "V-006",
                "search_type": "V",
                "email": "orders@plumbingwholesale.com",
                "phone_primary": "+1-555-0106",
                "address_line_1": "890 Pipe Street",
                "city": "Phoenix",
                "country": "USA",
                "tax_id": "TAX-V006",
                "payment_terms": "COD"
            },
            {
                "alpha_name": "Safety Equipment Plus",
                "address_number": "V-007",
                "search_type": "V",
                "email": "sales@safetyequip.com",
                "phone_primary": "+1-555-0107",
                "address_line_1": "234 Safety First Blvd",
                "city": "Atlanta",
                "country": "USA",
                "tax_id": "TAX-V007",
                "payment_terms": "Net 30"
            },
            {
                "alpha_name": "AutoFleet Parts",
                "address_number": "V-008",
                "search_type": "V",
                "email": "fleet@autofleetparts.com",
                "phone_primary": "+1-555-0108",
                "address_line_1": "678 Motor Way",
                "city": "Los Angeles",
                "country": "USA",
                "tax_id": "TAX-V008",
                "payment_terms": "Net 60"
            },
            {
                "alpha_name": "Building Materials Direct",
                "address_number": "V-009",
                "search_type": "V",
                "email": "orders@buildmaterials.com",
                "phone_primary": "+1-555-0109",
                "address_line_1": "901 Construction Ave",
                "city": "Denver",
                "country": "USA",
                "tax_id": "TAX-V009",
                "payment_terms": "Net 30"
            },
            {
                "alpha_name": "Office Supplies Pro",
                "address_number": "V-010",
                "search_type": "V",
                "email": "business@officesuppliespro.com",
                "phone_primary": "+1-555-0110",
                "address_line_1": "345 Business Center",
                "city": "Miami",
                "country": "USA",
                "tax_id": "TAX-V010",
                "payment_terms": "Net 15"
            }
        ]

        created_count = 0
        skipped_count = 0

        for vendor_data in vendors:
            # Check if vendor already exists by address_number
            existing = db.query(AddressBook).filter(
                AddressBook.company_id == company.id,
                AddressBook.address_number == vendor_data["address_number"]
            ).first()

            if existing:
                print(f"  SKIP: {vendor_data['alpha_name']} (already exists)")
                skipped_count += 1
                continue

            # Create new vendor in Address Book
            # category_code_04 is used for payment terms per JDE convention
            vendor = AddressBook(
                company_id=company.id,
                search_type=vendor_data["search_type"],
                alpha_name=vendor_data["alpha_name"],
                address_number=vendor_data["address_number"],
                email=vendor_data["email"],
                phone_primary=vendor_data["phone_primary"],
                address_line_1=vendor_data["address_line_1"],
                city=vendor_data["city"],
                country=vendor_data["country"],
                tax_id=vendor_data["tax_id"],
                category_code_04=vendor_data.get("payment_terms"),  # Payment terms in category code
                is_active=True
            )
            db.add(vendor)
            created_count += 1
            print(f"  CREATE: {vendor_data['alpha_name']} ({vendor_data['address_number']})")

        db.commit()
        print(f"\nSummary:")
        print(f"  Created: {created_count} vendors")
        print(f"  Skipped: {skipped_count} vendors (already exist)")
        print(f"\nDone! Vendors are now available in Address Book with search_type='V'")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_vendors()
