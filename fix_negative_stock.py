#!/usr/bin/env python3
"""
Script to fix negative stock quantities in the database.
Sets all negative stock_qty values to 0.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal
from app.models import Product

def fix_negative_stock():
    """Fix all products with negative stock_qty by setting them to 0."""
    db = SessionLocal()
    try:
        # Find all products with negative stock
        negative_stock_products = db.query(Product).filter(Product.stock_qty < 0).all()
        
        if not negative_stock_products:
            print("No products with negative stock found.")
            return
        
        print(f"Found {len(negative_stock_products)} products with negative stock:")
        for product in negative_stock_products:
            print(f"  - {product.name} (ID: {product.id}): {product.stock_qty} -> 0")
            product.stock_qty = 0.0
        
        db.commit()
        print(f"\nSuccessfully fixed {len(negative_stock_products)} products.")
        
    except Exception as e:
        db.rollback()
        print(f"Error fixing negative stock: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    fix_negative_stock()

