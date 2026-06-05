"""Quotations must not change product stock until converted to a sale."""
import app.enterprise_models  # noqa: F401 — register branches FK for User

from app.database import SessionLocal
from app.models import Product, User
from app.quotation_models import Tenant
from app.quotation_service import QuotationService


def _make_tenant(db):
    t = Tenant(tenant_uid="q-stock-uid", name="Quote Shop", is_active=True)
    db.add(t)
    db.flush()
    return t


def _make_user(db, tenant_id):
    u = User(
        username="quote_cashier",
        password_hash="x",
        role="cashier",
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(u)
    db.flush()
    return u


def _make_product(db, tenant_id, stock=12.0):
    p = Product(
        name="Widget",
        selling_price=5.0,
        cost_price=3.0,
        stock_qty=stock,
        reserved_qty=0.0,
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(p)
    db.flush()
    return p


def test_create_quotation_does_not_deduct_stock():
    db = SessionLocal()
    try:
        tenant = _make_tenant(db)
        user = _make_user(db, tenant.id)
        product = _make_product(db, tenant.id, stock=12.0)
        db.commit()

        service = QuotationService(db)
        service.create_quotation(
            customer_id=None,
            customer_name="Walk-in Customer",
            customer_phone=None,
            customer_email=None,
            items=[
                {
                    "product_id": product.id,
                    "quantity": 3,
                    "unit_price": 5.0,
                    "discount": 0,
                }
            ],
            valid_until=None,
            notes=None,
            created_by=user.id,
            tenant_id=tenant.id,
            acting_user=user,
        )

        db.refresh(product)
        assert product.stock_qty == 12.0
        assert product.reserved_qty == 0.0
    finally:
        db.close()
