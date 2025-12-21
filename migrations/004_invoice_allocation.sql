-- Migration: Invoice Allocation and Cost Distribution
-- This allows subcontractor invoices to be allocated to contracts with cost distributed over time

-- Invoice Allocation table - links invoice to contract with allocation settings
CREATE TABLE IF NOT EXISTS invoice_allocations (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES processed_images(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,

    -- Allocation settings
    total_amount NUMERIC(14, 2) NOT NULL,  -- Total invoice amount to allocate
    distribution_type VARCHAR(20) NOT NULL DEFAULT 'one_time',  -- one_time, monthly, quarterly, custom

    -- For distributed allocations
    start_date DATE,  -- Start of distribution period
    end_date DATE,    -- End of distribution period
    number_of_periods INTEGER DEFAULT 1,  -- Number of periods to distribute over

    -- Status and audit
    status VARCHAR(20) DEFAULT 'active',  -- active, cancelled, completed
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(invoice_id)  -- One allocation per invoice
);

-- Allocation Periods table - individual period amounts for distributed costs
CREATE TABLE IF NOT EXISTS allocation_periods (
    id SERIAL PRIMARY KEY,
    allocation_id INTEGER NOT NULL REFERENCES invoice_allocations(id) ON DELETE CASCADE,

    -- Period details
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    period_number INTEGER NOT NULL,  -- 1, 2, 3, etc.

    -- Amount for this period
    amount NUMERIC(14, 2) NOT NULL,

    -- Recognition status
    is_recognized BOOLEAN DEFAULT FALSE,  -- Whether this period's cost has been recognized/posted
    recognized_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS ix_invoice_allocations_invoice_id ON invoice_allocations(invoice_id);
CREATE INDEX IF NOT EXISTS ix_invoice_allocations_contract_id ON invoice_allocations(contract_id);
CREATE INDEX IF NOT EXISTS ix_invoice_allocations_status ON invoice_allocations(status);
CREATE INDEX IF NOT EXISTS ix_allocation_periods_allocation_id ON allocation_periods(allocation_id);
CREATE INDEX IF NOT EXISTS ix_allocation_periods_period_dates ON allocation_periods(period_start, period_end);
CREATE INDEX IF NOT EXISTS ix_allocation_periods_recognized ON allocation_periods(is_recognized);
