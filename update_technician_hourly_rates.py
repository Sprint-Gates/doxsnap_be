"""
Update Technician Hourly Rates
Computes hourly_rate for technicians with monthly salary who don't have hourly_rate set.
Formula: hourly_rate = base_salary / (working_days_per_month * working_hours_per_day)
"""
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import AddressBook

def update_hourly_rates():
    """Update hourly rates for employees with monthly salary"""
    db: Session = SessionLocal()

    try:
        # Find all employees (search_type='E') with monthly salary but no hourly_rate
        employees = db.query(AddressBook).filter(
            AddressBook.search_type == "E",
            AddressBook.salary_type == "monthly",
            AddressBook.base_salary.isnot(None)
        ).all()

        updated_count = 0
        skipped_count = 0

        for emp in employees:
            # Calculate hourly rate
            hours_per_day = float(emp.working_hours_per_day or 8.0)
            days_per_month = int(emp.working_days_per_month or 22)
            hours_per_month = days_per_month * hours_per_day

            if hours_per_month > 0:
                new_hourly_rate = round(float(emp.base_salary) / hours_per_month, 2)

                if emp.hourly_rate != new_hourly_rate:
                    old_rate = emp.hourly_rate
                    emp.hourly_rate = new_hourly_rate
                    updated_count += 1
                    print(f"  UPDATE: {emp.alpha_name} ({emp.address_number})")
                    print(f"          Base Salary: ${emp.base_salary}/month")
                    print(f"          Hours/Month: {hours_per_month} ({days_per_month} days x {hours_per_day} hrs)")
                    print(f"          Hourly Rate: ${old_rate or 'N/A'} -> ${new_hourly_rate}")
                else:
                    skipped_count += 1
                    print(f"  SKIP: {emp.alpha_name} (hourly rate already correct: ${emp.hourly_rate})")
            else:
                skipped_count += 1
                print(f"  SKIP: {emp.alpha_name} (invalid hours configuration)")

        db.commit()
        print(f"\nSummary:")
        print(f"  Updated: {updated_count} employees")
        print(f"  Skipped: {skipped_count} employees")
        print(f"\nDone!")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    update_hourly_rates()
