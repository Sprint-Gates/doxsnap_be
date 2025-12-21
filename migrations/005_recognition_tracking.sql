-- Migration: Enhanced Recognition Tracking for Allocation Periods
-- Adds proper audit trail and documentation requirements for cost recognition

-- Add recognition tracking fields to allocation_periods table
ALTER TABLE allocation_periods ADD COLUMN IF NOT EXISTS recognition_number VARCHAR(20);
ALTER TABLE allocation_periods ADD COLUMN IF NOT EXISTS recognition_reference VARCHAR(100);
ALTER TABLE allocation_periods ADD COLUMN IF NOT EXISTS recognition_notes TEXT;
ALTER TABLE allocation_periods ADD COLUMN IF NOT EXISTS recognized_by INTEGER REFERENCES users(id);

-- Create index on recognition_number for fast lookups
CREATE INDEX IF NOT EXISTS ix_allocation_periods_recognition_number ON allocation_periods(recognition_number);

-- Create recognition_log table for audit trail
CREATE TABLE IF NOT EXISTS recognition_log (
    id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES allocation_periods(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL,  -- 'recognized', 'unrecognized', 'modified'
    recognition_number VARCHAR(20),
    previous_status BOOLEAN,
    new_status BOOLEAN,
    reference VARCHAR(100),
    notes TEXT,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for recognition_log
CREATE INDEX IF NOT EXISTS ix_recognition_log_period_id ON recognition_log(period_id);
CREATE INDEX IF NOT EXISTS ix_recognition_log_user_id ON recognition_log(user_id);
CREATE INDEX IF NOT EXISTS ix_recognition_log_created_at ON recognition_log(created_at);
CREATE INDEX IF NOT EXISTS ix_recognition_log_recognition_number ON recognition_log(recognition_number);

-- Create sequence for recognition numbers if not exists
CREATE SEQUENCE IF NOT EXISTS recognition_number_seq START 1;

-- Function to generate recognition number
CREATE OR REPLACE FUNCTION generate_recognition_number()
RETURNS VARCHAR(20) AS $$
DECLARE
    next_val INTEGER;
    year_str VARCHAR(4);
BEGIN
    SELECT nextval('recognition_number_seq') INTO next_val;
    SELECT TO_CHAR(CURRENT_DATE, 'YYYY') INTO year_str;
    RETURN 'REC-' || year_str || '-' || LPAD(next_val::TEXT, 4, '0');
END;
$$ LANGUAGE plpgsql;
