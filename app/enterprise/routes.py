"""
Enterprise API: suppliers, purchase orders, adjustments, transfers, branches, audit, reorder, statements.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..billing.feature_deps import require_feature
from ..billing.features import Feature
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import auth
from ..audit_service import log_audit
from ..database import get_db
from ..enterprise_models import (
    ADJ_STATUS_APPROVED,
    ADJ_STATUS_PENDING,
    ADJ_STATUS_REJECTED,
    ADJUSTMENT_TYPES,
    PO_STATUS_APPROVED,
    PO_STATUS_CANCELLED,
    PO_STATUS_DRAFT,
    PO_STATUS_PARTIALLY_RECEIVED,
    PO_STATUS_RECEIVED,
    PO_STATUS_SENT,
    TRANSFER_STATUS_CANCELLED,
    TRANSFER_STATUS_DRAFT,
    TRANSFER_STATUS_IN_TRANSIT,
    TRANSFER_STATUS_RECEIVED,
    AuditLog,
    Branch,
    BranchProductStock,
    PurchaseOrder,
    PurchaseOrderItem,
    StockAdjustment,
    StockTransfer,
    StockTransferItem,
    Supplier,
    SupplierLedgerEntry,
    WhatsappIntegration,
)
from ..models import Customer, LaybyCustomer, LaybyPayment, LaybyTransaction, Product, Sale, User
from ..permissions import Perm, dep_perm, has_permission, require_permission
from ..accounting_engine import AccountingEngine
from ..accounting_setup import verify_chart_of_accounts
from .. import tenant_scope
from ..tenant_scope import (
    filter_by_tenant,
    filter_sales_by_branch,
    get_scoped,
    is_branch_restricted,
    require_customer,
    row_visible,
    tenant_id_for_row,
)
from .inventory_ops import apply_product_stock_change, scoped_product
from ..email_service import email_service
from ..tenant_scope import first_store_settings_for_tenant
from .pdf_utils import customer_statement_pdf, purchase_order_pdf
from .statement_service import build_customer_statement

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/enterprise",
    tags=["enterprise"],
    dependencies=[Depends(require_feature(Feature.ENTERPRISE))],
)


# --- Schemas ---


class SupplierIn(BaseModel):
    business_name: str
    supplier_code: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_number: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None


class SupplierOut(SupplierIn):
    id: int
    balance: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BranchIn(BaseModel):
    name: str
    code: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    is_default: bool = False


class BranchOut(BranchIn):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class POItemIn(BaseModel):
    product_id: int
    quantity_ordered: float
    unit_cost: Decimal


class POCreate(BaseModel):
    supplier_id: int
    branch_id: Optional[int] = None
    notes: Optional[str] = None
    items: List[POItemIn]


class POReceiveItem(BaseModel):
    item_id: int
    quantity_received: float


class POReceive(BaseModel):
    items: List[POReceiveItem]


class AdjustmentIn(BaseModel):
    product_id: int
    branch_id: Optional[int] = None
    adjustment_type: str
    quantity_change: float
    reason: Optional[str] = None


class TransferItemIn(BaseModel):
    product_id: int
    quantity: float


class TransferCreate(BaseModel):
    from_branch_id: int
    to_branch_id: int
    notes: Optional[str] = None
    items: List[TransferItemIn]


def _next_po_number(db: Session, tenant_id: Optional[int]) -> str:
    prefix = "PO"
    q = db.query(func.max(PurchaseOrder.id))
    if tenant_id is not None:
        q = db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id == tenant_id)
        n = q.count() + 1
    else:
        n = db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id.is_(None)).count() + 1
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d')}-{n:04d}"


def _next_transfer_number(db: Session, tenant_id: Optional[int]) -> str:
    n = (
        db.query(StockTransfer)
        .filter(
            StockTransfer.tenant_id == tenant_id
            if tenant_id is not None
            else StockTransfer.tenant_id.is_(None)
        )
        .count()
        + 1
    )
    return f"TR-{datetime.utcnow().strftime('%Y%m%d')}-{n:04d}"


def _supplier_query(db: Session, user: User):
    return filter_by_tenant(db.query(Supplier), Supplier, user).filter(Supplier.is_active == True)


# --- Suppliers ---


@router.get("/suppliers", response_model=List[SupplierOut])
def list_suppliers(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_SUPPLIERS)),
):
    query = _supplier_query(db, user)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Supplier.business_name.ilike(term),
                Supplier.contact_person.ilike(term),
                Supplier.phone.ilike(term),
                Supplier.email.ilike(term),
            )
        )
    return query.order_by(Supplier.business_name).limit(500).all()


@router.post("/suppliers", response_model=SupplierOut)
def create_supplier(
    body: SupplierIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_SUPPLIERS)),
):
    s = Supplier(**body.model_dump(), tenant_id=tenant_id_for_row(user))
    db.add(s)
    db.flush()
    log_audit(
        db, user=user, action="create", entity_type="supplier", entity_id=s.id,
        new_value=body.model_dump(), request=request,
    )
    db.commit()
    db.refresh(s)
    return s


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_SUPPLIERS)),
):
    s = get_scoped(db, Supplier, supplier_id, user)
    if not s:
        raise HTTPException(404, "Supplier not found")
    return s


@router.put("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    body: SupplierIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_SUPPLIERS)),
):
    s = get_scoped(db, Supplier, supplier_id, user)
    if not s:
        raise HTTPException(404, "Supplier not found")
    old = {"business_name": s.business_name, "phone": s.phone}
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    log_audit(db, user=user, action="update", entity_type="supplier", entity_id=s.id, old_value=old, new_value=body.model_dump(), request=request)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_SUPPLIERS)),
):
    s = get_scoped(db, Supplier, supplier_id, user)
    if not s:
        raise HTTPException(404, "Supplier not found")
    s.is_active = False
    log_audit(db, user=user, action="deactivate", entity_type="supplier", entity_id=s.id, request=request)
    db.commit()
    return {"ok": True}


@router.get("/suppliers/{supplier_id}/ledger")
def supplier_ledger(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_SUPPLIERS)),
):
    s = get_scoped(db, Supplier, supplier_id, user)
    if not s:
        raise HTTPException(404, "Supplier not found")
    entries = (
        db.query(SupplierLedgerEntry)
        .filter(SupplierLedgerEntry.supplier_id == supplier_id)
        .order_by(SupplierLedgerEntry.created_at.desc())
        .limit(500)
        .all()
    )
    pos = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.supplier_id == supplier_id)
        .order_by(PurchaseOrder.created_at.desc())
        .limit(100)
        .all()
    )
    return {
        "supplier_id": supplier_id,
        "balance": float(s.balance),
        "ledger": [
            {
                "id": e.id,
                "amount": float(e.amount),
                "entry_type": e.entry_type,
                "reference_type": e.reference_type,
                "reference_id": e.reference_id,
                "notes": e.notes,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "purchase_orders": [
            {"id": p.id, "po_number": p.po_number, "status": p.status, "total": float(p.total), "created_at": p.created_at.isoformat()}
            for p in pos
        ],
    }


# --- Branches ---


@router.get("/branches", response_model=List[BranchOut])
def list_branches(
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_BRANCHES)),
):
    return filter_by_tenant(db.query(Branch), Branch, user).filter(Branch.is_active == True).order_by(Branch.name).all()


@router.post("/branches", response_model=BranchOut)
def create_branch(
    body: BranchIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_BRANCHES)),
):
    tid = tenant_id_for_row(user)
    if body.is_default:
        q = db.query(Branch).filter(Branch.is_default == True)
        if tid is not None:
            q = q.filter(Branch.tenant_id == tid)
        else:
            q = q.filter(Branch.tenant_id.is_(None))
        for b in q.all():
            b.is_default = False
    br = Branch(**body.model_dump(), tenant_id=tid)
    db.add(br)
    db.flush()
    log_audit(db, user=user, action="create", entity_type="branch", entity_id=br.id, new_value=body.model_dump(), request=request)
    db.commit()
    db.refresh(br)
    return br


@router.get("/branches/{branch_id}/stock")
def branch_stock(
    branch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.VIEW_INVENTORY)),
):
    br = get_scoped(db, Branch, branch_id, user)
    if not br:
        raise HTTPException(404, "Branch not found")
    rows = (
        db.query(BranchProductStock, Product)
        .join(Product, Product.id == BranchProductStock.product_id)
        .filter(BranchProductStock.branch_id == branch_id)
        .all()
    )
    return [
        {
            "product_id": p.id,
            "product_name": p.name,
            "stock_qty": bps.stock_qty,
            "tenant_stock_qty": p.stock_qty,
        }
        for bps, p in rows
    ]


# --- Purchase orders ---


@router.get("/purchase-orders")
def list_purchase_orders(
    status: Optional[str] = None,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING)),
):
    q = filter_by_tenant(db.query(PurchaseOrder), PurchaseOrder, user)
    if status:
        q = q.filter(PurchaseOrder.status == status)
    if supplier_id:
        q = q.filter(PurchaseOrder.supplier_id == supplier_id)
    orders = q.order_by(PurchaseOrder.created_at.desc()).limit(200).all()
    return [
        {
            "id": o.id,
            "po_number": o.po_number,
            "supplier_id": o.supplier_id,
            "status": o.status,
            "total": float(o.total),
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]


@router.post("/purchase-orders")
def create_purchase_order(
    body: POCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING)),
):
    sup = get_scoped(db, Supplier, body.supplier_id, user)
    if not sup:
        raise HTTPException(404, "Supplier not found")
    if not body.items:
        raise HTTPException(400, "At least one line item required")
    subtotal = Decimal("0")
    po = PurchaseOrder(
        tenant_id=tenant_id_for_row(user),
        branch_id=body.branch_id,
        supplier_id=body.supplier_id,
        po_number=_next_po_number(db, tenant_id_for_row(user)),
        status=PO_STATUS_DRAFT,
        created_by=user.id,
        notes=body.notes,
    )
    db.add(po)
    db.flush()
    for line in body.items:
        p = scoped_product(db, line.product_id, user)
        lt = Decimal(str(line.quantity_ordered)) * line.unit_cost
        subtotal += lt
        db.add(
            PurchaseOrderItem(
                purchase_order_id=po.id,
                product_id=p.id,
                product_name=p.name,
                quantity_ordered=line.quantity_ordered,
                unit_cost=line.unit_cost,
                line_total=lt,
            )
        )
    po.subtotal = subtotal
    po.total = subtotal
    log_audit(db, user=user, action="create", entity_type="purchase_order", entity_id=po.id, request=request)
    db.commit()
    return {"id": po.id, "po_number": po.po_number, "status": po.status, "total": float(po.total)}


@router.get("/purchase-orders/{po_id}")
def get_purchase_order(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING)),
):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    return {
        "id": po.id,
        "po_number": po.po_number,
        "supplier_id": po.supplier_id,
        "branch_id": po.branch_id,
        "status": po.status,
        "subtotal": float(po.subtotal),
        "total": float(po.total),
        "notes": po.notes,
        "items": [
            {
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product_name,
                "quantity_ordered": i.quantity_ordered,
                "quantity_received": i.quantity_received,
                "unit_cost": float(i.unit_cost),
                "line_total": float(i.line_total),
            }
            for i in po.items
        ],
    }


@router.put("/purchase-orders/{po_id}")
def update_purchase_order(
    po_id: int,
    body: POCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING)),
):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po or po.status != PO_STATUS_DRAFT:
        raise HTTPException(400, "Only draft POs can be edited")
    sup = get_scoped(db, Supplier, body.supplier_id, user)
    if not sup:
        raise HTTPException(404, "Supplier not found")
    for old in list(po.items):
        db.delete(old)
    po.supplier_id = body.supplier_id
    po.branch_id = body.branch_id
    po.notes = body.notes
    subtotal = Decimal("0")
    for line in body.items:
        p = scoped_product(db, line.product_id, user)
        lt = Decimal(str(line.quantity_ordered)) * line.unit_cost
        subtotal += lt
        db.add(
            PurchaseOrderItem(
                purchase_order_id=po.id,
                product_id=p.id,
                product_name=p.name,
                quantity_ordered=line.quantity_ordered,
                unit_cost=line.unit_cost,
                line_total=lt,
            )
        )
    po.subtotal = subtotal
    po.total = subtotal
    log_audit(db, user=user, action="update", entity_type="purchase_order", entity_id=po.id, request=request)
    db.commit()
    return {"id": po.id, "po_number": po.po_number, "status": po.status, "total": float(po.total)}


@router.post("/purchase-orders/{po_id}/send")
def send_po(po_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING))):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po or po.status != PO_STATUS_DRAFT:
        raise HTTPException(400, "PO not in draft")
    po.status = PO_STATUS_SENT
    po.sent_at = datetime.utcnow()
    log_audit(db, user=user, action="send", entity_type="purchase_order", entity_id=po.id, request=request)
    db.commit()
    return {"ok": True, "status": po.status}


@router.post("/purchase-orders/{po_id}/approve")
def approve_po(po_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING))):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po or po.status not in (PO_STATUS_DRAFT, PO_STATUS_SENT):
        raise HTTPException(400, "Cannot approve")
    po.status = PO_STATUS_APPROVED
    po.approved_at = datetime.utcnow()
    po.approved_by = user.id
    log_audit(db, user=user, action="approve", entity_type="purchase_order", entity_id=po.id, request=request)
    db.commit()
    return {"ok": True}


@router.post("/purchase-orders/{po_id}/receive")
def receive_po(
    po_id: int,
    body: POReceive,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.RECEIVE_STOCK)),
):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po or po.status in (PO_STATUS_CANCELLED, PO_STATUS_RECEIVED):
        raise HTTPException(400, "Cannot receive")
    item_map = {i.id: i for i in po.items}
    received_value = Decimal("0")
    for recv in body.items:
        it = item_map.get(recv.item_id)
        if not it:
            continue
        delta = recv.quantity_received
        if delta <= 0:
            continue
        remaining = float(it.quantity_ordered) - float(it.quantity_received)
        delta = min(delta, remaining)
        if delta <= 0:
            continue
        it.quantity_received = float(it.quantity_received) + delta
        line_value = Decimal(str(it.unit_cost)) * Decimal(str(delta))
        received_value += line_value
        apply_product_stock_change(
            db, it.product_id, delta, f"PO receive {po.po_number}",
            branch_id=po.branch_id,
            update_cost=float(it.unit_cost),
        )
    all_received = all(float(i.quantity_received) >= float(i.quantity_ordered) for i in po.items)
    any_received = any(float(i.quantity_received) > 0 for i in po.items)
    if all_received:
        po.status = PO_STATUS_RECEIVED
        po.received_at = datetime.utcnow()
    elif any_received:
        po.status = PO_STATUS_PARTIALLY_RECEIVED
    if po.status == PO_STATUS_RECEIVED:
        sup = db.get(Supplier, po.supplier_id)
        if sup:
            existing = (
                db.query(SupplierLedgerEntry)
                .filter(
                    SupplierLedgerEntry.reference_type == "purchase_order",
                    SupplierLedgerEntry.reference_id == po.id,
                )
                .first()
            )
            if not existing:
                entry = SupplierLedgerEntry(
                    supplier_id=sup.id,
                    tenant_id=po.tenant_id,
                    amount=po.total,
                    entry_type="purchase",
                    reference_type="purchase_order",
                    reference_id=po.id,
                    created_by=user.id,
                )
                sup.balance = Decimal(str(sup.balance)) + po.total
                db.add(entry)
    if received_value > 0 and verify_chart_of_accounts(db):
        try:
            AccountingEngine(db).post_purchase_receive(
                po_id=po.id,
                po_number=po.po_number,
                amount=received_value,
                created_by=user.id,
            )
        except Exception as e:
            logger.error("Accounting post for PO %s failed: %s", po.id, e, exc_info=True)
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Accounting error: {e}")
    log_audit(db, user=user, action="receive", entity_type="purchase_order", entity_id=po.id, request=request)
    db.commit()
    return {"ok": True, "status": po.status, "received_value": float(received_value)}


@router.post("/purchase-orders/{po_id}/cancel")
def cancel_po(po_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING))):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po:
        raise HTTPException(404)
    if po.status == PO_STATUS_RECEIVED:
        raise HTTPException(400, "Cannot cancel received PO")
    po.status = PO_STATUS_CANCELLED
    log_audit(db, user=user, action="cancel", entity_type="purchase_order", entity_id=po.id, request=request)
    db.commit()
    return {"ok": True}


@router.delete("/purchase-orders/{po_id}")
def delete_po(po_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_PURCHASING))):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po or po.status != PO_STATUS_DRAFT:
        raise HTTPException(400, "Only draft POs can be deleted")
    log_audit(db, user=user, action="delete", entity_type="purchase_order", entity_id=po.id, request=request)
    db.delete(po)
    db.commit()
    return {"ok": True}


@router.get("/purchase-orders/{po_id}/pdf")
def po_pdf(po_id: int, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.EXPORT_DATA))):
    po = get_scoped(db, PurchaseOrder, po_id, user)
    if not po:
        raise HTTPException(404)
    sup = db.get(Supplier, po.supplier_id)
    pdf = purchase_order_pdf(po, sup.business_name if sup else "", po.items)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{po.po_number}.pdf"'})


# --- Stock adjustments ---


@router.get("/adjustments")
def list_adjustments(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.VIEW_INVENTORY)),
):
    q = filter_by_tenant(db.query(StockAdjustment), StockAdjustment, user)
    if status:
        q = q.filter(StockAdjustment.status == status)
    rows = q.order_by(StockAdjustment.created_at.desc()).limit(200).all()
    return [
        {
            "id": r.id,
            "product_id": r.product_id,
            "adjustment_type": r.adjustment_type,
            "quantity_change": r.quantity_change,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/adjustments")
def create_adjustment(
    body: AdjustmentIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.MANAGE_INVENTORY)),
):
    if body.adjustment_type not in ADJUSTMENT_TYPES:
        raise HTTPException(400, f"Invalid type. Use: {ADJUSTMENT_TYPES}")
    scoped_product(db, body.product_id, user)
    auto_approve = has_permission(user, Perm.APPROVE_ADJUSTMENTS)
    adj = StockAdjustment(
        tenant_id=tenant_id_for_row(user),
        branch_id=body.branch_id,
        product_id=body.product_id,
        adjustment_type=body.adjustment_type,
        quantity_change=body.quantity_change,
        reason=body.reason,
        status=ADJ_STATUS_APPROVED if auto_approve else ADJ_STATUS_PENDING,
        created_by=user.id,
        approved_by=user.id if auto_approve else None,
        approved_at=datetime.utcnow() if auto_approve else None,
    )
    db.add(adj)
    db.flush()
    if auto_approve:
        apply_product_stock_change(
            db, body.product_id, body.quantity_change,
            f"Adjustment {body.adjustment_type}",
            branch_id=body.branch_id,
        )
    log_audit(db, user=user, action="create", entity_type="stock_adjustment", entity_id=adj.id, request=request)
    db.commit()
    return {"id": adj.id, "status": adj.status}


@router.post("/adjustments/{adj_id}/approve")
def approve_adjustment(
    adj_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.APPROVE_ADJUSTMENTS)),
):
    adj = get_scoped(db, StockAdjustment, adj_id, user)
    if not adj or adj.status != ADJ_STATUS_PENDING:
        raise HTTPException(400, "Not pending")
    apply_product_stock_change(
        db, adj.product_id, adj.quantity_change,
        f"Adjustment approved {adj.adjustment_type}",
        branch_id=adj.branch_id,
    )
    adj.status = ADJ_STATUS_APPROVED
    adj.approved_by = user.id
    adj.approved_at = datetime.utcnow()
    log_audit(db, user=user, action="approve", entity_type="stock_adjustment", entity_id=adj.id, request=request)
    db.commit()
    return {"ok": True}


@router.post("/adjustments/{adj_id}/reject")
def reject_adjustment(adj_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.APPROVE_ADJUSTMENTS))):
    adj = get_scoped(db, StockAdjustment, adj_id, user)
    if not adj or adj.status != ADJ_STATUS_PENDING:
        raise HTTPException(400, "Not pending")
    adj.status = ADJ_STATUS_REJECTED
    log_audit(db, user=user, action="reject", entity_type="stock_adjustment", entity_id=adj.id, request=request)
    db.commit()
    return {"ok": True}


# --- Stock transfers ---


@router.get("/transfers")
def list_transfers(db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_TRANSFERS))):
    rows = filter_by_tenant(db.query(StockTransfer), StockTransfer, user).order_by(StockTransfer.created_at.desc()).limit(200).all()
    return [{"id": t.id, "transfer_number": t.transfer_number, "status": t.status, "from_branch_id": t.from_branch_id, "to_branch_id": t.to_branch_id} for t in rows]


@router.post("/transfers")
def create_transfer(body: TransferCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_TRANSFERS))):
    if body.from_branch_id == body.to_branch_id:
        raise HTTPException(400, "Branches must differ")
    t = StockTransfer(
        tenant_id=tenant_id_for_row(user),
        transfer_number=_next_transfer_number(db, tenant_id_for_row(user)),
        from_branch_id=body.from_branch_id,
        to_branch_id=body.to_branch_id,
        notes=body.notes,
        created_by=user.id,
    )
    db.add(t)
    db.flush()
    for line in body.items:
        p = scoped_product(db, line.product_id, user)
        db.add(StockTransferItem(stock_transfer_id=t.id, product_id=p.id, product_name=p.name, quantity=line.quantity))
    log_audit(db, user=user, action="create", entity_type="stock_transfer", entity_id=t.id, request=request)
    db.commit()
    return {"id": t.id, "transfer_number": t.transfer_number}


@router.post("/transfers/{transfer_id}/send")
def send_transfer(transfer_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_TRANSFERS))):
    t = get_scoped(db, StockTransfer, transfer_id, user)
    if not t or t.status != TRANSFER_STATUS_DRAFT:
        raise HTTPException(400, "Invalid transfer")
    for it in t.items:
        apply_product_stock_change(db, it.product_id, -it.quantity, f"Transfer out {t.transfer_number}", branch_id=t.from_branch_id)
    t.status = TRANSFER_STATUS_IN_TRANSIT
    t.sent_at = datetime.utcnow()
    log_audit(db, user=user, action="send", entity_type="stock_transfer", entity_id=t.id, request=request)
    db.commit()
    return {"ok": True}


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(transfer_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_TRANSFERS))):
    t = get_scoped(db, StockTransfer, transfer_id, user)
    if not t or t.status != TRANSFER_STATUS_IN_TRANSIT:
        raise HTTPException(400, "Not in transit")
    for it in t.items:
        it.quantity_received = it.quantity
        apply_product_stock_change(db, it.product_id, it.quantity, f"Transfer in {t.transfer_number}", branch_id=t.to_branch_id)
    t.status = TRANSFER_STATUS_RECEIVED
    t.received_at = datetime.utcnow()
    t.received_by = user.id
    log_audit(db, user=user, action="receive", entity_type="stock_transfer", entity_id=t.id, request=request)
    db.commit()
    return {"ok": True}


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(transfer_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_TRANSFERS))):
    t = get_scoped(db, StockTransfer, transfer_id, user)
    if not t:
        raise HTTPException(404)
    if t.status == TRANSFER_STATUS_IN_TRANSIT:
        raise HTTPException(400, "Cannot cancel in-transit transfer")
    t.status = TRANSFER_STATUS_CANCELLED
    log_audit(db, user=user, action="cancel", entity_type="stock_transfer", entity_id=t.id, request=request)
    db.commit()
    return {"ok": True}


# --- Audit ---


@router.get("/audit-logs")
def audit_logs(
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.VIEW_AUDIT)),
):
    q = filter_by_tenant(db.query(AuditLog), AuditLog, user)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if action:
        q = q.filter(AuditLog.action == action)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if from_date:
        q = q.filter(AuditLog.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        q = q.filter(AuditLog.created_at <= datetime.fromisoformat(to_date))
    rows = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "device": r.device,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/audit-logs/export.csv")
def export_audit(
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.EXPORT_DATA)),
):
    rows = filter_by_tenant(db.query(AuditLog), AuditLog, user).order_by(AuditLog.created_at.desc()).limit(5000).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "username", "action", "entity_type", "entity_id", "created_at"])
    for r in rows:
        w.writerow([r.id, r.username, r.action, r.entity_type, r.entity_id, r.created_at.isoformat()])
    return Response(content=buf.getvalue(), media_type="text/csv")


# --- Reorder suggestions ---


@router.get("/reorder-suggestions")
def reorder_suggestions(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.VIEW_INVENTORY)),
):
    from ..models import SaleItem

    since = datetime.utcnow() - timedelta(days=days)
    products = filter_by_tenant(db.query(Product), Product, user).filter(Product.is_active == True).all()
    suggestions = []
    for p in products:
        sold = (
            db.query(func.coalesce(func.sum(SaleItem.quantity), 0))
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(SaleItem.product_id == p.id, Sale.created_at >= since)
        )
        if user.tenant_id is not None:
            sold = sold.filter(Sale.tenant_id == user.tenant_id)
        else:
            sold = sold.filter(Sale.tenant_id.is_(None))
        total_sold = int(sold.scalar() or 0)
        daily = total_sold / max(days, 1)
        weekly = daily * 7
        monthly = daily * 30
        threshold = float(p.low_stock_threshold or 10)
        current = float(p.stock_qty)
        if current <= threshold or weekly > current:
            suggested = max(0, int(weekly * 2 - current))
            if suggested < 1 and current <= threshold:
                suggested = int(threshold * 2)
            suggestions.append({
                "product_id": p.id,
                "product_name": p.name,
                "current_stock": current,
                "avg_daily_sales": round(daily, 2),
                "avg_weekly_sales": round(weekly, 2),
                "avg_monthly_sales": round(monthly, 2),
                "suggested_reorder": suggested,
                "low_stock_threshold": threshold,
            })
    suggestions.sort(key=lambda x: x["current_stock"] - x["avg_weekly_sales"])
    return suggestions


# --- Customer statements ---


class StatementEmailRequest(BaseModel):
    to_email: Optional[str] = None


@router.get("/customers/{customer_id}/statement")
def customer_statement(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    c = require_customer(db, customer_id, user)
    return build_customer_statement(db, c, user)


@router.get("/customers/{customer_id}/statement/pdf")
def customer_statement_pdf_route(customer_id: int, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.EXPORT_DATA))):
    c = require_customer(db, customer_id, user)
    data = build_customer_statement(db, c, user)
    pdf = customer_statement_pdf(
        data["customer_name"],
        [(l["date"], l["type"], str(l["amount"])) for l in data["lines"]],
        Decimal(str(data["balance"])),
        phone=data.get("customer_phone"),
        email=data.get("customer_email"),
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="statement-{customer_id}.pdf"'},
    )


@router.post("/customers/{customer_id}/statement/email")
def email_customer_statement(
    customer_id: int,
    body: StatementEmailRequest,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.EXPORT_DATA)),
):
    c = require_customer(db, customer_id, user)
    to = (body.to_email or c.email or "").strip()
    if not to or "@" not in to:
        raise HTTPException(400, "Valid recipient email required (customer or request body)")
    if not email_service.is_configured():
        raise HTTPException(
            503,
            "Email not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD on the server.",
        )
    data = build_customer_statement(db, c, user)
    pdf = customer_statement_pdf(
        data["customer_name"],
        [(l["date"], l["type"], str(l["amount"])) for l in data["lines"]],
        Decimal(str(data["balance"])),
        phone=data.get("customer_phone"),
        email=data.get("customer_email"),
    )
    settings = first_store_settings_for_tenant(db, user.tenant_id)
    store_name = settings.store_name if settings else "Store"
    ok = email_service.send_customer_statement(
        to_email=to,
        customer_name=data["customer_name"],
        statement_lines=data["lines"],
        balance=data["balance"],
        store_name=store_name,
        pdf_bytes=pdf,
    )
    if not ok:
        raise HTTPException(500, "Failed to send email")
    log_audit(
        db,
        user=user,
        action="email_statement",
        entity_type="customer",
        entity_id=c.id,
        new_value={"to": to},
    )
    db.commit()
    return {"ok": True, "sent_to": to}


# --- Dashboards ---


@router.get("/dashboards/summary")
def enterprise_dashboard(db: Session = Depends(get_db), user: User = Depends(auth.get_current_active_user)):
    tid = tenant_id_for_row(user)
    def _count(model):
        q = db.query(model)
        if hasattr(model, "tenant_id"):
            q = filter_by_tenant(q, model, user)
        return q.count()

    return {
        "suppliers": _count(Supplier) if has_permission(user, Perm.MANAGE_SUPPLIERS) else None,
        "open_purchase_orders": filter_by_tenant(db.query(PurchaseOrder), PurchaseOrder, user)
        .filter(PurchaseOrder.status.in_([PO_STATUS_SENT, PO_STATUS_APPROVED, PO_STATUS_PARTIALLY_RECEIVED]))
        .count()
        if has_permission(user, Perm.MANAGE_PURCHASING)
        else None,
        "pending_adjustments": filter_by_tenant(db.query(StockAdjustment), StockAdjustment, user)
        .filter(StockAdjustment.status == ADJ_STATUS_PENDING)
        .count()
        if has_permission(user, Perm.VIEW_INVENTORY)
        else None,
        "branches": _count(Branch) if has_permission(user, Perm.MANAGE_BRANCHES) else None,
        "transfers_in_transit": filter_by_tenant(db.query(StockTransfer), StockTransfer, user)
        .filter(StockTransfer.status == TRANSFER_STATUS_IN_TRANSIT)
        .count()
        if has_permission(user, Perm.MANAGE_TRANSFERS)
        else None,
    }


# --- Branch reports ---


@router.get("/reports/branch-sales")
def branch_sales_report(
    branch_id: int,
    from_date: str,
    to_date: str,
    db: Session = Depends(get_db),
    user: User = Depends(dep_perm(Perm.VIEW_REPORTS)),
):
    br = get_scoped(db, Branch, branch_id, user)
    if not br:
        raise HTTPException(404)
    # Sales branch_id column optional — filter tenant sales until branch_id on Sale is populated
    q = filter_by_tenant(db.query(Sale), Sale, user)
    q = filter_sales_by_branch(q, user)
    q = q.filter(
        Sale.created_at >= datetime.fromisoformat(from_date),
        Sale.created_at <= datetime.fromisoformat(to_date),
    )
    if branch_id is not None and not is_branch_restricted(user):
        q = q.filter(Sale.branch_id == branch_id)
    sales = q.all()
    total = sum(float(s.total) for s in sales)
    return {"branch_id": branch_id, "branch_name": br.name, "total_sales": total, "transaction_count": len(sales)}


@router.get("/reports/branch-inventory")
def branch_inventory_report(branch_id: int, db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.VIEW_REPORTS))):
    return branch_stock(branch_id, db, user)


@router.get("/offline-bundle")
def offline_bundle(db: Session = Depends(get_db), user: User = Depends(auth.get_current_active_user)):
    """Master data snapshot for offline cache (Android / PWA)."""
    tid = tenant_id_for_row(user)
    suppliers = _supplier_query(db, user).limit(2000).all()
    branches = []
    if has_permission(user, Perm.MANAGE_BRANCHES):
        branches = filter_by_tenant(db.query(Branch), Branch, user).filter(Branch.is_active == True).all()
    pos = (
        filter_by_tenant(db.query(PurchaseOrder), PurchaseOrder, user)
        .filter(PurchaseOrder.status.in_([PO_STATUS_DRAFT, PO_STATUS_SENT, PO_STATUS_APPROVED, PO_STATUS_PARTIALLY_RECEIVED]))
        .limit(500)
        .all()
    )
    return {
        "suppliers": [
            {
                "id": s.id,
                "business_name": s.business_name,
                "phone": s.phone,
                "whatsapp_number": s.whatsapp_number,
                "balance": float(s.balance),
            }
            for s in suppliers
        ],
        "branches": [{"id": b.id, "name": b.name, "code": b.code, "is_default": b.is_default} for b in branches],
        "purchase_orders": [
            {"id": p.id, "po_number": p.po_number, "supplier_id": p.supplier_id, "status": p.status, "total": float(p.total)}
            for p in pos
        ],
        "synced_at": datetime.utcnow().isoformat(),
    }


@router.get("/whatsapp/integrations")
def list_whatsapp_integrations(db: Session = Depends(get_db), user: User = Depends(dep_perm(Perm.MANAGE_SETTINGS))):
    if user.tenant_id is None:
        return []
    rows = db.query(WhatsappIntegration).filter(WhatsappIntegration.tenant_id == user.tenant_id).all()
    return [{"id": r.id, "phone_number": r.phone_number, "provider": r.provider, "status": r.status, "branch_id": r.branch_id} for r in rows]
