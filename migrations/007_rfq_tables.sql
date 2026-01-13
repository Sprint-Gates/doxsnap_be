-- RFQ (Request for Quotation) System Tables
-- Migration: 007_rfq_tables.sql
-- Created: 2026-01-13

-- =============================================================================
-- Main RFQ Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS request_for_quotations (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    rfq_number VARCHAR(50) UNIQUE NOT NULL,

    -- Type and Status
    rfq_type VARCHAR(50) NOT NULL,  -- 'spare_parts' or 'subcontractor_service'
    status VARCHAR(50) DEFAULT 'draft',  -- draft, submitted, quote_pending, comparison, converted_to_pr, cancelled
    priority VARCHAR(20) DEFAULT 'normal',  -- low, normal, high, urgent

    -- Source linkage
    project_id INTEGER REFERENCES projects(id),
    site_id INTEGER REFERENCES sites(id),
    work_order_id INTEGER REFERENCES work_orders(id),

    -- Details
    title VARCHAR(255) NOT NULL,
    description TEXT,
    required_date DATE,
    currency VARCHAR(3) DEFAULT 'USD',
    estimated_budget NUMERIC(12, 2),

    -- Audit - Creation
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Audit - Submission
    submitted_at TIMESTAMP,
    submitted_by INTEGER REFERENCES users(id),

    -- Audit - Cancellation
    cancelled_at TIMESTAMP,
    cancelled_by INTEGER REFERENCES users(id),
    cancellation_reason TEXT,

    -- Conversion tracking
    converted_to_pr_at TIMESTAMP,
    converted_by INTEGER REFERENCES users(id),

    -- Soft delete
    deleted_at TIMESTAMP,

    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_rfq_company_status ON request_for_quotations(company_id, status);
CREATE INDEX IF NOT EXISTS idx_rfq_created_by ON request_for_quotations(created_by);
CREATE INDEX IF NOT EXISTS idx_rfq_project_site ON request_for_quotations(project_id, site_id);
CREATE INDEX IF NOT EXISTS idx_rfq_number ON request_for_quotations(rfq_number);

-- =============================================================================
-- RFQ Items Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_items (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,

    -- Item reference
    item_id INTEGER REFERENCES item_master(id),
    item_number VARCHAR(100),
    description VARCHAR(500) NOT NULL,

    -- Quantities
    quantity_requested NUMERIC(10, 2) NOT NULL,
    unit VARCHAR(20) DEFAULT 'EA',

    -- Budget estimation
    estimated_unit_cost NUMERIC(12, 2),
    estimated_total NUMERIC(12, 2),

    -- For subcontractor_service type
    service_scope TEXT,
    visit_date DATE,
    visit_location VARCHAR(255),

    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rfq_items_rfq ON rfq_items(rfq_id);

-- =============================================================================
-- RFQ Vendors Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_vendors (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,
    address_book_id INTEGER NOT NULL REFERENCES address_book(id),

    -- Contact tracking
    contact_method VARCHAR(50),
    contact_date TIMESTAMP,
    contacted_by INTEGER REFERENCES users(id),
    is_contacted BOOLEAN DEFAULT FALSE,

    -- Selection
    is_selected BOOLEAN DEFAULT FALSE,
    selection_reason TEXT,

    vendor_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rfq_vendors_rfq ON rfq_vendors(rfq_id);
CREATE INDEX IF NOT EXISTS idx_rfq_vendors_address_book ON rfq_vendors(address_book_id);

-- =============================================================================
-- RFQ Quotes Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_quotes (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,
    rfq_vendor_id INTEGER NOT NULL REFERENCES rfq_vendors(id) ON DELETE CASCADE,

    -- Quote details from vendor
    vendor_quote_number VARCHAR(100),
    quote_date DATE NOT NULL,
    validity_date DATE,

    -- Totals
    subtotal NUMERIC(12, 2) DEFAULT 0,
    tax_amount NUMERIC(12, 2) DEFAULT 0,
    quote_total NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',

    -- Terms
    delivery_days INTEGER,
    delivery_date DATE,
    payment_terms VARCHAR(100),
    warranty_terms VARCHAR(255),

    -- Status
    status VARCHAR(50) DEFAULT 'received',  -- received, under_review, selected, rejected
    rejection_reason TEXT,

    -- Attached quote document
    document_id INTEGER REFERENCES processed_images(id),

    -- Evaluation score (0-100)
    evaluation_score NUMERIC(5, 2),
    evaluation_notes TEXT,

    -- Audit
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    received_by INTEGER NOT NULL REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_rfq_quotes_rfq ON rfq_quotes(rfq_id);
CREATE INDEX IF NOT EXISTS idx_rfq_quotes_vendor ON rfq_quotes(rfq_vendor_id);

-- =============================================================================
-- RFQ Quote Lines Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_quote_lines (
    id SERIAL PRIMARY KEY,
    rfq_quote_id INTEGER NOT NULL REFERENCES rfq_quotes(id) ON DELETE CASCADE,
    rfq_item_id INTEGER REFERENCES rfq_items(id),

    -- Item details
    item_description VARCHAR(500) NOT NULL,
    quantity_quoted NUMERIC(10, 2) NOT NULL,
    unit VARCHAR(20) DEFAULT 'EA',
    unit_price NUMERIC(12, 2) NOT NULL,
    total_price NUMERIC(12, 2) NOT NULL,

    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_rfq_quote_lines_quote ON rfq_quote_lines(rfq_quote_id);
CREATE INDEX IF NOT EXISTS idx_rfq_quote_lines_item ON rfq_quote_lines(rfq_item_id);

-- =============================================================================
-- RFQ Audit Trail Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_audit_trail (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,

    -- What happened
    action VARCHAR(50) NOT NULL,
    action_category VARCHAR(30),

    -- Who did it
    action_by INTEGER NOT NULL REFERENCES users(id),
    action_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- Change tracking
    old_value TEXT,
    new_value TEXT,

    -- Additional context (JSON)
    details TEXT,

    -- For compliance
    ip_address VARCHAR(45),
    user_agent VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_rfq_audit_rfq ON rfq_audit_trail(rfq_id);
CREATE INDEX IF NOT EXISTS idx_rfq_audit_action ON rfq_audit_trail(rfq_id, action);
CREATE INDEX IF NOT EXISTS idx_rfq_audit_time ON rfq_audit_trail(action_at DESC);

-- =============================================================================
-- RFQ Site Visits Table (for subcontractor_service type)
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_site_visits (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL UNIQUE REFERENCES request_for_quotations(id) ON DELETE CASCADE,

    -- Scheduling
    scheduled_date DATE,
    scheduled_time TIME,
    actual_date DATE,
    actual_time TIME,

    -- Status
    visit_status VARCHAR(50) DEFAULT 'pending',  -- pending, scheduled, completed, rescheduled, cancelled

    -- Site contact
    site_contact_person VARCHAR(255),
    site_contact_phone VARCHAR(50),
    site_contact_email VARCHAR(255),

    -- Visit details
    visit_notes TEXT,
    issues_identified TEXT,
    recommendations TEXT,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_by INTEGER REFERENCES users(id),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rfq_site_visits_rfq ON rfq_site_visits(rfq_id);

-- =============================================================================
-- RFQ Site Visit Photos Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_site_visit_photos (
    id SERIAL PRIMARY KEY,
    site_visit_id INTEGER NOT NULL REFERENCES rfq_site_visits(id) ON DELETE CASCADE,

    -- Photo reference
    image_id INTEGER NOT NULL REFERENCES processed_images(id),

    caption VARCHAR(255),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by INTEGER NOT NULL REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_rfq_site_visit_photos_visit ON rfq_site_visit_photos(site_visit_id);

-- =============================================================================
-- RFQ Comparisons Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_comparisons (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL UNIQUE REFERENCES request_for_quotations(id) ON DELETE CASCADE,

    -- Status
    comparison_status VARCHAR(50) DEFAULT 'pending',  -- pending, in_progress, complete

    -- Evaluation criteria (JSON array)
    evaluation_criteria TEXT,

    -- Recommendation
    recommended_vendor_id INTEGER REFERENCES rfq_vendors(id),
    recommendation_notes TEXT,

    -- Evaluator notes
    evaluator_notes TEXT,

    -- Audit
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    completed_by INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_rfq_comparisons_rfq ON rfq_comparisons(rfq_id);

-- =============================================================================
-- RFQ Documents Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS rfq_documents (
    id SERIAL PRIMARY KEY,
    rfq_id INTEGER NOT NULL REFERENCES request_for_quotations(id) ON DELETE CASCADE,

    -- Document reference
    image_id INTEGER NOT NULL REFERENCES processed_images(id),

    -- Document type
    document_type VARCHAR(50),  -- specification, drawing, requirement, other
    title VARCHAR(255),
    description TEXT,

    -- Audit
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by INTEGER NOT NULL REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_rfq_documents_rfq ON rfq_documents(rfq_id);

-- =============================================================================
-- Add rfq_id to Purchase Requests (link RFQ to PR)
-- =============================================================================
ALTER TABLE purchase_requests
ADD COLUMN IF NOT EXISTS rfq_id INTEGER REFERENCES request_for_quotations(id);

CREATE INDEX IF NOT EXISTS idx_pr_rfq ON purchase_requests(rfq_id);

-- =============================================================================
-- Comments
-- =============================================================================
COMMENT ON TABLE request_for_quotations IS 'Request for Quotation - Request for vendor quotes before purchasing';
COMMENT ON TABLE rfq_items IS 'RFQ Line Items - Individual items/services requested in an RFQ';
COMMENT ON TABLE rfq_vendors IS 'RFQ Vendors - Vendors to contact for quotes';
COMMENT ON TABLE rfq_quotes IS 'RFQ Quotes - Vendor quotes received for an RFQ';
COMMENT ON TABLE rfq_quote_lines IS 'RFQ Quote Lines - Individual line items in a vendor quote';
COMMENT ON TABLE rfq_audit_trail IS 'RFQ Audit Trail - Complete history of all actions on an RFQ';
COMMENT ON TABLE rfq_site_visits IS 'RFQ Site Visits - For subcontractor service type RFQs';
COMMENT ON TABLE rfq_site_visit_photos IS 'RFQ Site Visit Photos - Photos taken during site visit';
COMMENT ON TABLE rfq_comparisons IS 'RFQ Comparisons - Quote comparison and evaluation matrix';
COMMENT ON TABLE rfq_documents IS 'RFQ Documents - Documents attached to an RFQ';
