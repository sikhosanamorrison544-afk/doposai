"""
Section 15 — inter-branch stock transfer API.

Prefix: /api/transfers

A stock transfer is an internal inventory movement ONLY. It must never create
a Sale, Payment, Expense, Withdrawal, Accounting journal entry, revenue, or COGS.

Lifecycle (strict):
    DRAFT -> REQUESTED -> APPROVED -> DISPATCHED -> RECEIVED
Terminal:
    REJECTED (from REQUESTED)
    CANCELLED (from DRAFT or REQUESTED; from APPROVED only if nothing dispatched)

BranchProductStock is the authoritative stock source; Product.stock_qty is only
the legacy compatibility shadow (sum of physical branch stock).

- Approval only RESERVES (reserved_qty) at the source branch — no stock moves.
- Dispatch reduces source on-hand and releases the matching reservation.
- Receipt increases destination on-hand (partial receives allowed).

Idempotency: ``client_transfer_id`` on create; ``client_movement_id`` on receive
(one key per receive event — supply a fresh key for each partial receive call).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .branch_context import user_has_branch_access
from .database import get_db
from .models import User
from .permissions import Perm, dep_perm
from .transfer_service import (
    add_transfer_item,
    approve_transfer,
    cancel_transfer,
    create_transfer,
    delete_transfer_draft,
    delete_transfer_item,
    dispatch_transfer,
    get_transfer,
    list_transfers,
    receive_transfer,
    reject_transfer,
    request_transfer,
    transfer_to_dict,
    update_transfer_draft,
    update_transfer_item,
)

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


class TransferItemIn(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)


class TransferCreateIn(BaseModel):
    from_branch_id: int
    to_branch_id: int
    notes: Optional[str] = None
    items: Optional[List[TransferItemIn]] = None
    client_transfer_id: Optional[str] = Field(None, max_length=64)


class TransferItemUpdateIn(BaseModel):
    quantity: float = Field(gt=0)


class TransferDraftUpdateIn(BaseModel):
    notes: Optional[str] = None


class NotesIn(BaseModel):
    notes: Optional[str] = None


class RejectIn(BaseModel):
    reason: str


class CancelIn(BaseModel):
    reason: Optional[str] = None


class ReceiveLineIn(BaseModel):
    item_id: int
    accepted: float = 0
    damaged: float = 0
    missing: float = 0


class ReceiveIn(BaseModel):
    lines: List[ReceiveLineIn]
    notes: Optional[str] = None
    client_movement_id: Optional[str] = Field(None, max_length=64)


def _mutate(db: Session, fn, *args, **kwargs):
    """Run a mutating service call then commit; roll back on ANY error so the
    shared request session is never left with a half-applied transaction."""
    try:
        result = fn(*args, **kwargs)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def _ensure_branch_visible(db: Session, user: User, t) -> None:
    """404 unless the caller may see at least one of the transfer's branches."""
    if user_has_branch_access(db, user, t.from_branch_id) or user_has_branch_access(
        db, user, t.to_branch_id
    ):
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")


@router.get("")
def api_list_transfers(
    from_branch_id: Optional[int] = Query(None),
    to_branch_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_VIEW)),
):
    rows = list_transfers(
        db,
        user,
        from_branch_id=from_branch_id,
        to_branch_id=to_branch_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return [transfer_to_dict(t, db) for t in rows]


@router.get("/{transfer_id}")
def api_get_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_VIEW)),
):
    t = get_transfer(db, user, transfer_id)
    _ensure_branch_visible(db, user, t)
    return transfer_to_dict(t, db)


@router.post("", status_code=status.HTTP_201_CREATED)
def api_create_transfer(
    body: TransferCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CREATE)),
):
    items = [
        {"product_id": i.product_id, "quantity": i.quantity} for i in (body.items or [])
    ]
    t = _mutate(
        db,
        create_transfer,
        db,
        user,
        from_branch_id=body.from_branch_id,
        to_branch_id=body.to_branch_id,
        notes=body.notes,
        items=items,
        client_transfer_id=body.client_transfer_id,
    )
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.post("/{transfer_id}/items", status_code=status.HTTP_201_CREATED)
def api_add_transfer_item(
    transfer_id: int,
    body: TransferItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CREATE)),
):
    t = _mutate(
        db,
        add_transfer_item,
        db,
        user,
        transfer_id,
        product_id=body.product_id,
        quantity=body.quantity,
    )
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.put("/{transfer_id}/items/{item_id}")
def api_update_transfer_item(
    transfer_id: int,
    item_id: int,
    body: TransferItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CREATE)),
):
    t = _mutate(
        db, update_transfer_item, db, user, transfer_id, item_id, quantity=body.quantity
    )
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.delete("/{transfer_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_transfer_item(
    transfer_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CREATE)),
):
    _mutate(db, delete_transfer_item, db, user, transfer_id, item_id)
    return None


@router.patch("/{transfer_id}")
def api_update_transfer_draft(
    transfer_id: int,
    body: TransferDraftUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CREATE)),
):
    t = _mutate(db, update_transfer_draft, db, user, transfer_id, notes=body.notes)
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_transfer_draft(
    transfer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CREATE)),
):
    _mutate(db, delete_transfer_draft, db, user, transfer_id)
    return None


@router.post("/{transfer_id}/request")
def api_request_transfer(
    transfer_id: int,
    body: NotesIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_REQUEST)),
):
    t = _mutate(db, request_transfer, db, user, transfer_id, notes=body.notes)
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.post("/{transfer_id}/approve")
def api_approve_transfer(
    transfer_id: int,
    body: NotesIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_APPROVE)),
):
    t = _mutate(db, approve_transfer, db, user, transfer_id, notes=body.notes)
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.post("/{transfer_id}/reject")
def api_reject_transfer(
    transfer_id: int,
    body: RejectIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_REJECT)),
):
    t = _mutate(db, reject_transfer, db, user, transfer_id, reason=body.reason)
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.post("/{transfer_id}/cancel")
def api_cancel_transfer(
    transfer_id: int,
    body: CancelIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_CANCEL)),
):
    t = _mutate(db, cancel_transfer, db, user, transfer_id, reason=body.reason)
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.post("/{transfer_id}/dispatch")
def api_dispatch_transfer(
    transfer_id: int,
    body: NotesIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_DISPATCH)),
):
    t = _mutate(db, dispatch_transfer, db, user, transfer_id, notes=body.notes)
    db.refresh(t)
    return transfer_to_dict(t, db)


@router.post("/{transfer_id}/receive")
def api_receive_transfer(
    transfer_id: int,
    body: ReceiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.BRANCH_TRANSFER_RECEIVE)),
):
    lines = [
        {
            "item_id": ln.item_id,
            "accepted": ln.accepted,
            "damaged": ln.damaged,
            "missing": ln.missing,
        }
        for ln in body.lines
    ]
    t = _mutate(
        db,
        receive_transfer,
        db,
        user,
        transfer_id,
        lines=lines,
        notes=body.notes,
        client_movement_id=body.client_movement_id,
    )
    db.refresh(t)
    return transfer_to_dict(t, db)
