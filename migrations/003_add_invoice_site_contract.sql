-- Migration: Add site_id and contract_id to processed_images table
-- This allows linking invoices directly to sites and contracts

ALTER TABLE processed_images ADD COLUMN IF NOT EXISTS site_id INTEGER REFERENCES sites(id);
ALTER TABLE processed_images ADD COLUMN IF NOT EXISTS contract_id INTEGER REFERENCES contracts(id);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS ix_processed_images_site_id ON processed_images(site_id);
CREATE INDEX IF NOT EXISTS ix_processed_images_contract_id ON processed_images(contract_id);
