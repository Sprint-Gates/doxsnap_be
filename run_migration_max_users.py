#!/usr/bin/env python3
"""
Run database migration to add max_users_override column to companies table.
Execute this script from the doxsnap_be directory:
    python run_migration_max_users.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import engine


def run_migration():
    print("Starting database migration - Adding max_users_override to companies...")

    with engine.connect() as conn:
        # Add max_users_override column to companies table
        try:
            conn.execute(text("""
                ALTER TABLE companies
                ADD COLUMN IF NOT EXISTS max_users_override INTEGER
            """))
            conn.commit()
            print("Added max_users_override column to companies table")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print("Column already exists, skipping...")
            else:
                print(f"Note: {e}")
            conn.rollback()

    print("\n" + "="*50)
    print("Migration completed successfully!")
    print("This allows platform admins to override user limits per company.")
    print("="*50)


if __name__ == "__main__":
    run_migration()
