#!/usr/bin/env python3
"""
Database migration script to add notification and low-stock fields.
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
    """Add new columns for notifications and low-stock thresholds."""
    
    db = SessionLocal()
    try:
        logger.info("Starting database migration...")
        
        # Check and add columns to store_settings table
        logger.info("Checking store_settings table...")
        
        # Get current columns
        result = db.execute(text("PRAGMA table_info(store_settings)"))
        columns = [row[1] for row in result]
        logger.info(f"Current columns: {columns}")
        
        # Add notification_email column if it doesn't exist
        if 'notification_email' not in columns:
            logger.info("Adding notification_email column...")
            db.execute(text("ALTER TABLE store_settings ADD COLUMN notification_email VARCHAR(200)"))
            db.commit()
            logger.info("✅ Added notification_email column")
        else:
            logger.info("✓ notification_email column already exists")
        
        # Add low_stock_email_enabled column if it doesn't exist
        if 'low_stock_email_enabled' not in columns:
            logger.info("Adding low_stock_email_enabled column...")
            db.execute(text("ALTER TABLE store_settings ADD COLUMN low_stock_email_enabled BOOLEAN DEFAULT 0"))
            db.commit()
            logger.info("✅ Added low_stock_email_enabled column")
        else:
            logger.info("✓ low_stock_email_enabled column already exists")
        
        # Add default_low_stock_threshold column if it doesn't exist
        if 'default_low_stock_threshold' not in columns:
            logger.info("Adding default_low_stock_threshold column...")
            db.execute(text("ALTER TABLE store_settings ADD COLUMN default_low_stock_threshold FLOAT DEFAULT 10.0"))
            db.commit()
            logger.info("✅ Added default_low_stock_threshold column")
        else:
            logger.info("✓ default_low_stock_threshold column already exists")
        
        # Check and add columns to products table
        logger.info("Checking products table...")
        result = db.execute(text("PRAGMA table_info(products)"))
        product_columns = [row[1] for row in result]
        logger.info(f"Current product columns: {product_columns}")
        
        # Add low_stock_threshold column if it doesn't exist
        if 'low_stock_threshold' not in product_columns:
            logger.info("Adding low_stock_threshold column to products...")
            db.execute(text("ALTER TABLE products ADD COLUMN low_stock_threshold FLOAT"))
            db.commit()
            logger.info("✅ Added low_stock_threshold column to products")
        else:
            logger.info("✓ low_stock_threshold column already exists in products")
        
        # Check if notifications table exists, create if not
        logger.info("Checking notifications table...")
        result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'"))
        if result.fetchone() is None:
            logger.info("Creating notifications table...")
            db.execute(text("""
                CREATE TABLE notifications (
                    id INTEGER NOT NULL PRIMARY KEY,
                    type VARCHAR(50) NOT NULL,
                    message TEXT NOT NULL,
                    product_id INTEGER,
                    is_read BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products (id)
                )
            """))
            db.execute(text("CREATE INDEX ix_notifications_type ON notifications (type)"))
            db.execute(text("CREATE INDEX ix_notifications_product_id ON notifications (product_id)"))
            db.execute(text("CREATE INDEX ix_notifications_is_read ON notifications (is_read)"))
            db.execute(text("CREATE INDEX ix_notifications_created_at ON notifications (created_at)"))
            db.commit()
            logger.info("✅ Created notifications table")
        else:
            logger.info("✓ notifications table already exists")
        
        logger.info("✅ Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Database Migration: Add Notification Fields")
    print("=" * 60)
    print()
    
    try:
        migrate_database()
        print()
        print("✅ Migration completed successfully!")
        print("You can now use the notification features.")
    except Exception as e:
        print()
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

