#!/usr/bin/env python3
"""
Run database migration to make client_id nullable in nps_surveys table.
This allows surveys to be created using address_book_id instead of client_id.

Execute this script from the doxsnap_be directory:
    python run_migration_nps_client_nullable.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import engine

alter_statements = [
    # Make client_id nullable in nps_surveys table
    "ALTER TABLE nps_surveys ALTER COLUMN client_id DROP NOT NULL;",
]

def run_migration():
    print("Starting NPS surveys migration...")
    print("Making client_id nullable to support address_book_id...")

    with engine.connect() as conn:
        for stmt in alter_statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"✓ Executed: {stmt}")
            except Exception as e:
                if "already" in str(e).lower():
                    print(f"  Column already nullable, skipping...")
                else:
                    print(f"  Note: {e}")
                conn.rollback()

    print("\n" + "="*50)
    print("Migration completed successfully!")
    print("Please restart your FastAPI server.")
    print("="*50)

if __name__ == "__main__":
    run_migration()
