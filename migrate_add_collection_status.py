#!/usr/bin/env python3
"""
Migration: Add collection_status to sales table and reserved_qty to products table
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine, Base
from sqlalchemy import text

def migrate():
    """Run migration to add collection status and reserved quantity."""
    print("Starting migration: Add collection status and reserved quantity...")
    
    with engine.begin() as conn:
        # Check if collection_status column exists in sales table
        result = conn.execute(text("PRAGMA table_info(sales)"))
        columns = [row[1] for row in result.fetchall()]
        
        if 'collection_status' in columns:
            print("✓ collection_status column already exists in sales table")
        else:
            # Add collection_status column to sales table
            print("Adding collection_status column to sales table...")
            conn.execute(text("ALTER TABLE sales ADD COLUMN collection_status VARCHAR(20) DEFAULT 'collected'"))
            print("✓ collection_status column added to sales table")
        
        # Check if reserved_qty column exists in products table
        result = conn.execute(text("PRAGMA table_info(products)"))
        columns = [row[1] for row in result.fetchall()]
        
        if 'reserved_qty' in columns:
            print("✓ reserved_qty column already exists in products table")
        else:
            # Add reserved_qty column to products table
            print("Adding reserved_qty column to products table...")
            conn.execute(text("ALTER TABLE products ADD COLUMN reserved_qty REAL DEFAULT 0.0"))
            print("✓ reserved_qty column added to products table")
    
    print("\n✓ Migration completed successfully!")

if __name__ == "__main__":
    migrate()

