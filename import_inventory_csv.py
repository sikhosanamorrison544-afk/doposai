"""
Import inventory from CSV file into the POS database.

Run:
    cd /home/morrison/Desktop/pos
    source .venv/bin/activate
    python import_inventory_csv.py
"""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Category, Product, InventoryMovement


def get_or_create_category(db: Session, name: str, description: str = "") -> Category:
    """Get existing category or create a new one."""
    if not name or not name.strip():
        return None
    name = name.strip()
    cat = db.query(Category).filter(Category.name == name).first()
    if cat:
        return cat
    cat = Category(name=name, description=description or None)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def parse_decimal(value: str) -> Decimal:
    """Parse a string value to Decimal, handling empty strings and invalid values."""
    if not value or not value.strip():
        return Decimal("0.00")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def parse_float(value: str) -> float:
    """Parse a string value to float, handling empty strings and invalid values.
    Ensures non-negative values (sets negative values to 0).
    """
    if not value or not value.strip():
        return 0.0
    try:
        result = float(str(value).strip())
        # Ensure non-negative (set negative values to 0)
        return max(0.0, result)
    except (ValueError, TypeError):
        return 0.0


def parse_int(value: str) -> int:
    """Parse a string value to int, handling empty strings and invalid values."""
    if not value or not value.strip():
        return 0
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 0


def import_inventory_from_csv(csv_path: str, db: Session) -> dict:
    """Import products from CSV file into database."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    stats = {
        "total_rows": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }

    # Use utf-8-sig to handle BOM (Byte Order Mark) if present
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (row 1 is header)
            stats["total_rows"] += 1
            
            try:
                # Extract data from CSV row
                product_name = row.get("Product name", "").strip()
                product_code = str(row.get("Product code", "")).strip()
                category_name = row.get("Product category", "").strip()
                sub_category = row.get("Product sub category", "").strip()
                avg_cost = parse_decimal(row.get("Average cost", "0"))
                selling_price = parse_decimal(row.get("Selling price", "0"))
                in_hand_stock = parse_float(row.get("In hand stock", "0"))
                
                # Skip rows with no product name
                if not product_name:
                    stats["skipped"] += 1
                    stats["errors"].append(f"Row {row_num}: Missing product name")
                    continue
                
                # Get or create category
                category = None
                if category_name:
                    category = get_or_create_category(db, category_name)
                
                # Handle barcode - use product code if available, but it must be unique
                barcode = product_code if product_code else None
                
                # Check if product already exists (by barcode if available, otherwise by name)
                existing_product = None
                if barcode:
                    existing_product = db.query(Product).filter(Product.barcode == barcode).first()
                else:
                    # Try to find by name if no barcode
                    existing_product = db.query(Product).filter(Product.name == product_name).first()
                
                if existing_product:
                    # Update existing product
                    existing_product.name = product_name
                    existing_product.category_id = category.id if category else None
                    existing_product.cost_price = avg_cost
                    existing_product.selling_price = selling_price
                    
                    # Update stock and create inventory movement if stock changed
                    # Ensure stock_qty is non-negative (set negative values to 0)
                    old_stock = existing_product.stock_qty
                    existing_product.stock_qty = max(0.0, float(in_hand_stock))
                    existing_product.is_active = True
                    
                    # Only update barcode if it's not set and we have a product code
                    if not existing_product.barcode and barcode:
                        # Check if barcode is already used by another product
                        existing_barcode = db.query(Product).filter(
                            Product.barcode == barcode,
                            Product.id != existing_product.id
                        ).first()
                        if not existing_barcode:
                            existing_product.barcode = barcode
                    
                    db.commit()
                    
                    # Create inventory movement if stock changed
                    # Use the non-negative final stock value
                    final_stock = max(0.0, float(in_hand_stock))
                    if old_stock != final_stock:
                        stock_change = final_stock - old_stock
                        movement = InventoryMovement(
                            product_id=existing_product.id,
                            change_qty=stock_change,
                            reason="Stock update (CSV import)",
                        )
                        db.add(movement)
                        db.commit()
                    
                    stats["updated"] += 1
                else:
                    # Create new product - ensure stock_qty is non-negative (set negative values to 0)
                    final_stock = max(0.0, float(in_hand_stock))
                    product = Product(
                        name=product_name,
                        barcode=barcode,
                        category_id=category.id if category else None,
                        stock_qty=final_stock,
                        cost_price=avg_cost,
                        selling_price=selling_price,
                        is_active=True,
                    )
                    db.add(product)
                    db.commit()
                    db.refresh(product)
                    
                    # Create inventory movement for initial stock if stock > 0
                    # Use the non-negative final stock value
                    if final_stock > 0:
                        movement = InventoryMovement(
                            product_id=product.id,
                            change_qty=final_stock,
                            reason="Initial stock (CSV import)",
                        )
                        db.add(movement)
                        db.commit()
                    
                    stats["created"] += 1
                    
            except Exception as e:
                stats["skipped"] += 1
                error_msg = f"Row {row_num}: {str(e)}"
                stats["errors"].append(error_msg)
                print(f"Error processing row {row_num}: {e}")
                db.rollback()
                continue
    
    return stats


def main() -> None:
    """Main entry point."""
    csv_file = "/home/morrison/Downloads/Available-inventory-2025-12-27.csv"
    
    print(f"Importing inventory from: {csv_file}")
    print("=" * 60)
    
    db = SessionLocal()
    try:
        stats = import_inventory_from_csv(csv_file, db)
        
        print("\nImport Summary:")
        print("=" * 60)
        print(f"Total rows processed: {stats['total_rows']}")
        print(f"Products created: {stats['created']}")
        print(f"Products updated: {stats['updated']}")
        print(f"Rows skipped: {stats['skipped']}")
        
        if stats['errors']:
            print(f"\nErrors ({len(stats['errors'])}):")
            for error in stats['errors'][:20]:  # Show first 20 errors
                print(f"  - {error}")
            if len(stats['errors']) > 20:
                print(f"  ... and {len(stats['errors']) - 20} more errors")
        
        print("\nImport complete!")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()

