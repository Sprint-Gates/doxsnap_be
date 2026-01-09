"""
Seed Technicians/Employees in Address Book
Creates 10 sample technicians with search_type='E' in the Address Book
Technicians are employees that can be assigned to work orders, shifts, and devices.
"""
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import AddressBook, Company

def seed_technicians():
    """Create sample technicians/employees in Address Book for testing"""
    db: Session = SessionLocal()

    try:
        # Get the first company (DoxSnap Demo Company)
        company = db.query(Company).first()
        if not company:
            print("ERROR: No company found. Please create a company first.")
            return

        print(f"Seeding technicians for company: {company.name} (ID: {company.id})")

        # Sample technicians data
        technicians = [
            {
                "alpha_name": "John Smith",
                "address_number": "E-001",
                "employee_id": "EMP001",
                "search_type": "E",
                "email": "john.smith@company.com",
                "phone_primary": "+1-555-1001",
                "specialization": "HVAC",
                "salary_type": "monthly",
                "base_salary": 4500.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Sarah Johnson",
                "address_number": "E-002",
                "employee_id": "EMP002",
                "search_type": "E",
                "email": "sarah.johnson@company.com",
                "phone_primary": "+1-555-1002",
                "specialization": "Electrical",
                "salary_type": "monthly",
                "base_salary": 4800.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Mike Davis",
                "address_number": "E-003",
                "employee_id": "EMP003",
                "search_type": "E",
                "email": "mike.davis@company.com",
                "phone_primary": "+1-555-1003",
                "specialization": "Plumbing",
                "salary_type": "monthly",
                "base_salary": 4200.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Emily Brown",
                "address_number": "E-004",
                "employee_id": "EMP004",
                "search_type": "E",
                "email": "emily.brown@company.com",
                "phone_primary": "+1-555-1004",
                "specialization": "Mechanical",
                "salary_type": "monthly",
                "base_salary": 4600.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Robert Wilson",
                "address_number": "E-005",
                "employee_id": "EMP005",
                "search_type": "E",
                "email": "robert.wilson@company.com",
                "phone_primary": "+1-555-1005",
                "specialization": "General Maintenance",
                "salary_type": "hourly",
                "hourly_rate": 25.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Jennifer Martinez",
                "address_number": "E-006",
                "employee_id": "EMP006",
                "search_type": "E",
                "email": "jennifer.martinez@company.com",
                "phone_primary": "+1-555-1006",
                "specialization": "HVAC",
                "salary_type": "monthly",
                "base_salary": 4300.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "David Lee",
                "address_number": "E-007",
                "employee_id": "EMP007",
                "search_type": "E",
                "email": "david.lee@company.com",
                "phone_primary": "+1-555-1007",
                "specialization": "Electrical",
                "salary_type": "monthly",
                "base_salary": 5000.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Lisa Anderson",
                "address_number": "E-008",
                "employee_id": "EMP008",
                "search_type": "E",
                "email": "lisa.anderson@company.com",
                "phone_primary": "+1-555-1008",
                "specialization": "Fire Safety",
                "salary_type": "monthly",
                "base_salary": 4700.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "James Taylor",
                "address_number": "E-009",
                "employee_id": "EMP009",
                "search_type": "E",
                "email": "james.taylor@company.com",
                "phone_primary": "+1-555-1009",
                "specialization": "Carpentry",
                "salary_type": "hourly",
                "hourly_rate": 28.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            },
            {
                "alpha_name": "Amanda White",
                "address_number": "E-010",
                "employee_id": "EMP010",
                "search_type": "E",
                "email": "amanda.white@company.com",
                "phone_primary": "+1-555-1010",
                "specialization": "General Maintenance",
                "salary_type": "monthly",
                "base_salary": 4000.00,
                "working_hours_per_day": 8.0,
                "working_days_per_month": 22
            }
        ]

        created_count = 0
        skipped_count = 0

        for tech_data in technicians:
            # Check if technician already exists by address_number or employee_id
            existing = db.query(AddressBook).filter(
                AddressBook.company_id == company.id,
                AddressBook.address_number == tech_data["address_number"]
            ).first()

            if existing:
                print(f"  SKIP: {tech_data['alpha_name']} (already exists)")
                skipped_count += 1
                continue

            # Calculate hourly rate if monthly salary is provided
            # Formula: hourly_rate = base_salary / (working_days_per_month * working_hours_per_day)
            hourly_rate = tech_data.get("hourly_rate")
            if tech_data.get("salary_type") == "monthly" and tech_data.get("base_salary"):
                hours_per_month = tech_data.get("working_days_per_month", 22) * tech_data.get("working_hours_per_day", 8.0)
                hourly_rate = round(tech_data["base_salary"] / hours_per_month, 2)

            # Create new technician/employee in Address Book
            technician = AddressBook(
                company_id=company.id,
                search_type=tech_data["search_type"],
                alpha_name=tech_data["alpha_name"],
                mailing_name=tech_data["alpha_name"],
                address_number=tech_data["address_number"],
                employee_id=tech_data["employee_id"],
                email=tech_data["email"],
                phone_primary=tech_data["phone_primary"],
                specialization=tech_data["specialization"],
                salary_type=tech_data.get("salary_type"),
                base_salary=tech_data.get("base_salary"),
                hourly_rate=hourly_rate,
                working_hours_per_day=tech_data.get("working_hours_per_day"),
                working_days_per_month=tech_data.get("working_days_per_month"),
                salary_currency="USD",
                overtime_rate_multiplier=1.5,
                is_active=True
            )
            db.add(technician)
            created_count += 1
            print(f"  CREATE: {tech_data['alpha_name']} ({tech_data['address_number']}) - {tech_data['specialization']}")

        db.commit()
        print(f"\nSummary:")
        print(f"  Created: {created_count} technicians/employees")
        print(f"  Skipped: {skipped_count} technicians (already exist)")
        print(f"\nDone! Technicians are now available in Address Book with search_type='E'")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_technicians()
