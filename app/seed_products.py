"""
Seed the database with example products and stock.

Run:
    cd /home/morrison/Desktop/pos
    source .venv/bin/activate
    python -m app.seed_products
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Category, Product, InventoryMovement


def get_or_create_category(db: Session, name: str, description: str = "") -> Category:
    cat = db.query(Category).filter(Category.name == name).first()
    if cat:
        return cat
    cat = Category(name=name, description=description or None)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def seed(db: Session) -> None:
    kitchen = get_or_create_category(db, "Kitchenware", "Pots, pans, utensils")
    solar = get_or_create_category(db, "Solar Equipment", "Panels, batteries, inverters")

    products = [
        # Kitchenware
        dict(
            name="Stainless Steel Cooking Pot 5L",
            barcode="KW001",
            category_id=kitchen.id,
            stock_qty=20,
            cost_price=Decimal("150.00"),
            selling_price=Decimal("220.00"),
        ),
        dict(
            name="Non-stick Frying Pan 28cm",
            barcode="KW002",
            category_id=kitchen.id,
            stock_qty=25,
            cost_price=Decimal("80.00"),
            selling_price=Decimal("130.00"),
        ),
        dict(
            name="Kitchen Knife Set (5pcs)",
            barcode="KW003",
            category_id=kitchen.id,
            stock_qty=15,
            cost_price=Decimal("120.00"),
            selling_price=Decimal("180.00"),
        ),
        dict(
            name="Glass Storage Container 1L",
            barcode="KW004",
            category_id=kitchen.id,
            stock_qty=40,
            cost_price=Decimal("25.00"),
            selling_price=Decimal("45.00"),
        ),
        # Solar
        dict(
            name="Solar Panel 200W",
            barcode="SE001",
            category_id=solar.id,
            stock_qty=10,
            cost_price=Decimal("800.00"),
            selling_price=Decimal("1150.00"),
        ),
        dict(
            name="Deep Cycle Battery 100Ah",
            barcode="SE002",
            category_id=solar.id,
            stock_qty=8,
            cost_price=Decimal("950.00"),
            selling_price=Decimal("1350.00"),
        ),
        dict(
            name="Pure Sine Wave Inverter 1000W",
            barcode="SE003",
            category_id=solar.id,
            stock_qty=5,
            cost_price=Decimal("1200.00"),
            selling_price=Decimal("1750.00"),
        ),
        dict(
            name="Solar Charge Controller 30A",
            barcode="SE004",
            category_id=solar.id,
            stock_qty=18,
            cost_price=Decimal("260.00"),
            selling_price=Decimal("380.00"),
        ),
    ]

    created = 0
    for pdata in products:
        existing = (
            db.query(Product)
            .filter(Product.barcode == pdata["barcode"])
            .first()
        )
        if existing:
            continue
        prod = Product(
            name=pdata["name"],
            barcode=pdata["barcode"],
            category_id=pdata["category_id"],
            stock_qty=pdata["stock_qty"],
            cost_price=pdata["cost_price"],
            selling_price=pdata["selling_price"],
            is_active=True,
        )
        db.add(prod)
        db.commit()
        db.refresh(prod)

        movement = InventoryMovement(
            product_id=prod.id,
            change_qty=prod.stock_qty,
            reason="Initial stock (seed)",
        )
        db.add(movement)
        db.commit()
        created += 1

    print(f"Seed complete. Created {created} products (others already existed).")


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()


