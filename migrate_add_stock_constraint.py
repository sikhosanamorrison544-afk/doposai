#!/usr/bin/env python3
"""
Migration script to add CHECK constraint for stock_qty >= 0.
SQLite doesn't support adding CHECK constraints to existing tables easily,
so we'll create a trigger to enforce it instead.
"""

from app.database import engine
from sqlalchemy import text

def migrate():
    """Add trigger to enforce stock_qty >= 0 constraint."""
    try:
        with engine.connect() as conn:
            # Check if trigger already exists
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='trigger' AND name='check_stock_qty_non_negative'
            """))
            if result.fetchone():
                print("Trigger 'check_stock_qty_non_negative' already exists. Skipping migration.")
                return
            
            # Create trigger to enforce stock_qty >= 0
            conn.execute(text("""
                CREATE TRIGGER check_stock_qty_non_negative
                BEFORE UPDATE OF stock_qty ON products
                FOR EACH ROW
                WHEN NEW.stock_qty < 0
                BEGIN
                    SELECT RAISE(ABORT, 'Stock quantity cannot be negative');
                END
            """))
            
            # Also create trigger for INSERT
            conn.execute(text("""
                CREATE TRIGGER check_stock_qty_non_negative_insert
                BEFORE INSERT ON products
                FOR EACH ROW
                WHEN NEW.stock_qty < 0
                BEGIN
                    SELECT RAISE(ABORT, 'Stock quantity cannot be negative');
                END
            """))
            
            conn.commit()
            print("✅ Successfully added triggers to enforce stock_qty >= 0 constraint.")
            
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        raise

if __name__ == "__main__":
    migrate()

