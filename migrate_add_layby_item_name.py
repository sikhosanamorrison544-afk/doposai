#!/usr/bin/env python3
"""Migration script to add layby_item_name column to layby_customers table."""

from app.database import engine
from sqlalchemy import text

def migrate():
    """Add layby_item_name column to layby_customers table."""
    try:
        with engine.connect() as conn:
            # For SQLite, we'll try to add the column and catch the error if it exists
            try:
                conn.execute(text("""
                    ALTER TABLE layby_customers 
                    ADD COLUMN layby_item_name VARCHAR(200)
                """))
                conn.commit()
                print("✅ Successfully added 'layby_item_name' column to 'layby_customers' table.")
            except Exception as add_error:
                # Check if error is because column already exists
                error_msg = str(add_error).lower()
                if 'duplicate column' in error_msg or 'already exists' in error_msg:
                    print("Column 'layby_item_name' already exists. Skipping migration.")
                else:
                    # Try to check if column exists using PRAGMA (SQLite specific)
                    try:
                        result = conn.execute(text("PRAGMA table_info(layby_customers)"))
                        columns = [row[1] for row in result.fetchall()]
                        if 'layby_item_name' in columns:
                            print("Column 'layby_item_name' already exists. Skipping migration.")
                        else:
                            raise add_error
                    except:
                        raise add_error
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        raise

if __name__ == "__main__":
    migrate()

