"""
Section 15 — inter-branch stock transfer service.

A stock transfer is an internal inventory movement ONLY. It must never create
a Sale, Payment, Expense, Withdrawal, Accounting journal entry, revenue, or
COGS.

Lifecycle (strict):
    DRAFT -> REQUESTED -> APPROVED -> DISPATCHED -> RECEIVED
Terminal:
    REJECTED (from REQUESTED)
    CANCELLED (from DRAFT or REQUESTED; from APPROVED only if nothing dispatched)

Stock source of truth is BranchProductStock:
    stock_qty    = physical on-hand
    reserved_qty = approved-but-not-yet-dispatched
    available    = on_hand - reserved
Product.stock_qty is only a compatibility shadow (sum of physical branch stock,
i.e. excludes in-transit).

All quantities are Decimal / NUMERIC(18,4). Row locks used via
``inventory_service.lock_branch_stock`` (SELECT ... FOR UPDATE).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .branch_context import list_accessible_branch_ids, require_branch_access
from .enterprise_models import (
    Branch,
    BranchProductStock,
    StockTransfer,
    StockTransferItem,
    TRANSFER_STATUS_APPROVED,
    TRANSFER_STATUS_CANCELLED,
    TRANSFER_STATUS_DISPATCHED,
    TRANSFER_STATUS_DRAFT,
    TRANSFER_STATUS_IN_TRANSIT,
    TRANSFER_STATUS_RECEIVED,
    TRANSFER_STATUS_REJECTED,
    TRANSFER_STATUS_REQUESTED,
)
from .inventory_service import (
    MOVEMENT_TRANSFER_DISPATCH,
    MOVEMENT_TRANSFER_RECEIPT,
    REFERENCE_STOCK_TRANSFER,
    ZERO,
    fmt_qty,
    lock_branch_stock,
    sync_legacy_product_stock,
    to_qty,
)
from .models import InventoryMovement, Product, User
from .tenant_scope import get_scoped, tenant_id_for_row

# Legacy "in_transit" is equivalent to "dispatched" for the v2 lifecycle.
_STATUS_DISPATCHED_LIKE = (TRANSFER_STATUS_DISPATCHED, TRANSFER_STATUS_IN_TRANSIT)

_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    TRANSFER_STATUS_DRAFT: (TRANSFER_STATUS_REQUESTED, TRANSFER_STATUS_CANCELLED),
    TRANSFER_STATUS_REQUESTED: (
        TRANSFER_STATUS_APPROVED,
        TRANSFER_STATUS_REJECTED,
        TRANSFER_STATUS_CANCELLED,
    ),
    TRANSFER_STATUS_APPROVED: (TRANSFER_STATUS_DISPATCHED, TRANSFER_STATUS_CANCELLED),
    TRANSFER_STATUS_DISPATCHED: (TRANSFER_STATUS_RECEIVED,),
    TRANSFER_STATUS_IN_TRANSIT: (TRANSFER_STATUS_RECEIVED,),
    TRANSFER_STATUS_RECEIVED: (),
    TRANSFER_STATUS_REJECTED: (),
    TRANSFER_STATUS_CANCELLED: (),
}


def _now() -> datetime:
    return datetime.utcnow()


def _money(value) -> Decimal:
    """Currency snapshot at 4 decimal places (never float)."""
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    except Exception:
        return Decimal("0.0000")


def _normalize_status(status: str) -> str:
    if status == TRANSFER_STATUS_IN_TRANSIT:
        return TRANSFER_STATUS_DISPATCHED
    return status


def _ensure_status(t: StockTransfer, allowed: Tuple[str, ...]) -> None:
    cur = _normalize_status(t.status or TRANSFER_STATUS_DRAFT)
    for a in allowed:
        if cur == a or t.status == a:
            return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"Invalid transfer transition from '{t.status}'",
    )


def get_transfer(
    db: Session, user: User, transfer_id: int, *, for_update: bool = False
) -> StockTransfer:
    """Tenant-scoped transfer lookup. Returns 404 without leaking cross-tenant data."""
    q = get_scoped(db, StockTransfer, transfer_id, user)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
    if for_update:
        q = db.query(StockTransfer).filter(StockTransfer.id == transfer_id).with_for_update().one()
    return q


def _require_source_destination_access(
    db: Session, user: User, transfer: StockTransfer
) -> Tuple[Branch, Branch]:
    src = require_branch_access(db, user, transfer.from_branch_id)
    dst = require_branch_access(db, user, transfer.to_branch_id)
    if src.tenant_id != transfer.tenant_id or dst.tenant_id != transfer.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transfer branches must belong to the same tenant",
        )
    if int(src.id) == int(dst.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Branches must differ")
    return src, dst


def _lock_rows(
    db: Session, tenant_id: Optional[int], branch_id: int, product_ids: List[int]
) -> Dict[int, BranchProductStock]:
    rows: Dict[int, BranchProductStock] = {}
    for pid in sorted(set(int(p) for p in product_ids)):
        rows[pid] = lock_branch_stock(
            db, tenant_id=tenant_id, branch_id=int(branch_id), product_id=pid
        )
    return rows


def _record_transfer_movement(
    db: Session,
    *,
    tenant_id: Optional[int],
    branch_id: int,
    product_id: int,
    change: Decimal,
    reason: str,
    movement_type: str,
    actor_user_id: Optional[int],
    client_movement_id: Optional[str],
    reference_id: int,
) -> InventoryMovement:
    full_reason = reason
    if movement_type and not reason.upper().startswith(movement_type):
        full_reason = f"{movement_type}: {reason}"
    kwargs: dict = {
        "product_id": int(product_id),
        "change_qty": float(change),
        "reason": full_reason[:80],
        "tenant_id": tenant_id,
        "branch_id": int(branch_id),
        "client_movement_id": client_movement_id,
        "movement_type": movement_type,
        "reference_type": REFERENCE_STOCK_TRANSFER,
        "reference_id": int(reference_id),
    }
    mov = InventoryMovement(**kwargs)
    db.add(mov)
    db.flush()
    return mov


def _movement_exists(db: Session, client_movement_id: str) -> bool:
    return (
        db.query(InventoryMovement.id)
        .filter(InventoryMovement.client_movement_id == client_movement_id)
        .first()
        is not None
    )


# --- Serialization ----------------------------------------------------------


def transfer_to_dict(t: StockTransfer) -> dict:
    items = []
    for it in t.items:
        items.append(
            {
                "id": it.id,
                "product_id": it.product_id,
                "product_name": it.product_name,
                "quantity_requested": fmt_qty(it.requested_quantity),
                "quantity_approved": fmt_qty(it.approved_quantity),
                "quantity_dispatched": fmt_qty(it.dispatched_quantity),
                "quantity_received": fmt_qty(it.quantity_received),
                "quantity_damaged": fmt_qty(it.quantity_damaged),
                "quantity_missing": fmt_qty(it.quantity_missing),
                "in_transit_quantity": fmt_qty(it.in_transit_quantity),
                "unit_cost_snapshot": (
                    fmt_qty(it.unit_cost_snapshot) if it.unit_cost_snapshot is not None else None
                ),
                "dispatched_value": fmt_qty(it.dispatched_value),
                "received_value": fmt_qty(it.received_value),
                "damaged_value": fmt_qty(it.damaged_value),
                "notes": it.notes,
            }
        )
    return {
        "id": t.id,
        "transfer_number": t.transfer_number,
        "tenant_id": t.tenant_id,
        "from_branch_id": t.from_branch_id,
        "to_branch_id": t.to_branch_id,
        "status": t.status,
        "notes": t.notes,
        "request_notes": t.request_notes,
        "approval_notes": t.approval_notes,
        "dispatch_notes": t.dispatch_notes,
        "receipt_notes": t.receipt_notes,
        "rejection_reason": t.rejection_reason,
        "cancellation_reason": t.cancellation_reason,
        "client_transfer_id": t.client_transfer_id,
        "created_by": t.created_by,
        "requested_by_id": t.requested_by_id,
        "approved_by_id": t.approved_by_id,
        "dispatched_by_id": t.dispatched_by_id,
        "received_by": t.received_by,
        "rejected_by_id": t.rejected_by_id,
        "cancelled_by_id": t.cancelled_by_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "requested_at": t.requested_at.isoformat() if t.requested_at else None,
        "approved_at": t.approved_at.isoformat() if t.approved_at else None,
        "dispatched_at": t.dispatched_at.isoformat() if t.dispatched_at else None,
        "received_at": t.received_at.isoformat() if t.received_at else None,
        "rejected_at": t.rejected_at.isoformat() if t.rejected_at else None,
        "cancelled_at": t.cancelled_at.isoformat() if t.cancelled_at else None,
        "items": items,
    }


def list_transfers(
    db: Session,
    user: User,
    *,
    from_branch_id: Optional[int] = None,
    to_branch_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[StockTransfer]:
    """Tenant-scoped transfer list; caller must have access to source or destination."""
    q = db.query(StockTransfer)
    if user.tenant_id is None:
        q = q.filter(StockTransfer.tenant_id.is_(None))
    else:
        q = q.filter(StockTransfer.tenant_id == user.tenant_id)
    accessible = list_accessible_branch_ids(db, user)
    if accessible:
        q = q.filter(
            or_(
                StockTransfer.from_branch_id.in_(accessible),
                StockTransfer.to_branch_id.in_(accessible),
            )
        )
    else:
        q = q.filter(or_(False))
    if from_branch_id is not None:
        q = q.filter(StockTransfer.from_branch_id == int(from_branch_id))
    if to_branch_id is not None:
        q = q.filter(StockTransfer.to_branch_id == int(to_branch_id))
    if status_filter:
        q = q.filter(StockTransfer.status == _normalize_status(status_filter))
    return (
        q.order_by(StockTransfer.created_at.desc(), StockTransfer.id.desc())
        .offset(int(offset))
        .limit(int(limit))
        .all()
    )


# --- Create / edit (DRAFT only) -------------------------------------------

_DRAFT_EDITABLE = (TRANSFER_STATUS_DRAFT,)


def create_transfer(
    db: Session,
    user: User,
    *,
    from_branch_id: int,
    to_branch_id: int,
    notes: Optional[str] = None,
    items: Optional[List[dict]] = None,
    client_transfer_id: Optional[str] = None,
) -> StockTransfer:
    src = require_branch_access(db, user, from_branch_id)
    dst = require_branch_access(db, user, to_branch_id)
    if int(src.id) == int(dst.id):
        raise HTTPException(status_code=400, detail="Branches must differ")
    if src.tenant_id != dst.tenant_id:
        raise HTTPException(status_code=400, detail="Branches must belong to the same tenant")

    tid = tenant_id_for_row(user)
    if client_transfer_id:
        existing = (
            db.query(StockTransfer)
            .filter(
                StockTransfer.tenant_id == tid
                if tid is not None
                else StockTransfer.tenant_id.is_(None),
                StockTransfer.client_transfer_id == client_transfer_id,
            )
            .first()
        )
        if existing is not None:
            return existing

    t = StockTransfer(
        tenant_id=tid,
        transfer_number=_next_transfer_number(db, tid),
        from_branch_id=int(src.id),
        to_branch_id=int(dst.id),
        notes=notes,
        status=TRANSFER_STATUS_DRAFT,
        created_by=user.id,
        client_transfer_id=client_transfer_id,
    )
    db.add(t)
    db.flush()
    for line in items or []:
        _add_item_to_transfer(db, user, t, line.get("product_id"), line.get("quantity"))
    return t


def _next_transfer_number(db: Session, tenant_id: Optional[int]) -> str:
    q = db.query(StockTransfer)
    if tenant_id is not None:
        n = q.filter(StockTransfer.tenant_id == tenant_id).count() + 1
    else:
        n = q.filter(StockTransfer.tenant_id.is_(None)).count() + 1
    return f"TR-{datetime.utcnow().strftime('%Y%m%d')}-{n:04d}"


def _add_item_to_transfer(
    db: Session, user: User, t: StockTransfer, product_id: int, quantity
) -> StockTransferItem:
    if t.status not in _DRAFT_EDITABLE:
        raise HTTPException(status_code=409, detail="Only draft transfers can be edited")
    p = db.query(Product).filter(Product.id == int(product_id)).first()
    if p is None or (p.tenant_id is not None and p.tenant_id != t.tenant_id):
        raise HTTPException(status_code=404, detail="Product not found")
    qty = to_qty(quantity)
    if qty <= ZERO:
        raise HTTPException(status_code=422, detail="Quantity must be positive")
    it = StockTransferItem(
        stock_transfer_id=t.id,
        product_id=p.id,
        product_name=p.name,
        quantity=qty,
    )
    db.add(it)
    db.flush()
    return it


def add_transfer_item(
    db: Session, user: User, transfer_id: int, *, product_id: int, quantity
) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    _add_item_to_transfer(db, user, t, product_id, quantity)
    return t


def update_transfer_item(
    db: Session, user: User, transfer_id: int, item_id: int, *, quantity
) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    if t.status not in _DRAFT_EDITABLE:
        raise HTTPException(status_code=409, detail="Only draft transfers can be edited")
    it = db.query(StockTransferItem).filter(
        StockTransferItem.id == item_id, StockTransferItem.stock_transfer_id == t.id
    ).first()
    if it is None:
        raise HTTPException(status_code=404, detail="Transfer item not found")
    qty = to_qty(quantity)
    if qty <= ZERO:
        raise HTTPException(status_code=422, detail="Quantity must be positive")
    it.quantity = qty
    db.flush()
    return t


def delete_transfer_item(
    db: Session, user: User, transfer_id: int, item_id: int
) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    if t.status not in _DRAFT_EDITABLE:
        raise HTTPException(status_code=409, detail="Only draft transfers can be edited")
    it = db.query(StockTransferItem).filter(
        StockTransferItem.id == item_id, StockTransferItem.stock_transfer_id == t.id
    ).first()
    if it is None:
        raise HTTPException(status_code=404, detail="Transfer item not found")
    db.delete(it)
    db.flush()
    return t


def update_transfer_draft(
    db: Session, user: User, transfer_id: int, *, notes: Optional[str] = None
) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    if t.status not in _DRAFT_EDITABLE:
        raise HTTPException(status_code=409, detail="Only draft transfers can be edited")
    if notes is not None:
        t.notes = notes
    db.flush()
    return t


def delete_transfer_draft(db: Session, user: User, transfer_id: int) -> None:
    t = get_transfer(db, user, transfer_id, for_update=True)
    if t.status not in _DRAFT_EDITABLE:
        raise HTTPException(status_code=409, detail="Only draft transfers can be deleted")
    db.delete(t)
    db.flush()


# --- Lifecycle --------------------------------------------------------------


def request_transfer(db: Session, user: User, transfer_id: int, *, notes: Optional[str] = None) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    _ensure_status(t, (TRANSFER_STATUS_DRAFT,))
    if not t.items:
        raise HTTPException(status_code=422, detail="Transfer must have at least one item")
    t.status = TRANSFER_STATUS_REQUESTED
    t.requested_by_id = user.id
    t.requested_at = _now()
    if notes is not None:
        t.request_notes = notes
    db.flush()
    return t


def approve_transfer(
    db: Session, user: User, transfer_id: int, *, notes: Optional[str] = None
) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    if t.status == TRANSFER_STATUS_APPROVED:
        return t  # idempotent — already reserved
    _ensure_status(t, (TRANSFER_STATUS_REQUESTED,))
    if not t.items:
        raise HTTPException(status_code=422, detail="Transfer must have at least one item")

    tid = t.tenant_id
    need: Dict[int, Decimal] = {}
    for it in t.items:
        qty = to_qty(it.approved_quantity if it.approved_quantity is not None else it.quantity)
        if qty <= ZERO:
            raise HTTPException(status_code=422, detail="Approved quantity must be positive")
        it.approved_quantity = qty
        need[int(it.product_id)] = need.get(int(it.product_id), ZERO) + qty

    # Deterministic lock order to avoid deadlocks; validate then reserve.
    rows = _lock_rows(db, tid, t.from_branch_id, list(need.keys()))
    for pid, row in rows.items():
        available = to_qty(row.stock_qty) - to_qty(row.reserved_qty)
        if available < need[pid]:
            product = db.query(Product).filter(Product.id == pid).first()
            name = product.name if product else str(pid)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Insufficient available stock for '{name}' at source branch. "
                    f"Available: {fmt_qty(available)}, Requested: {fmt_qty(need[pid])}"
                ),
            )
    for pid, row in rows.items():
        row.reserved_qty = to_qty(row.reserved_qty) + need[pid]
        db.add(row)

    t.status = TRANSFER_STATUS_APPROVED
    t.approved_by_id = user.id
    t.approved_at = _now()
    if notes is not None:
        t.approval_notes = notes
    db.flush()
    return t


def reject_transfer(db: Session, user: User, transfer_id: int, *, reason: str) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    _ensure_status(t, (TRANSFER_STATUS_REQUESTED,))
    t.status = TRANSFER_STATUS_REJECTED
    t.rejected_by_id = user.id
    t.rejected_at = _now()
    t.rejection_reason = reason
    db.flush()
    return t


def cancel_transfer(db: Session, user: User, transfer_id: int, *, reason: Optional[str] = None) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)

    cur = _normalize_status(t.status)
    if cur == TRANSFER_STATUS_APPROVED:
        # Only cancellable if nothing dispatched yet.
        for it in t.items:
            if it.dispatched_quantity > ZERO:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot cancel an approved transfer that has dispatched quantities",
                )
        _release_all_reservations(db, t)
        t.status = TRANSFER_STATUS_CANCELLED
        t.cancelled_by_id = user.id
        t.cancelled_at = _now()
        if reason is not None:
            t.cancellation_reason = reason
        db.flush()
        return t

    if cur in (TRANSFER_STATUS_DRAFT, TRANSFER_STATUS_REQUESTED):
        t.status = TRANSFER_STATUS_CANCELLED
        t.cancelled_by_id = user.id
        t.cancelled_at = _now()
        if reason is not None:
            t.cancellation_reason = reason
        db.flush()
        return t

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=f"Cannot cancel transfer in status '{t.status}'"
    )


def _release_all_reservations(db: Session, t: StockTransfer) -> None:
    tid = t.tenant_id
    per_product: Dict[int, Decimal] = {}
    for it in t.items:
        qty = to_qty(it.approved_quantity if it.approved_quantity is not None else it.quantity)
        per_product[int(it.product_id)] = per_product.get(int(it.product_id), ZERO) + qty
    rows = _lock_rows(db, tid, t.from_branch_id, list(per_product.keys()))
    for pid, row in rows.items():
        reserved = to_qty(row.reserved_qty)
        new_reserved = reserved - per_product[pid]
        if new_reserved < ZERO:
            new_reserved = ZERO
        row.reserved_qty = new_reserved
        db.add(row)


def dispatch_transfer(
    db: Session, user: User, transfer_id: int, *, notes: Optional[str] = None
) -> StockTransfer:
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    if _normalize_status(t.status) == TRANSFER_STATUS_DISPATCHED:
        return t  # idempotent
    _ensure_status(t, (TRANSFER_STATUS_APPROVED,))
    if not t.items:
        raise HTTPException(status_code=422, detail="Transfer must have at least one item")

    tid = t.tenant_id

    # Snapshot costs + per-item dispatch quantities, grouped by product.
    need: Dict[int, Decimal] = {}
    for it in t.items:
        if it.quantity_dispatched is not None:
            continue  # already dispatched in a previous partial-dispatch? (disallow below)
        qty = to_qty(it.approved_quantity if it.approved_quantity is not None else it.quantity)
        if qty <= ZERO:
            raise HTTPException(status_code=422, detail="Dispatch quantity must be positive")
        need[int(it.product_id)] = need.get(int(it.product_id), ZERO) + qty

    if not need:
        raise HTTPException(status_code=409, detail="Nothing to dispatch")

    rows = _lock_rows(db, tid, t.from_branch_id, list(need.keys()))
    # Validate on-hand before mutating any of the locked rows.
    for pid, row in rows.items():
        # reserved may have been released if partial; dispatch consumes on-hand,
        # releasing the matching reservation (reservation already held).
        if to_qty(row.stock_qty) < need[pid]:
            product = db.query(Product).filter(Product.id == pid).first()
            name = product.name if product else str(pid)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Insufficient on-hand stock for '{name}' to dispatch",
            )

    for it in t.items:
        product = db.query(Product).filter(Product.id == it.product_id).first()
        if it.unit_cost_snapshot is None and product is not None:
            it.unit_cost_snapshot = _money(product.cost_price)
        qty = to_qty(it.approved_quantity if it.approved_quantity is not None else it.quantity)
        it.quantity_dispatched = qty
        _record_transfer_movement(
            db,
            tenant_id=tid,
            branch_id=t.from_branch_id,
            product_id=it.product_id,
            change=-qty,
            reason=f"Transfer dispatch {t.transfer_number}",
            movement_type=MOVEMENT_TRANSFER_DISPATCH,
            actor_user_id=user.id,
            client_movement_id=f"disp:{t.id}:{it.id}",
            reference_id=t.id,
        )

    for pid, row in rows.items():
        qty = need[pid]
        # reduce on-hand and release the matching reservation.
        on_hand = to_qty(row.stock_qty) - qty
        reserved = to_qty(row.reserved_qty) - qty
        if reserved < ZERO:
            reserved = ZERO
        if on_hand < ZERO:
            on_hand = ZERO
        row.stock_qty = on_hand
        row.reserved_qty = reserved
        db.add(row)
        sync_legacy_product_stock(db, pid)

    t.status = TRANSFER_STATUS_DISPATCHED
    t.dispatched_by_id = user.id
    t.sent_at = _now()
    if notes is not None:
        t.dispatch_notes = notes
    db.flush()
    return t


def receive_transfer(
    db: Session,
    user: User,
    transfer_id: int,
    *,
    lines: List[dict],
    notes: Optional[str] = None,
    client_movement_id: Optional[str] = None,
) -> StockTransfer:
    """Receive accepted/damaged/missing per item. Partial receives allowed.

    ``lines`` is a list of ``{item_id, accepted, damaged, missing}`` quantities
    to ADD during this receive call. Damaged/missing reduce in-transit but do
    NOT enter destination on-hand.
    """
    t = get_transfer(db, user, transfer_id, for_update=True)
    _require_source_destination_access(db, user, t)
    if t.status == TRANSFER_STATUS_RECEIVED:
        return t  # idempotent
    _ensure_status(t, _STATUS_DISPATCHED_LIKE)

    op_key = client_movement_id or f"recv:{t.id}"
    tid = t.tenant_id
    item_map = {int(it.id): it for it in t.items}
    accepted_by_product: Dict[int, Decimal] = {}

    for line in lines:
        item_id = int(line.get("item_id"))
        it = item_map.get(item_id)
        if it is None:
            raise HTTPException(status_code=422, detail=f"Unknown transfer item {item_id}")
        accepted = to_qty(line.get("accepted", 0))
        damaged = to_qty(line.get("damaged", 0))
        missing = to_qty(line.get("missing", 0))
        if accepted < ZERO or damaged < ZERO or missing < ZERO:
            raise HTTPException(status_code=422, detail="Receipt quantities cannot be negative")
        delta = accepted + damaged + missing
        if delta <= ZERO:
            continue

        dispatched = it.dispatched_quantity
        already = (
            to_qty(it.quantity_received)
            + to_qty(it.quantity_damaged)
            + to_qty(it.quantity_missing)
        )
        if already + delta > dispatched:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Receipt for '{it.product_name}' would exceed dispatched quantity "
                    f"({fmt_qty(dispatched)})"
                ),
            )

        mov_key = f"{op_key}:{item_id}"
        if _movement_exists(db, mov_key):
            continue  # idempotent retry for this item

        if accepted > ZERO:
            accepted_by_product[int(it.product_id)] = (
                accepted_by_product.get(int(it.product_id), ZERO) + accepted
            )

        it.quantity_received = to_qty(it.quantity_received) + accepted
        it.quantity_damaged = to_qty(it.quantity_damaged) + damaged
        it.quantity_missing = to_qty(it.quantity_missing) + missing
        if notes is not None:
            it.receipt_notes = notes

        # One informational movement for the accepted quantity per item.
        if accepted > ZERO:
            _record_transfer_movement(
                db,
                tenant_id=tid,
                branch_id=t.to_branch_id,
                product_id=it.product_id,
                change=accepted,
                reason=f"Transfer receipt {t.transfer_number}",
                movement_type=MOVEMENT_TRANSFER_RECEIPT,
                actor_user_id=user.id,
                client_movement_id=mov_key,
                reference_id=t.id,
            )

    # Apply destination stock increases (deterministic lock order).
    if accepted_by_product:
        rows = _lock_rows(db, tid, t.to_branch_id, list(accepted_by_product.keys()))
        for pid, row in rows.items():
            row.stock_qty = to_qty(row.stock_qty) + accepted_by_product[pid]
            db.add(row)
            sync_legacy_product_stock(db, pid)

    # Complete only when every dispatched quantity is fully accounted.
    complete = True
    for it in t.items:
        accounted = (
            to_qty(it.quantity_received)
            + to_qty(it.quantity_damaged)
            + to_qty(it.quantity_missing)
        )
        if accounted < it.dispatched_quantity:
            complete = False
            break
    if complete:
        t.status = TRANSFER_STATUS_RECEIVED
        t.received_by = user.id
        t.received_at = _now()
    if notes is not None:
        t.receipt_notes = notes
    db.flush()
    return t