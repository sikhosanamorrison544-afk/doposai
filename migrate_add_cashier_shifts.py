#!/usr/bin/env python3
"""
Migration: Add cashier shifts table and shift_id to sales table
"""
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine, Base
from app.models import CashierShift, Sale
from sqlalchemy import text

def migrate():
    """Run migration to add cashier shifts."""
    print("Starting migration: Add cashier shifts...")
    
    with engine.begin() as conn:  # Use begin() for automatic transaction management
        # Check if cashier_shifts table exists
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='cashier_shifts'
        """))
        if result.fetchone():
            print("✓ cashier_shifts table already exists")
        else:
            # Create cashier_shifts table
            print("Creating cashier_shifts table...")
            CashierShift.__table__.create(engine, checkfirst=True)
            print("✓ cashier_shifts table created")
        
        # Check if shift_id column exists in sales table
        result = conn.execute(text("PRAGMA table_info(sales)"))
        columns = [row[1] for row in result.fetchall()]
        
        if 'shift_id' in columns:
            print("✓ shift_id column already exists in sales table")
        else:
            # Add shift_id column to sales table
            print("Adding shift_id column to sales table...")
            conn.execute(text("ALTER TABLE sales ADD COLUMN shift_id INTEGER"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_shift_id ON sales(shift_id)"))
            # commit() is automatic with begin() context manager
            print("✓ shift_id column added to sales table")
    
    print("\n✓ Migration completed successfully!")

if __name__ == "__main__":
    migrate()

