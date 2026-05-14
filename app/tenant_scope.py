"""Multi-tenant row visibility: NULL tenant_id = legacy single-tenant data."""
from __future__ import annotations

from typing import Any, Optional, Type

from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session, aliased

from .models import (
    CashierShift,
    Category,
    Customer,
    LaybyCustomer,
    LaybyTransaction,
    Notification,
    Product,
    Sale,
    StoreSettings,
    User,
    Withdrawal,
)


def row_visible(row_tid: Optional[int], user: User) -> bool:
    if user.tenant_id is None:
        return row_tid is None
    return row_tid == user.tenant_id


def filter_by_tenant(query: Query, model: Type[Any], user: User) -> Query:
    if not hasattr(model, "tenant_id"):
        return query
    if user.tenant_id is None:
        return query.filter(model.tenant_id.is_(None))
    return query.filter(model.tenant_id == user.tenant_id)


def filter_products(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(Product), Product, user)


def filter_customers(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(Customer), Customer, user)


def filter_sales(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(Sale), Sale, user)


def filter_categories(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(Category), Category, user)


def filter_store_settings(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(StoreSettings), StoreSettings, user)


def filter_users(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(User), User, user)


def filter_shifts(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(CashierShift), CashierShift, user)


def filter_withdrawals(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(Withdrawal), Withdrawal, user)


def filter_layby_customers(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(LaybyCustomer), LaybyCustomer, user)


def filter_layby_transactions(db: Session, user: User) -> Query:
    return (
        db.query(LaybyTransaction)
        .join(LaybyCustomer, LaybyCustomer.id == LaybyTransaction.customer_id)
        .filter(
            LaybyCustomer.tenant_id.is_(None)
            if user.tenant_id is None
            else LaybyCustomer.tenant_id == user.tenant_id
        )
    )


def filter_fixed_assets(db: Session, user: User) -> Query:
    from .accounting_models import FixedAsset

    Creator = aliased(User)
    q = db.query(FixedAsset).join(Creator, FixedAsset.created_by == Creator.id)
    if user.tenant_id is None:
        return q.filter(Creator.tenant_id.is_(None))
    return q.filter(Creator.tenant_id == user.tenant_id)


def first_store_settings_for_tenant(db: Session, tenant_id: Optional[int]) -> Optional[StoreSettings]:
    """Store branding row for a tenant (NULL = legacy single-tenant)."""
    if tenant_id is not None:
        return db.query(StoreSettings).filter(StoreSettings.tenant_id == tenant_id).first()
    return db.query(StoreSettings).filter(StoreSettings.tenant_id.is_(None)).first()


def sale_tenant_match(user: User):
    """Filter expression for Sale rows visible to this user."""
    if user.tenant_id is None:
        return Sale.tenant_id.is_(None)
    return Sale.tenant_id == user.tenant_id


def product_tenant_match(user: User):
    """Filter expression for Product rows visible to this user."""
    if user.tenant_id is None:
        return Product.tenant_id.is_(None)
    return Product.tenant_id == user.tenant_id


def withdrawal_tenant_match(user: User):
    """Filter expression for Withdrawal rows visible to this user."""
    if user.tenant_id is None:
        return Withdrawal.tenant_id.is_(None)
    return Withdrawal.tenant_id == user.tenant_id


def filter_notifications(db: Session, user: User) -> Query:
    return filter_by_tenant(db.query(Notification), Notification, user)


def get_scoped(db: Session, model: Type[Any], id_: int, user: User) -> Any:
    obj = db.get(model, id_)
    if obj is None:
        return None
    if hasattr(obj, "tenant_id") and not row_visible(getattr(obj, "tenant_id", None), user):
        return None
    return obj


def require_product(db: Session, product_id: int, user: User) -> Product:
    p = get_scoped(db, Product, product_id, user)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return p


def require_customer(db: Session, customer_id: int, user: User) -> Customer:
    c = get_scoped(db, Customer, customer_id, user)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return c


def require_sale(db: Session, sale_id: int, user: User) -> Sale:
    s = get_scoped(db, Sale, sale_id, user)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    return s


def require_user(db: Session, user_id: int, admin: User) -> User:
    u = get_scoped(db, User, user_id, admin)
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return u


def require_shift(db: Session, shift_id: int, user: User) -> CashierShift:
    s = get_scoped(db, CashierShift, shift_id, user)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    return s


def require_withdrawal(db: Session, withdrawal_id: int, user: User) -> Withdrawal:
    w = get_scoped(db, Withdrawal, withdrawal_id, user)
    if w is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Withdrawal not found")
    return w


def tenant_id_for_row(user: User) -> Optional[int]:
    return user.tenant_id


def same_tenant(a: Optional[int], b: Optional[int]) -> bool:
    """True if both legacy (NULL) or same non-null tenant id."""
    return (a is None and b is None) or (a is not None and b is not None and int(a) == int(b))
