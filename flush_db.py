#!/usr/bin/env python3
"""
Full database reset - drops all tables and recreates them.
WARNING: This destroys ALL data including users, companies, etc.

Execute from the doxsnap_be directory:
    python flush_db.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text, inspect
from app.database import engine, Base
from app import models  # Import all models to register them with Base


def flush_database():
    print("=" * 60)
    print("FULL DATABASE RESET")
    print("=" * 60)
    print("\nWARNING: This will DELETE ALL DATA in the database!")
    print("This includes: users, companies, invoices, clients, etc.\n")

    confirm = input("Type 'YES' to confirm full database reset: ")
    if confirm != "YES":
        print("Aborted. No changes made.")
        return

    print("\nDropping all tables...")

    # Use CASCADE to handle foreign key dependencies
    with engine.connect() as conn:
        # Get all table names
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Drop all tables with CASCADE
        for table in tables:
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
                print(f"  Dropped {table}")
            except Exception as e:
                print(f"  Error dropping {table}: {e}")

        conn.commit()

    print("✓ All tables dropped")

    # Recreate all tables
    print("\nRecreating all tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ All tables created")

    # Seed default plans
    print("\nSeeding default plans...")
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO plans (name, slug, description, price_monthly, documents_min, documents_max, max_users, max_clients, max_branches, max_projects, is_active, is_popular, sort_order, created_at, updated_at)
            VALUES
                ('Starter', 'starter', 'Perfect for small businesses', 49, 50, 100, 3, 10, 3, 10, true, true, 1, NOW(), NOW()),
                ('Professional', 'professional', 'For growing teams', 99, 100, 500, 10, 50, 10, 50, true, false, 2, NOW(), NOW()),
                ('Enterprise', 'enterprise', 'For large organizations', 299, 500, 2000, 50, 200, 50, 200, true, false, 3, NOW(), NOW())
            ON CONFLICT (slug) DO NOTHING
        """))
        conn.commit()
    print("✓ Default plans seeded")

    # Seed default super admin
    print("\nSeeding default super admin...")
    with engine.connect() as conn:
        # Hash for 'admin123' using bcrypt
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        hashed_password = pwd_context.hash("admin123")

        conn.execute(text("""
            INSERT INTO super_admins (email, name, hashed_password, is_active, created_at, updated_at)
            VALUES (:email, :name, :hashed_password, true, NOW(), NOW())
            ON CONFLICT DO NOTHING
        """), {
            "email": "admin@doxsnap.com",
            "name": "Platform Admin",
            "hashed_password": hashed_password
        })
        conn.commit()
    print("✓ Default super admin created (admin@doxsnap.com / admin123)")

    print("\n" + "=" * 60)
    print("DATABASE RESET COMPLETE!")
    print("=" * 60)
    print("\nDefault credentials:")
    print("  Platform Admin: admin@doxsnap.com / admin123")
    print("\nPlease restart your FastAPI server.")


if __name__ == "__main__":
    flush_database()
