-- Migration: Expanded Allocation Types (Sites & Projects)
-- Adds ability to allocate invoices to sites and projects in addition to contracts

-- Make contract_id nullable (was NOT NULL before, now one of contract/site/project must be set)
ALTER TABLE invoice_allocations ALTER COLUMN contract_id DROP NOT NULL;

-- Add site_id column to invoice_allocations table
ALTER TABLE invoice_allocations ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id);

-- Add project_id column to invoice_allocations table
ALTER TABLE invoice_allocations ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id);

-- Add allocation_type column (contract, site, project)
ALTER TABLE invoice_allocations ADD COLUMN IF NOT EXISTS allocation_type VARCHAR(20) DEFAULT 'contract';

-- Update existing allocations to have allocation_type = 'contract'
UPDATE invoice_allocations SET allocation_type = 'contract' WHERE allocation_type IS NULL AND contract_id IS NOT NULL;

-- Create indexes for new columns
CREATE INDEX IF NOT EXISTS ix_invoice_allocations_site_id ON invoice_allocations(site_id);
CREATE INDEX IF NOT EXISTS ix_invoice_allocations_project_id ON invoice_allocations(project_id);
CREATE INDEX IF NOT EXISTS ix_invoice_allocations_allocation_type ON invoice_allocations(allocation_type);

-- Add check constraint to ensure exactly one target is set
-- Note: PostgreSQL allows NULL values to pass check constraints, so we also need to validate in application
ALTER TABLE invoice_allocations DROP CONSTRAINT IF EXISTS chk_allocation_target;
ALTER TABLE invoice_allocations ADD CONSTRAINT chk_allocation_target CHECK (
    (contract_id IS NOT NULL AND site_id IS NULL AND project_id IS NULL) OR
    (contract_id IS NULL AND site_id IS NOT NULL AND project_id IS NULL) OR
    (contract_id IS NULL AND site_id IS NULL AND project_id IS NOT NULL)
);
