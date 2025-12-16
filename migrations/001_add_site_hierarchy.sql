-- Migration: Add Site/Building/Space hierarchy and update Equipment for flexible parent assignment
-- Run this script to update your database schema

-- ============================================================================
-- 1. Create new tables for the site hierarchy
-- ============================================================================

-- Sites table
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

CREATE INDEX IF NOT EXISTS ix_sites_client_id ON sites(client_id);
CREATE INDEX IF NOT EXISTS ix_sites_code ON sites(code);

-- Buildings table
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

CREATE INDEX IF NOT EXISTS ix_buildings_site_id ON buildings(site_id);
CREATE INDEX IF NOT EXISTS ix_buildings_code ON buildings(code);

-- Spaces table
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

CREATE INDEX IF NOT EXISTS ix_spaces_building_id ON spaces(building_id);
CREATE INDEX IF NOT EXISTS ix_spaces_code ON spaces(code);

-- ============================================================================
-- 2. Create Contract management tables
-- ============================================================================

-- Scopes reference table
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

CREATE INDEX IF NOT EXISTS ix_scopes_company_id ON scopes(company_id);

-- Contracts table
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

CREATE INDEX IF NOT EXISTS ix_contracts_company_id ON contracts(company_id);
CREATE INDEX IF NOT EXISTS ix_contracts_client_id ON contracts(client_id);
CREATE INDEX IF NOT EXISTS ix_contracts_contract_number ON contracts(contract_number);

-- Contract-Site association table
CREATE TABLE IF NOT EXISTS contract_sites (
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (contract_id, site_id)
);

-- Contract Scopes (SLA per scope)
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

CREATE INDEX IF NOT EXISTS ix_contract_scopes_contract_id ON contract_scopes(contract_id);
CREATE INDEX IF NOT EXISTS ix_contract_scopes_scope_id ON contract_scopes(scope_id);

-- Operator-Site association table
CREATE TABLE IF NOT EXISTS operator_sites (
    user_id INTEGER NOT NULL REFERENCES users(id),
    site_id INTEGER NOT NULL REFERENCES sites(id),
    assigned_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, site_id)
);

-- ============================================================================
-- 3. Update Equipment table for flexible parent assignment
-- ============================================================================

-- Add new columns to equipment table (if they don't exist)
DO $$
BEGIN
    -- Add client_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'equipment' AND column_name = 'client_id') THEN
        ALTER TABLE equipment ADD COLUMN client_id INTEGER REFERENCES clients(id);
    END IF;

    -- Add site_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'equipment' AND column_name = 'site_id') THEN
        ALTER TABLE equipment ADD COLUMN site_id INTEGER REFERENCES sites(id);
    END IF;

    -- Add building_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'equipment' AND column_name = 'building_id') THEN
        ALTER TABLE equipment ADD COLUMN building_id INTEGER REFERENCES buildings(id);
    END IF;

    -- Add space_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'equipment' AND column_name = 'space_id') THEN
        ALTER TABLE equipment ADD COLUMN space_id INTEGER REFERENCES spaces(id);
    END IF;
END $$;

-- ============================================================================
-- 4. Update SubEquipment table for flexible parent assignment
-- ============================================================================

DO $$
BEGIN
    -- Add client_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'sub_equipment' AND column_name = 'client_id') THEN
        ALTER TABLE sub_equipment ADD COLUMN client_id INTEGER REFERENCES clients(id);
    END IF;

    -- Add site_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'sub_equipment' AND column_name = 'site_id') THEN
        ALTER TABLE sub_equipment ADD COLUMN site_id INTEGER REFERENCES sites(id);
    END IF;

    -- Add building_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'sub_equipment' AND column_name = 'building_id') THEN
        ALTER TABLE sub_equipment ADD COLUMN building_id INTEGER REFERENCES buildings(id);
    END IF;

    -- Add space_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'sub_equipment' AND column_name = 'space_id') THEN
        ALTER TABLE sub_equipment ADD COLUMN space_id INTEGER REFERENCES spaces(id);
    END IF;

    -- Add floor_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'sub_equipment' AND column_name = 'floor_id') THEN
        ALTER TABLE sub_equipment ADD COLUMN floor_id INTEGER REFERENCES floors(id);
    END IF;

    -- Add room_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'sub_equipment' AND column_name = 'room_id') THEN
        ALTER TABLE sub_equipment ADD COLUMN room_id INTEGER REFERENCES rooms(id);
    END IF;
END $$;

-- ============================================================================
-- 5. Update Floors table to reference Building instead of Branch
-- ============================================================================

DO $$
BEGIN
    -- Add building_id if not exists
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'floors' AND column_name = 'building_id') THEN
        ALTER TABLE floors ADD COLUMN building_id INTEGER REFERENCES buildings(id);
    END IF;

    -- Make branch_id nullable if it exists (for backward compatibility during migration)
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'floors' AND column_name = 'branch_id') THEN
        ALTER TABLE floors ALTER COLUMN branch_id DROP NOT NULL;
    END IF;
END $$;

-- ============================================================================
-- Done! Your database schema is now updated.
-- ============================================================================
