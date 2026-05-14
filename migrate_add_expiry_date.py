#!/usr/bin/env python3
"""
Database migration script to add expiry_date column to products table.
Run this once to update your database schema.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, SessionLocal
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database():
    """Add expiry_date column to products table."""
    
    db = SessionLocal()
    try:
        logger.info("Starting database migration...")
        logger.info("Adding expiry_date column to products table...")
        
        # Check if column already exists
        result = db.execute(text("PRAGMA table_info(products)"))
        columns = [row[1] for row in result]
        logger.info(f"Current columns: {columns}")
        
        # Add expiry_date column if it doesn't exist
        if 'expiry_date' not in columns:
            logger.info("Adding expiry_date column...")
            db.execute(text("ALTER TABLE products ADD COLUMN expiry_date DATE"))
            db.commit()
            logger.info("✅ Added expiry_date column to products table")
        else:
            logger.info("✓ expiry_date column already exists")
        
        logger.info("✅ Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    try:
        migrate_database()
        print("\n✅ Migration completed successfully!")
        print("You can now use expiry dates for products.")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)


