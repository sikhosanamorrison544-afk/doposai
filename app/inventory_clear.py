"""Bulk clear tenant inventory (admin-only)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Set

from fastapi import HTTPException, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .enterprise_models import BranchProductStock
from .models import (
    InventoryMovement,
    LaybyTransaction,
    Notification,
    Product,
    RefundItem,
    SaleItem,
    User,
)
from .quotation_models import QuotationItem
from . import tenant_scope

logger = logging.getLogger(__name__)

CONFIRM_PHRASE = "DELETE ALL STOCK"


def clear_all_stock_for_tenant(db: Session, admin: User) -> Dict[str, Any]:
    """Deactivate all products; hard-delete those with no sales/layby/quotation/refund ties."""
    base = tenant_scope.filter_products(db, admin)
    product_ids = [row[0] for row in base.with_entities(Product.id).all()]
    if not product_ids:
        return {
            "ok": True,
            "deleted": 0,
            "deactivated": 0,
            "message": "No products to clear.",
        }

    active_layby = (
        db.query(LaybyTransaction.id)
        .filter(
            LaybyTransaction.product_id.in_(product_ids),
            LaybyTransaction.status == "active",
        )
        .limit(1)
        .first()
    )
    if active_layby:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clear stock while active layby transactions exist. Complete or cancel them first.",
        )

    protected: Set[int] = set()
    for model, col in (
        (SaleItem, SaleItem.product_id),
        (LaybyTransaction, LaybyTransaction.product_id),
        (RefundItem, RefundItem.product_id),
        (QuotationItem, QuotationItem.product_id),
    ):
        protected.update(
            row[0]
            for row in db.query(col)
            .filter(col.in_(product_ids))
            .distinct()
            .all()
        )

    deletable = [pid for pid in product_ids if pid not in protected]

    if deletable:
        db.execute(
            delete(InventoryMovement).where(InventoryMovement.product_id.in_(deletable))
        )
        db.execute(
            delete(BranchProductStock).where(BranchProductStock.product_id.in_(deletable))
        )
        db.query(Notification).filter(Notification.product_id.in_(deletable)).update(
            {Notification.product_id: None},
            synchronize_session=False,
        )
        db.execute(delete(Product).where(Product.id.in_(deletable)))

    remaining = [pid for pid in product_ids if pid in protected]
    deactivated = 0
    if remaining:
        deactivated = (
            base.filter(Product.id.in_(remaining))
            .update(
                {
                    Product.is_active: False,
                    Product.stock_qty: 0.0,
                    Product.reserved_qty: 0.0,
                },
                synchronize_session=False,
            )
            or 0
        )

    db.commit()
    deleted_count = len(deletable)
    logger.info(
        "Cleared stock for tenant %s: deleted=%s deactivated=%s",
        admin.tenant_id,
        deleted_count,
        deactivated,
    )
    msg_parts = []
    if deleted_count:
        msg_parts.append(f"removed {deleted_count:,} product(s)")
    if deactivated:
        msg_parts.append(
            f"deactivated {deactivated:,} product(s) kept for sales history"
        )
    message = (
        "Inventory cleared: " + ", ".join(msg_parts) + "."
        if msg_parts
        else "Inventory cleared."
    )
    return {
        "ok": True,
        "deleted": deleted_count,
        "deactivated": deactivated,
        "message": message,
    }
