"""
Shared inventory operations for PO receiving, adjustments, and transfers.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..enterprise_models import BranchProductStock
from ..models import InventoryMovement, Product
from ..tenant_scope import require_product


def apply_product_stock_change(
    db: Session,
    product_id: int,
    change_qty: float,
    reason: str,
    *,
    branch_id: Optional[int] = None,
    update_cost: Optional[float] = None,
) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise ValueError(f"Product {product_id} not found")
    new_qty = float(product.stock_qty) + change_qty
    if new_qty < 0:
        raise ValueError("Insufficient stock")
    product.stock_qty = new_qty
    if update_cost is not None:
        product.cost_price = update_cost
    db.add(
        InventoryMovement(
            product_id=product_id,
            change_qty=change_qty,
            reason=reason,
        )
    )
    if branch_id is not None:
        bps = (
            db.query(BranchProductStock)
            .filter(
                BranchProductStock.branch_id == branch_id,
                BranchProductStock.product_id == product_id,
            )
            .first()
        )
        if bps is None:
            bps = BranchProductStock(branch_id=branch_id, product_id=product_id, stock_qty=0)
            db.add(bps)
            db.flush()
        bps.stock_qty = max(0.0, float(bps.stock_qty) + change_qty)
    return product


def scoped_product(db: Session, product_id: int, user) -> Product:
    return require_product(db, product_id, user)
