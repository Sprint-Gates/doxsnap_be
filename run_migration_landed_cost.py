#!/usr/bin/env python3
"""
Run database migration to add Landed Cost / Extra Cost support for Goods Receipts.
This adds:
- goods_receipt_extra_costs table (for freight, duties, port charges, etc.)
- New columns to goods_receipts table (is_import, total_extra_costs, total_landed_cost)
- New columns to goods_receipt_lines table (allocated_extra_cost, landed_unit_cost, landed_total_cost)

Execute this script from the doxsnap_be directory:
    python run_migration_landed_cost.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import engine

# Create the goods_receipt_extra_costs table
create_table_sql = """
-- Create goods_receipt_extra_costs table for import extra costs
CREATE TABLE IF NOT EXISTS goods_receipt_extra_costs (
    id SERIAL PRIMARY KEY,
    goods_receipt_id INTEGER NOT NULL REFERENCES goods_receipts(id) ON DELETE CASCADE,
    cost_type VARCHAR(50) NOT NULL,  -- freight, duty, port_handling, customs, insurance, other
    cost_description VARCHAR(255),
    amount NUMERIC(18, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    vendor_id INTEGER REFERENCES vendors(id),  -- Optional: who charged this cost
    reference_number VARCHAR(100),  -- Bill of lading, customs doc, invoice number
    notes TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for goods_receipt_extra_costs
CREATE INDEX IF NOT EXISTS ix_grn_extra_costs_goods_receipt_id ON goods_receipt_extra_costs(goods_receipt_id);
CREATE INDEX IF NOT EXISTS ix_grn_extra_costs_cost_type ON goods_receipt_extra_costs(cost_type);
CREATE INDEX IF NOT EXISTS ix_grn_extra_costs_vendor_id ON goods_receipt_extra_costs(vendor_id);
"""

# ALTER statements to add new columns
alter_statements = [
    # goods_receipts table - landed cost fields
    "ALTER TABLE goods_receipts ADD COLUMN IF NOT EXISTS is_import BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE goods_receipts ADD COLUMN IF NOT EXISTS total_extra_costs NUMERIC(18, 2) DEFAULT 0;",
    "ALTER TABLE goods_receipts ADD COLUMN IF NOT EXISTS total_landed_cost NUMERIC(18, 2) DEFAULT 0;",

    # goods_receipt_lines table - landed cost allocation fields
    "ALTER TABLE goods_receipt_lines ADD COLUMN IF NOT EXISTS allocated_extra_cost NUMERIC(18, 2) DEFAULT 0;",
    "ALTER TABLE goods_receipt_lines ADD COLUMN IF NOT EXISTS landed_unit_cost NUMERIC(18, 4);",
    "ALTER TABLE goods_receipt_lines ADD COLUMN IF NOT EXISTS landed_total_cost NUMERIC(18, 2);",
]

# Optional: Add default account mappings for landed cost types
default_account_mappings_sql = """
-- Insert default account mappings for landed cost types (if not already exists)
-- These should be configured by the user, but we can add placeholder mappings

-- Note: This assumes accounts_payable mapping exists. User should configure proper accounts.
-- INSERT INTO default_account_mappings (company_id, transaction_type, category, debit_account_id, credit_account_id, description, is_active)
-- SELECT company_id, 'landed_cost_freight', NULL, NULL, credit_account_id, 'Freight costs for imports', TRUE
-- FROM default_account_mappings WHERE transaction_type = 'accounts_payable' AND NOT EXISTS (
--     SELECT 1 FROM default_account_mappings WHERE transaction_type = 'landed_cost_freight'
-- );
"""


def run_migration():
    print("=" * 60)
    print("Landed Cost / Extra Cost Migration")
    print("=" * 60)
    print()

    with engine.connect() as conn:
        # Create extra costs table
        print("1. Creating goods_receipt_extra_costs table...")
        try:
            conn.execute(text(create_table_sql))
            conn.commit()
            print("   ✓ Table created successfully")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("   ✓ Table already exists, skipping...")
            else:
                print(f"   Note: {e}")
            conn.rollback()

        # Add new columns to existing tables
        print("\n2. Adding landed cost columns to goods_receipts and goods_receipt_lines...")
        for stmt in alter_statements:
            try:
                conn.execute(text(stmt))
                conn.commit()
                # Extract table and column name for display
                parts = stmt.split()
                table_name = parts[2]
                col_name = parts[7] if "IF NOT EXISTS" in stmt else parts[5]
                print(f"   ✓ Added {col_name} to {table_name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"   ✓ Column already exists, skipping...")
                else:
                    print(f"   Note: {e}")
                conn.rollback()

        # Verify tables were created
        print("\n3. Verifying migration...")
        try:
            result = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'goods_receipts'
                AND column_name IN ('is_import', 'total_extra_costs', 'total_landed_cost')
            """))
            grn_cols = [row[0] for row in result]
            print(f"   ✓ goods_receipts columns: {', '.join(grn_cols) if grn_cols else 'none found'}")

            result = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'goods_receipt_lines'
                AND column_name IN ('allocated_extra_cost', 'landed_unit_cost', 'landed_total_cost')
            """))
            line_cols = [row[0] for row in result]
            print(f"   ✓ goods_receipt_lines columns: {', '.join(line_cols) if line_cols else 'none found'}")

            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'goods_receipt_extra_costs'
                )
            """))
            table_exists = result.scalar()
            print(f"   ✓ goods_receipt_extra_costs table: {'exists' if table_exists else 'not found'}")

        except Exception as e:
            print(f"   Verification note: {e}")

    print("\n" + "=" * 60)
    print("Migration completed!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Restart your FastAPI server")
    print("2. Configure account mappings for landed cost types:")
    print("   - landed_cost_freight")
    print("   - landed_cost_duty")
    print("   - landed_cost_port_handling")
    print("   - landed_cost_customs")
    print("   - landed_cost_insurance")
    print("   - landed_cost_other")
    print()
    print("API Endpoints available:")
    print("   GET    /goods-receipts/{grn_id}/extra-costs")
    print("   POST   /goods-receipts/{grn_id}/extra-costs")
    print("   PUT    /goods-receipts/{grn_id}/extra-costs/{cost_id}")
    print("   DELETE /goods-receipts/{grn_id}/extra-costs/{cost_id}")
    print("   POST   /goods-receipts/{grn_id}/recalculate-landed-costs")
    print("   GET    /goods-receipts/{grn_id}/landed-cost-summary")
    print("   PUT    /goods-receipts/{grn_id}/mark-as-import")
    print("   GET    /goods-receipts/extra-cost-types")
    print()


if __name__ == "__main__":
    run_migration()
