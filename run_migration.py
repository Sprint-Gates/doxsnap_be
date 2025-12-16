#!/usr/bin/env python3
"""
Run database migration to add Site hierarchy and update Equipment model.
Execute this script from the doxsnap_be directory:
    python run_migration.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import engine

migration_sql = """
-- 1. Create Sites table
CREATE TABLE IF NOT EXISTS sites (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    name VARCHAR NOT NULL,
    code VARCHAR,
    address VARCHAR,
    city VARCHAR,
    country VARCHAR,
    latitude FLOAT,
    longitude FLOAT,
    contact_name VARCHAR,
    contact_phone VARCHAR,
    contact_email VARCHAR,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 2. Create Buildings table
CREATE TABLE IF NOT EXISTS buildings (
    id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    code VARCHAR,
    description TEXT,
    building_type VARCHAR,
    address VARCHAR,
    floors_count INTEGER,
    year_built INTEGER,
    total_area FLOAT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 3. Create Spaces table
CREATE TABLE IF NOT EXISTS spaces (
    id SERIAL PRIMARY KEY,
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    code VARCHAR,
    space_type VARCHAR,
    area FLOAT,
    capacity INTEGER,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 4. Create Scopes reference table
CREATE TABLE IF NOT EXISTS scopes (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    name VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    description TEXT,
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 5. Create Contracts table
CREATE TABLE IF NOT EXISTS contracts (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    contract_number VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description TEXT,
    contract_type VARCHAR NOT NULL DEFAULT 'comprehensive',
    threshold_amount NUMERIC(15,2),
    threshold_period VARCHAR,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    contract_value NUMERIC(15,2),
    budget NUMERIC(15,2),
    currency VARCHAR DEFAULT 'USD',
    status VARCHAR DEFAULT 'draft',
    is_renewable BOOLEAN DEFAULT FALSE,
    renewal_notice_days INTEGER,
    auto_renew BOOLEAN DEFAULT FALSE,
    document_url VARCHAR,
    notes TEXT,
    terms_conditions TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 6. Create Contract-Sites association
CREATE TABLE IF NOT EXISTS contract_sites (
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (contract_id, site_id)
);

-- 7. Create Contract Scopes table
CREATE TABLE IF NOT EXISTS contract_scopes (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    scope_id INTEGER NOT NULL REFERENCES scopes(id),
    allocated_budget NUMERIC(15,2),
    sla_response_time_hours INTEGER,
    sla_response_time_priority_low INTEGER,
    sla_response_time_priority_medium INTEGER,
    sla_response_time_priority_high INTEGER,
    sla_response_time_priority_critical INTEGER,
    sla_resolution_time_hours INTEGER,
    sla_resolution_time_priority_low INTEGER,
    sla_resolution_time_priority_medium INTEGER,
    sla_resolution_time_priority_high INTEGER,
    sla_resolution_time_priority_critical INTEGER,
    sla_availability_percent NUMERIC(5,2),
    sla_penalty_response_breach NUMERIC(15,2),
    sla_penalty_resolution_breach NUMERIC(15,2),
    sla_penalty_availability_breach NUMERIC(15,2),
    sla_penalty_calculation VARCHAR,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 8. Create Operator-Sites association
CREATE TABLE IF NOT EXISTS operator_sites (
    user_id INTEGER NOT NULL REFERENCES users(id),
    site_id INTEGER NOT NULL REFERENCES sites(id),
    assigned_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, site_id)
);
"""

# Separate ALTER statements to add columns
alter_statements = [
    # Equipment table columns
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS client_id INTEGER REFERENCES clients(id);",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id);",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS building_id INTEGER REFERENCES buildings(id);",
    "ALTER TABLE equipment ADD COLUMN IF NOT EXISTS space_id INTEGER REFERENCES spaces(id);",

    # SubEquipment table columns
    "ALTER TABLE sub_equipment ADD COLUMN IF NOT EXISTS client_id INTEGER REFERENCES clients(id);",
    "ALTER TABLE sub_equipment ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id);",
    "ALTER TABLE sub_equipment ADD COLUMN IF NOT EXISTS building_id INTEGER REFERENCES buildings(id);",
    "ALTER TABLE sub_equipment ADD COLUMN IF NOT EXISTS space_id INTEGER REFERENCES spaces(id);",
    "ALTER TABLE sub_equipment ADD COLUMN IF NOT EXISTS floor_id INTEGER REFERENCES floors(id);",
    "ALTER TABLE sub_equipment ADD COLUMN IF NOT EXISTS room_id INTEGER REFERENCES rooms(id);",

    # Floors table - add building_id
    "ALTER TABLE floors ADD COLUMN IF NOT EXISTS building_id INTEGER REFERENCES buildings(id);",
]

def run_migration():
    print("Starting database migration...")

    with engine.connect() as conn:
        # Run main table creation
        print("Creating new tables...")
        try:
            conn.execute(text(migration_sql))
            conn.commit()
            print("✓ Tables created successfully")
        except Exception as e:
            print(f"Note: {e}")
            conn.rollback()

        # Run ALTER statements one by one
        print("\nAdding new columns to existing tables...")
        for stmt in alter_statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
                col_name = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split(" ")[0]
                table_name = stmt.split("ALTER TABLE ")[1].split(" ")[0]
                print(f"✓ Added {col_name} to {table_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"  Column already exists, skipping...")
                else:
                    print(f"  Note: {e}")
                conn.rollback()

        # Create indexes
        print("\nCreating indexes...")
        indexes = [
            "CREATE INDEX IF NOT EXISTS ix_sites_client_id ON sites(client_id);",
            "CREATE INDEX IF NOT EXISTS ix_sites_code ON sites(code);",
            "CREATE INDEX IF NOT EXISTS ix_buildings_site_id ON buildings(site_id);",
            "CREATE INDEX IF NOT EXISTS ix_buildings_code ON buildings(code);",
            "CREATE INDEX IF NOT EXISTS ix_spaces_building_id ON spaces(building_id);",
            "CREATE INDEX IF NOT EXISTS ix_spaces_code ON spaces(code);",
            "CREATE INDEX IF NOT EXISTS ix_scopes_company_id ON scopes(company_id);",
            "CREATE INDEX IF NOT EXISTS ix_contracts_company_id ON contracts(company_id);",
            "CREATE INDEX IF NOT EXISTS ix_contracts_client_id ON contracts(client_id);",
            "CREATE INDEX IF NOT EXISTS ix_contract_scopes_contract_id ON contract_scopes(contract_id);",
        ]
        for idx in indexes:
            try:
                conn.execute(text(idx))
                conn.commit()
            except Exception as e:
                conn.rollback()
        print("✓ Indexes created")

    print("\n" + "="*50)
    print("Migration completed successfully!")
    print("Please restart your FastAPI server.")
    print("="*50)

if __name__ == "__main__":
    run_migration()
