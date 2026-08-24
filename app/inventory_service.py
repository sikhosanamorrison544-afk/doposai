"""
Section 14 — branch-authoritative inventory service.

BranchProductStock.quantity_on_hand (stock_qty) is the operational source of truth.
Product.stock_qty is a legacy compatibility shadow = sum of active-branch quantities.

All stock mutations for POS/refunds/adjustments must go through this module.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Sequence, Union

from fastapi import HTTPException, status
from sqlalchemy import func, inspect, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .branch_context import (
    resolve_branch_context,
    user_has_branch_access,
)
from .enterprise_models import Branch, BranchProductStock
from .models import InventoryMovement, Product, User
from .permissions import is_admin_level

logger = logging.getLogger(__name__)

QTY = Decimal("0.0001")  # quantize to 4 decimal places
ZERO = Decimal("0")

MOVEMENT_SALE = "SALE"
MOVEMENT_REFUND = "REFUND"
MOVEMENT_ADJUSTMENT = "ADJUSTMENT"
MOVEMENT_OPENING_STOCK = "OPENING_STOCK"
MOVEMENT_TRANSFER_DISPATCH = "TRANSFER_DISPATCH"
MOVEMENT_TRANSFER_RECEIPT = "TRANSFER_RECEIPT"
MOVEMENT_TRANSFER_DAMAGED = "TRANSFER_DAMAGED"
MOVEMENT_TRANSFER_MISSING = "TRANSFER_MISSING"
MOVEMENT_TRANSFER_VARIANCE_RESOLVED = "TRANSFER_VARIANCE_RESOLVED"
MOVEMENT_INITIAL = "OPENING_STOCK"
REFERENCE_STOCK_TRANSFER = "STOCK_TRANSFER"


def to_qty(value: Union[Decimal, float, int, str, None]) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return d.quantize(QTY, rounding=ROUND_HALF_UP)


def fmt_qty(value: Union[Decimal, float, int, str, None]) -> str:
    return format(to_qty(value), "f")


@dataclass
class BranchStockSnapshot:
    branch_id: int
    product_id: int
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    available: Decimal


def require_operational_branch(
    db: Session,
    user: User,
    *,
    explicit_branch_id: Optional[int] = None,
    header_branch_id: Optional[str] = None,
    allow_inactive: bool = False,
) -> Branch:
    """
    Resolve a concrete branch for writes.

    Rejects consolidated scope=all with a controlled 400.
    Auto-creates Main Branch when the tenant has none (pre-migration compat).
    """
    token_scope = getattr(user, "_token_branch_scope", None)
    if (
        (token_scope or "").strip().lower() == "all"
        and explicit_branch_id is None
        and (header_branch_id is None or str(header_branch_id).strip() == "")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A specific branch is required for this operation",
        )

    # Ensure at least Main Branch exists for this tenant (single-store compat).
    _ensure_tenant_has_main_branch(db, user.tenant_id)

    ctx = resolve_branch_context(
        db,
        user,
        header_branch_id=header_branch_id,
        query_branch_id=explicit_branch_id,
        token_branch_id=getattr(user, "_token_branch_id", None),
        token_scope=token_scope,
        require_branch=True,
    )
    if ctx.scope == "all" or ctx.branch_id is None or ctx.branch is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A specific branch is required for this operation",
        )
    br = ctx.branch
    if not br.is_active and not allow_inactive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot write to an inactive branch",
        )
    if not user_has_branch_access(db, user, br.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this branch",
        )
    return br


def _ensure_tenant_has_main_branch(db: Session, tenant_id: Optional[int]) -> Branch:
    q = db.query(Branch)
    if tenant_id is None:
        q = q.filter(Branch.tenant_id.is_(None))
    else:
        q = q.filter(Branch.tenant_id == tenant_id)
    existing = q.filter(Branch.is_default.is_(True)).order_by(Branch.id.asc()).first()
    if existing is not None:
        return existing
    any_b = q.order_by(Branch.id.asc()).first()
    if any_b is not None:
        any_b.is_default = True
        db.flush()
        return any_b
    br = Branch(
        tenant_id=tenant_id,
        name="Main Branch",
        code="MAIN",
        is_default=True,
        is_active=True,
    )
    db.add(br)
    db.flush()
    return br


def ensure_branch_stock_row(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    for_update: bool = False,
) -> BranchProductStock:
    q = db.query(BranchProductStock).filter(
        BranchProductStock.branch_id == int(branch_id),
        BranchProductStock.product_id == int(product_id),
    )
    if for_update:
        q = q.with_for_update()
    row = q.one_or_none()
    if row is not None:
        return row

    initial = ZERO
    seeded = False
    reserved = ZERO
    branch = db.query(Branch).filter(Branch.id == int(branch_id)).first()
    product = db.query(Product).filter(Product.id == int(product_id)).first()
    other_bps = (
        db.query(BranchProductStock.id)
        .filter(BranchProductStock.product_id == int(product_id))
        .count()
    )
    # Lazy Main Branch seed from Product.stock_qty when no BPS exists yet.
    if branch and branch.is_default and product is not None and other_bps == 0:
        initial = to_qty(product.stock_qty)
        reserved = to_qty(getattr(product, "reserved_qty", 0) or 0)
        seeded = True

    row = BranchProductStock(
        tenant_id=tenant_id if tenant_id is not None else getattr(product, "tenant_id", None),
        branch_id=int(branch_id),
        product_id=int(product_id),
        stock_qty=initial,
        reserved_qty=reserved,
        seeded_from_legacy=seeded,
    )
    db.add(row)
    db.flush()
    if for_update:
        row = (
            db.query(BranchProductStock)
            .filter(BranchProductStock.id == row.id)
            .with_for_update()
            .one()
        )
    return row


def get_branch_stock(
    db: Session, branch_id: int, product_id: int
) -> BranchStockSnapshot:
    row = (
        db.query(BranchProductStock)
        .filter(
            BranchProductStock.branch_id == int(branch_id),
            BranchProductStock.product_id == int(product_id),
        )
        .one_or_none()
    )
    on_hand = to_qty(row.stock_qty if row else 0)
    reserved = to_qty(row.reserved_qty if row else 0)
    return BranchStockSnapshot(
        branch_id=int(branch_id),
        product_id=int(product_id),
        quantity_on_hand=on_hand,
        quantity_reserved=reserved,
        available=on_hand - reserved,
    )


def lock_branch_stock(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
) -> BranchProductStock:
    return ensure_branch_stock_row(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
        product_id=product_id,
        for_update=True,
    )


def sync_legacy_product_stock(db: Session, product_id: int) -> Decimal:
    """Set Product.stock_qty = sum of BranchProductStock across all branches."""
    # Flush pending in-session stock mutations first so the SUM reflects the
    # same transaction (autoflush=False sessions otherwise read stale values).
    db.flush()
    total = (
        db.query(func.coalesce(func.sum(BranchProductStock.stock_qty), 0))
        .filter(BranchProductStock.product_id == int(product_id))
        .scalar()
    )
    total_d = to_qty(total)
    db.execute(
        update(Product)
        .where(Product.id == int(product_id))
        .values(stock_qty=float(total_d))
    )
    return total_d


def _record_movement(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    change: Decimal,
    reason: str,
    movement_type: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    client_movement_id: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
) -> InventoryMovement:
    # reason remains human-readable; prefix type when provided for filtering
    full_reason = reason
    if movement_type and not reason.upper().startswith(movement_type):
        full_reason = f"{movement_type}: {reason}" if reason else movement_type
    kwargs: dict = {
        "product_id": int(product_id),
        "change_qty": float(change),
        "reason": full_reason[:80],
        "tenant_id": tenant_id,
        "branch_id": int(branch_id),
        "client_movement_id": client_movement_id,
    }
    if hasattr(InventoryMovement, "reference_type"):
        kwargs["reference_type"] = reference_type
    if hasattr(InventoryMovement, "reference_id"):
        kwargs["reference_id"] = reference_id
    if hasattr(InventoryMovement, "movement_type"):
        kwargs["movement_type"] = movement_type
    mov = InventoryMovement(**kwargs)
    db.add(mov)
    db.flush()
    return mov


def increase_branch_stock(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    quantity: Union[Decimal, float, int, str],
    reason: str,
    movement_type: str = MOVEMENT_ADJUSTMENT,
    actor_user_id: Optional[int] = None,
    client_movement_id: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
) -> BranchStockSnapshot:
    qty = to_qty(quantity)
    if qty <= ZERO:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if client_movement_id:
        existing = (
            db.query(InventoryMovement)
            .filter(InventoryMovement.client_movement_id == client_movement_id)
            .first()
        )
        if existing is not None:
            # Idempotent retry — do not increment or create a second movement.
            return get_branch_stock(db, branch_id, product_id)
    row = lock_branch_stock(
        db, tenant_id=tenant_id, branch_id=branch_id, product_id=product_id
    )
    new_val = to_qty(row.stock_qty) + qty
    db.execute(
        update(BranchProductStock)
        .where(BranchProductStock.id == row.id)
        .values(stock_qty=new_val)
    )
    db.refresh(row)
    _record_movement(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
        product_id=product_id,
        change=qty,
        reason=reason,
        movement_type=movement_type,
        actor_user_id=actor_user_id,
        client_movement_id=client_movement_id,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    sync_legacy_product_stock(db, product_id)
    return get_branch_stock(db, branch_id, product_id)


def decrease_branch_stock(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    quantity: Union[Decimal, float, int, str],
    reason: str,
    movement_type: str = MOVEMENT_SALE,
    actor_user_id: Optional[int] = None,
    allow_negative: bool = False,
    client_movement_id: Optional[str] = None,
    check_reserved: bool = True,
) -> BranchStockSnapshot:
    qty = to_qty(quantity)
    if qty <= ZERO:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    row = lock_branch_stock(
        db, tenant_id=tenant_id, branch_id=branch_id, product_id=product_id
    )
    on_hand = to_qty(row.stock_qty)
    reserved = to_qty(row.reserved_qty)
    available = on_hand - reserved if check_reserved else on_hand
    if not allow_negative and available < qty:
        product = db.query(Product).filter(Product.id == product_id).first()
        name = product.name if product else str(product_id)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient stock for '{name}' at this branch. "
                f"Available: {fmt_qty(available)}, Requested: {fmt_qty(qty)}"
            ),
        )
    new_val = on_hand - qty
    if not allow_negative and new_val < ZERO:
        new_val = ZERO
    db.execute(
        update(BranchProductStock)
        .where(BranchProductStock.id == row.id)
        .values(stock_qty=new_val)
    )
    db.refresh(row)
    _record_movement(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
        product_id=product_id,
        change=-qty,
        reason=reason,
        movement_type=movement_type,
        actor_user_id=actor_user_id,
        client_movement_id=client_movement_id,
    )
    sync_legacy_product_stock(db, product_id)
    return get_branch_stock(db, branch_id, product_id)


def reserve_branch_stock(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    quantity: Union[Decimal, float, int, str],
) -> BranchStockSnapshot:
    """Increase reserved_qty; fails if available < quantity."""
    qty = to_qty(quantity)
    if qty <= ZERO:
        raise HTTPException(status_code=400, detail="Reserve quantity must be positive")
    row = lock_branch_stock(
        db, tenant_id=tenant_id, branch_id=branch_id, product_id=product_id
    )
    on_hand = to_qty(row.stock_qty)
    reserved = to_qty(row.reserved_qty)
    available = on_hand - reserved
    if available < qty:
        product = db.query(Product).filter(Product.id == product_id).first()
        name = product.name if product else str(product_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Insufficient available stock to reserve for '{name}'. "
                f"Available: {fmt_qty(available)}, Requested: {fmt_qty(qty)}"
            ),
        )
    new_reserved = reserved + qty
    db.execute(
        update(BranchProductStock)
        .where(BranchProductStock.id == row.id)
        .values(reserved_qty=new_reserved)
    )
    db.refresh(row)
    return get_branch_stock(db, branch_id, product_id)


def release_branch_reservation(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    quantity: Union[Decimal, float, int, str],
) -> BranchStockSnapshot:
    """Decrease reserved_qty (clamped to zero)."""
    qty = to_qty(quantity)
    if qty <= ZERO:
        return get_branch_stock(db, branch_id, product_id)
    row = lock_branch_stock(
        db, tenant_id=tenant_id, branch_id=branch_id, product_id=product_id
    )
    reserved = to_qty(row.reserved_qty)
    new_reserved = reserved - qty
    if new_reserved < ZERO:
        new_reserved = ZERO
    db.execute(
        update(BranchProductStock)
        .where(BranchProductStock.id == row.id)
        .values(reserved_qty=new_reserved)
    )
    db.refresh(row)
    return get_branch_stock(db, branch_id, product_id)


def dispatch_reserved_stock(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    quantity: Union[Decimal, float, int, str],
    reason: str,
    actor_user_id: Optional[int] = None,
    client_movement_id: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
) -> BranchStockSnapshot:
    """
    Atomic dispatch: decrease on-hand and release matching reservation.
    Does not re-check available beyond on-hand (reservation already held).
    """
    qty = to_qty(quantity)
    if qty <= ZERO:
        raise HTTPException(status_code=400, detail="Dispatch quantity must be positive")
    row = lock_branch_stock(
        db, tenant_id=tenant_id, branch_id=branch_id, product_id=product_id
    )
    on_hand = to_qty(row.stock_qty)
    reserved = to_qty(row.reserved_qty)
    if on_hand < qty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient on-hand stock to dispatch. On hand: {fmt_qty(on_hand)}",
        )
    new_on_hand = on_hand - qty
    new_reserved = reserved - qty
    if new_reserved < ZERO:
        new_reserved = ZERO
    db.execute(
        update(BranchProductStock)
        .where(BranchProductStock.id == row.id)
        .values(stock_qty=new_on_hand, reserved_qty=new_reserved)
    )
    db.refresh(row)
    _record_movement(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
        product_id=product_id,
        change=-qty,
        reason=reason,
        movement_type=MOVEMENT_TRANSFER_DISPATCH,
        actor_user_id=actor_user_id,
        client_movement_id=client_movement_id,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    sync_legacy_product_stock(db, product_id)
    return get_branch_stock(db, branch_id, product_id)


def set_branch_stock(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    quantity: Union[Decimal, float, int, str],
    reason: str,
    actor_user_id: Optional[int] = None,
) -> BranchStockSnapshot:
    target = to_qty(quantity)
    if target < ZERO:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
    row = lock_branch_stock(
        db, tenant_id=tenant_id, branch_id=branch_id, product_id=product_id
    )
    before = to_qty(row.stock_qty)
    delta = target - before
    db.execute(
        update(BranchProductStock)
        .where(BranchProductStock.id == row.id)
        .values(stock_qty=target)
    )
    db.refresh(row)
    if delta != ZERO:
        _record_movement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            product_id=product_id,
            change=delta,
            reason=reason,
            movement_type=MOVEMENT_ADJUSTMENT,
            actor_user_id=actor_user_id,
        )
    sync_legacy_product_stock(db, product_id)
    return get_branch_stock(db, branch_id, product_id)


def seed_main_branch_from_legacy(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product: Product,
) -> BranchProductStock:
    """
    Idempotent Main Branch seed. Never re-seeds once seeded_from_legacy is set
    or a row already exists.
    """
    existing = (
        db.query(BranchProductStock)
        .filter(
            BranchProductStock.branch_id == int(branch_id),
            BranchProductStock.product_id == product.id,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.tenant_id is None and tenant_id is not None:
            existing.tenant_id = tenant_id
        return existing
    row = BranchProductStock(
        tenant_id=tenant_id,
        branch_id=int(branch_id),
        product_id=product.id,
        stock_qty=to_qty(product.stock_qty),
        reserved_qty=to_qty(getattr(product, "reserved_qty", 0) or 0),
        seeded_from_legacy=True,
    )
    db.add(row)
    db.flush()
    return row


def total_branch_stock_for_product(db: Session, product_id: int) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(BranchProductStock.stock_qty), 0))
        .filter(BranchProductStock.product_id == int(product_id))
        .scalar()
    )
    return to_qty(total)


def branch_stock_breakdown(db: Session, product_id: int) -> List[dict]:
    rows = (
        db.query(BranchProductStock)
        .filter(BranchProductStock.product_id == int(product_id))
        .order_by(BranchProductStock.branch_id.asc())
        .all()
    )
    return [
        {"branchId": r.branch_id, "quantity": fmt_qty(r.stock_qty)}
        for r in rows
    ]


def assert_shift_matches_branch(
    shift_branch_id: Optional[int], sale_branch_id: int
) -> None:
    if shift_branch_id is None:
        return
    if int(shift_branch_id) != int(sale_branch_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Open shift belongs to a different branch",
        )


def assert_can_switch_with_open_shift(
    db: Session, user: User, target_branch_id: int
) -> None:
    """Cashiers with an open shift cannot switch operational branch."""
    from .models import CashierShift

    if is_admin_level(user):
        return
    open_shift = (
        db.query(CashierShift)
        .filter(
            CashierShift.cashier_id == user.id,
            CashierShift.end_time.is_(None),
        )
        .first()
    )
    if open_shift is None:
        return
    if open_shift.branch_id is not None and int(open_shift.branch_id) != int(
        target_branch_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Close the open shift before switching branches",
        )


@dataclass
class InventorySummary:
    quantity_on_hand: Decimal
    quantity_reserved: Decimal
    quantity_in_transit_out: Decimal
    quantity_in_transit_in: Decimal
    available_quantity: Decimal

    def to_dict(self) -> dict:
        return {
            "quantityOnHand": fmt_qty(self.quantity_on_hand),
            "quantityReserved": fmt_qty(self.quantity_reserved),
            "quantityInTransitOut": fmt_qty(self.quantity_in_transit_out),
            "quantityInTransitIn": fmt_qty(self.quantity_in_transit_in),
            "availableQuantity": fmt_qty(self.available_quantity),
        }


def inventory_summary_for_product_branch(
    db: Session,
    *,
    branch_id: int,
    product_id: int,
) -> InventorySummary:
    """
    On-hand / reserved from BPS; in-transit from open transfer-item quantities.

    available = on_hand − reserved  (in-transit-out already left on-hand at dispatch,
    so it is NOT subtracted again).
    """
    from .enterprise_models import (
        TRANSFER_STATUS_DISPATCHED,
        TRANSFER_STATUS_IN_TRANSIT,
        StockTransfer,
        StockTransferItem,
    )

    snap = get_branch_stock(db, branch_id, product_id)
    out_items = (
        db.query(StockTransferItem)
        .join(StockTransfer, StockTransferItem.stock_transfer_id == StockTransfer.id)
        .filter(
            StockTransfer.from_branch_id == int(branch_id),
            StockTransferItem.product_id == int(product_id),
            StockTransfer.status.in_(
                (TRANSFER_STATUS_DISPATCHED, TRANSFER_STATUS_IN_TRANSIT)
            ),
        )
        .all()
    )
    in_items = (
        db.query(StockTransferItem)
        .join(StockTransfer, StockTransferItem.stock_transfer_id == StockTransfer.id)
        .filter(
            StockTransfer.to_branch_id == int(branch_id),
            StockTransferItem.product_id == int(product_id),
            StockTransfer.status.in_(
                (TRANSFER_STATUS_DISPATCHED, TRANSFER_STATUS_IN_TRANSIT)
            ),
        )
        .all()
    )
    transit_out = sum((it.in_transit_quantity for it in out_items), ZERO)
    transit_in = sum((it.in_transit_quantity for it in in_items), ZERO)
    return InventorySummary(
        quantity_on_hand=snap.quantity_on_hand,
        quantity_reserved=snap.quantity_reserved,
        quantity_in_transit_out=to_qty(transit_out),
        quantity_in_transit_in=to_qty(transit_in),
        available_quantity=snap.available,
    )


_SCHEMA_REQUIRED_COLUMNS = (
    ("branches", "email"),
    ("branches", "manager_user_id"),
    ("branch_product_stock", "tenant_id"),
    ("branch_product_stock", "seeded_from_legacy"),
    ("inventory_movements", "branch_id"),
    ("inventory_movements", "movement_type"),
    ("inventory_movements", "reference_type"),
    ("inventory_movements", "reference_id"),
)


def assert_branch_schema_ready(db: Session) -> None:
    """Raise a controlled 503 when the branch migration has not been applied.

    The ORM models require columns added by ``migrate_branches.py`` (email,
    manager_user_id, BPS tenant_id/seeded_from_legacy, movement provenance).
    If those columns are absent, normal Branch/BPS queries raise an unhandled
    ``OperationalError``. Surface a clear schema-not-ready response instead.
    """
    try:
        insp = inspect(db.get_bind())
        table_cols: dict = {}
        for table in ("branches", "branch_product_stock", "inventory_movements"):
            if not insp.has_table(table):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Branch schema is not ready — run the branch migration",
                )
            table_cols[table] = {c["name"] for c in insp.get_columns(table)}
    except HTTPException:
        raise
    except Exception as e:  # inspector failure on an unsupported backend
        logger.error("Branch schema readiness check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Branch schema is not ready — run the branch migration",
        ) from e

    missing = [f"{t}.{c}" for t, c in _SCHEMA_REQUIRED_COLUMNS if c not in table_cols.get(t, set())]
    if missing:
        logger.warning("Branch schema not ready, missing: %s", missing)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Branch schema is not ready — run the branch migration",
        )


def create_product_with_opening_stock(
    db: Session,
    *,
    user: User,
    name: str,
    category_id: Optional[int],
    stock_qty: Union[Decimal, float, int, str],
    reserved_qty: Union[Decimal, float, int, str],
    cost_price: Decimal,
    selling_price: Decimal,
    is_active: bool = True,
    expiry_date: Optional[date] = None,
    explicit_branch_id: Optional[int] = None,
    header_branch_id: Optional[str] = None,
) -> Product:
    """Atomically create a tenant-wide Product plus its selected-branch inventory.

    Order (all-or-nothing):
      resolve authenticated tenant → require one concrete active branch →
      validate access → create Product → create BranchProductStock for the
      selected branch only → apply opening stock (OPENING_STOCK movement only
      when non-zero) → sync Product.stock_qty shadow → commit.

    Any failure rolls back the whole transaction. No partial Product row is
    left behind, other branches stay at zero, and the legacy stock shadow
    equals the total branch stock.
    """
    from .product_barcodes import BarcodeAllocationError, generate_unique_barcode

    assert_branch_schema_ready(db)

    tid = user.tenant_id
    opening = to_qty(stock_qty)
    reserved = to_qty(reserved_qty)
    if opening < ZERO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock quantity cannot be negative",
        )
    if reserved < ZERO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reserved quantity cannot be negative",
        )

    write_branch = require_operational_branch(
        db,
        user,
        explicit_branch_id=explicit_branch_id,
        header_branch_id=header_branch_id,
    )

    last_err: Optional[Exception] = None
    for _attempt in range(8):
        try:
            product = Product(
                name=name,
                barcode=generate_unique_barcode(db, user),
                category_id=category_id,
                stock_qty=0.0,
                reserved_qty=float(reserved),
                cost_price=cost_price,
                selling_price=selling_price,
                is_active=is_active,
                expiry_date=expiry_date,
                tenant_id=tid,
            )
            db.add(product)
            db.flush()

            bps = BranchProductStock(
                tenant_id=tid,
                branch_id=int(write_branch.id),
                product_id=product.id,
                stock_qty=ZERO,
                reserved_qty=ZERO,
                seeded_from_legacy=False,
            )
            db.add(bps)
            db.flush()

            if opening > ZERO:
                increase_branch_stock(
                    db,
                    tenant_id=tid,
                    branch_id=write_branch.id,
                    product_id=product.id,
                    quantity=opening,
                    reason="Initial stock",
                    movement_type=MOVEMENT_OPENING_STOCK,
                    actor_user_id=user.id,
                )
            else:
                sync_legacy_product_stock(db, product.id)

            db.commit()
            db.refresh(product)
            return product
        except BarcodeAllocationError as e:
            db.rollback()
            logger.error("AUTO barcode namespace exhausted during product create: %s", e)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="AUTO barcode namespace exhausted — cannot allocate a unique barcode",
            ) from e
        except HTTPException:
            db.rollback()
            raise
        except IntegrityError as e:
            db.rollback()
            last_err = e
            msg = str(e).lower()
            if "barcode" in msg or "unique" in msg:
                # Concurrent AUTO-* collision — retry with the next code.
                continue
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conflict creating product (duplicate barcode or branch inventory)",
            ) from e
        except OperationalError as e:
            db.rollback()
            logger.error("Branch schema not ready during product create: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Branch schema is not ready — run the branch migration",
            ) from e
        except Exception as e:
            db.rollback()
            raise

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Duplicate barcode — could not allocate a unique barcode; please retry",
    ) from last_err
