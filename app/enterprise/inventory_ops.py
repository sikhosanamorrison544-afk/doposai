"""
Shared inventory operations for PO receiving, adjustments, and transfers.

Stock changes use a row lock plus an atomic SQL increment
(``stock_qty = stock_qty + change``) and write the inventory movement in the
same transaction so concurrent receipts cannot overwrite each other.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..enterprise_models import BranchProductStock
from ..models import InventoryMovement, Product
from ..tenant_scope import require_product


@dataclass
class StockChangeResult:
    product: Product
    previous_qty: float
    change_qty: float
    resulting_qty: float
    movement_id: Optional[int]


def apply_product_stock_change(
    db: Session,
    product_id: int,
    change_qty: float,
    reason: str,
    *,
    branch_id: Optional[int] = None,
    update_cost: Optional[float] = None,
) -> StockChangeResult:
    """
    Atomically adjust stock. When branch_id is set, BranchProductStock is authoritative
    and Product.stock_qty is synced as a legacy shadow (Section 14).
    """
    from ..inventory_service import (
        MOVEMENT_ADJUSTMENT,
        decrease_branch_stock,
        increase_branch_stock,
        to_qty,
    )

    change = float(change_qty)
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .with_for_update()
        .one_or_none()
    )
    if product is None:
        raise ValueError(f"Product {product_id} not found")

    if update_cost is not None:
        db.execute(
            update(Product).where(Product.id == product_id).values(cost_price=update_cost)
        )

    if branch_id is not None:
        tid = getattr(product, "tenant_id", None)
        qty = abs(change)
        if change >= 0:
            snap = increase_branch_stock(
                db,
                tenant_id=tid,
                branch_id=int(branch_id),
                product_id=product_id,
                quantity=qty,
                reason=reason,
                movement_type=MOVEMENT_ADJUSTMENT,
            )
        else:
            snap = decrease_branch_stock(
                db,
                tenant_id=tid,
                branch_id=int(branch_id),
                product_id=product_id,
                quantity=qty,
                reason=reason,
                movement_type=MOVEMENT_ADJUSTMENT,
                check_reserved=False,
            )
        db.refresh(product)
        resulting = float(product.stock_qty or 0)
        previous = resulting - change
        mov = (
            db.query(InventoryMovement)
            .filter(InventoryMovement.product_id == product_id)
            .order_by(InventoryMovement.id.desc())
            .first()
        )
        return StockChangeResult(
            product=product,
            previous_qty=previous,
            change_qty=change,
            resulting_qty=resulting,
            movement_id=mov.id if mov else 0,
        )

    # Legacy Product-only path (no branch) — keep for rare callers; prefer branch_id.
    previous = float(product.stock_qty or 0)
    resulting = previous + change
    if resulting < 0:
        raise ValueError("Insufficient stock")

    db.execute(
        update(Product).where(Product.id == product_id).values(stock_qty=Product.stock_qty + change)
    )
    db.refresh(product)
    resulting = float(product.stock_qty or 0)
    previous = resulting - change

    movement = InventoryMovement(
        product_id=product_id,
        change_qty=change,
        reason=reason,
        tenant_id=getattr(product, "tenant_id", None),
    )
    db.add(movement)
    db.flush()

    return StockChangeResult(
        product=product,
        previous_qty=previous,
        change_qty=change,
        resulting_qty=resulting,
        movement_id=movement.id,
    )


def scoped_product(db: Session, product_id: int, user) -> Product:
    return require_product(db, product_id, user)
