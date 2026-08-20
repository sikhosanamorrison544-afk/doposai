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
    Atomically adjust product stock and record an InventoryMovement.

    Caller owns the outer transaction (commit/rollback). This function:
      1. Locks the product row with FOR UPDATE (honoured on Postgres; SQLite
         still serialises writers at the DB file)
      2. Applies ``stock_qty = stock_qty + change`` via SQL so two concurrent
         receipts cannot overwrite each other even when FOR UPDATE is a no-op
      3. Inserts the movement and flushes so ``movement_id`` is available
      4. Optionally adjusts branch stock under the same transaction
    """
    change = float(change_qty)
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .with_for_update()
        .one_or_none()
    )
    if product is None:
        raise ValueError(f"Product {product_id} not found")

    previous = float(product.stock_qty or 0)
    resulting = previous + change
    if resulting < 0:
        raise ValueError("Insufficient stock")

    values = {"stock_qty": Product.stock_qty + change}
    if update_cost is not None:
        values["cost_price"] = update_cost

    db.execute(update(Product).where(Product.id == product_id).values(**values))
    db.refresh(product)
    # Prefer the post-update column as source of truth (guards against races).
    resulting = float(product.stock_qty or 0)
    previous = resulting - change

    movement = InventoryMovement(
        product_id=product_id,
        change_qty=change,
        reason=reason,
    )
    db.add(movement)
    db.flush()  # assign movement.id before commit

    if branch_id is not None:
        bps = (
            db.query(BranchProductStock)
            .filter(
                BranchProductStock.branch_id == branch_id,
                BranchProductStock.product_id == product_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if bps is None:
            bps = BranchProductStock(
                branch_id=branch_id, product_id=product_id, stock_qty=0.0
            )
            db.add(bps)
            db.flush()
            bps = (
                db.query(BranchProductStock)
                .filter(BranchProductStock.id == bps.id)
                .with_for_update()
                .one()
            )
        # Atomic branch increment; clamp at zero to match prior behaviour.
        db.execute(
            update(BranchProductStock)
            .where(BranchProductStock.id == bps.id)
            .values(stock_qty=BranchProductStock.stock_qty + change)
        )
        db.refresh(bps)
        if float(bps.stock_qty or 0) < 0:
            bps.stock_qty = 0.0

    return StockChangeResult(
        product=product,
        previous_qty=previous,
        change_qty=change,
        resulting_qty=resulting,
        movement_id=movement.id,
    )


def scoped_product(db: Session, product_id: int, user) -> Product:
    return require_product(db, product_id, user)
