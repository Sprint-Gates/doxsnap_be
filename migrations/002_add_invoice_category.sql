-- Migration: Add invoice_category column to processed_images table
-- This column distinguishes between Service Invoices (subcontractor) and Spare Parts Invoices

-- Add invoice_category column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'processed_images' AND column_name = 'invoice_category') THEN
        ALTER TABLE processed_images ADD COLUMN invoice_category VARCHAR;
    END IF;
END $$;

-- Optional: Create an index for faster filtering by invoice category
CREATE INDEX IF NOT EXISTS ix_processed_images_invoice_category ON processed_images(invoice_category);
