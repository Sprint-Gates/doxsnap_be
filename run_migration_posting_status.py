"""
Migration: Add posting_status column to processed_images table

This script adds the posting_status column to track if invoice items have been posted to inventory.

Run with: python run_migration_posting_status.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.database import SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Add posting_status column to processed_images table"""
    db = SessionLocal()

    try:
        # Check if column already exists
        check_query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'processed_images'
            AND column_name = 'posting_status'
        """)
        result = db.execute(check_query).fetchone()

        if result:
            logger.info("Column 'posting_status' already exists in processed_images table")
            return

        # Add the column
        alter_query = text("""
            ALTER TABLE processed_images
            ADD COLUMN posting_status VARCHAR(50) NULL
        """)
        db.execute(alter_query)
        db.commit()

        logger.info("Successfully added 'posting_status' column to processed_images table")

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()
