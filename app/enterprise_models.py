"""
Enterprise inventory models: branches, suppliers, purchasing, adjustments, transfers, audit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# --- Branches ---


class Branch(Base):
    """Tenant-owned location (shop / till / stock room). Exactly one tenant per branch.

    ``is_default`` marks the Main Branch (at most one active main per tenant —
    enforced by migrate_branches / application layer; soft-deactivate preferred
    over hard delete when financial history exists).
    """

    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_branches_tenant_name"),
        UniqueConstraint("tenant_id", "code", name="uq_branches_tenant_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    manager_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Main Branch flag (Section 12 ``is_main`` synonym).
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def is_main(self) -> bool:
        return bool(self.is_default)

    @is_main.setter
    def is_main(self, value: bool) -> None:
        self.is_default = bool(value)


class BranchProductStock(Base):
    """Per-branch inventory — Section 14 authoritative stock source of truth.

    ``stock_qty`` / ``quantity_on_hand`` is NUMERIC(18,4).
    ``Product.stock_qty`` is a legacy shadow (sum of branch quantities).
    """

    __tablename__ = "branch_product_stock"
    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", name="uq_branch_product"),
        CheckConstraint("stock_qty >= 0", name="check_branch_stock_non_negative"),
        CheckConstraint("reserved_qty >= 0", name="check_branch_reserved_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    # Authoritative on-hand quantity (DECIMAL — GlazzerX-ready precision).
    stock_qty: Mapped[Numeric] = mapped_column(Numeric(18, 4), default=0)
    reserved_qty: Mapped[Numeric] = mapped_column(Numeric(18, 4), default=0)
    reorder_level: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 4), nullable=True)
    reorder_quantity: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 4), nullable=True)
    # Idempotent migrate marker: True once seeded from Product.stock_qty.
    seeded_from_legacy: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def quantity_on_hand(self):
        from decimal import Decimal

        return Decimal(str(self.stock_qty or 0))

    @quantity_on_hand.setter
    def quantity_on_hand(self, value) -> None:
        from decimal import Decimal

        self.stock_qty = Decimal(str(value))


# --- Suppliers ---


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    supplier_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    business_name: Mapped[str] = mapped_column(String(200), index=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    whatsapp_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    balance: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)  # positive = amount owed to supplier
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    ledger_entries: Mapped[list["SupplierLedgerEntry"]] = relationship(
        "SupplierLedgerEntry", back_populates="supplier"
    )
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        "PurchaseOrder", back_populates="supplier"
    )


class SupplierLedgerEntry(Base):
    """Supplier balance movements (purchases, payments)."""
    __tablename__ = "supplier_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    amount: Mapped[Numeric] = mapped_column(Numeric(12, 2))  # + increases balance owed
    entry_type: Mapped[str] = mapped_column(String(40))  # purchase, payment, adjustment
    reference_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="ledger_entries")


# --- Purchase orders ---


PO_STATUS_DRAFT = "draft"
PO_STATUS_SENT = "sent"
PO_STATUS_APPROVED = "approved"
PO_STATUS_PARTIALLY_RECEIVED = "partially_received"
PO_STATUS_RECEIVED = "received"
PO_STATUS_CANCELLED = "cancelled"

PO_STATUSES = (
    PO_STATUS_DRAFT,
    PO_STATUS_SENT,
    PO_STATUS_APPROVED,
    PO_STATUS_PARTIALLY_RECEIVED,
    PO_STATUS_RECEIVED,
    PO_STATUS_CANCELLED,
)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_number: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(32), default=PO_STATUS_DRAFT, index=True)
    subtotal: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    tax_total: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="purchase_orders")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        "PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(120))
    quantity_ordered: Mapped[float] = mapped_column(Float)
    quantity_received: Mapped[float] = mapped_column(Float, default=0)
    unit_cost: Mapped[Numeric] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Numeric] = mapped_column(Numeric(12, 2))

    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="items")


# --- Stock adjustments ---


ADJUSTMENT_TYPES = (
    "damage",
    "expired",
    "lost",
    "theft",
    "manual_correction",
    "stock_count_variance",
)

ADJ_STATUS_PENDING = "pending"
ADJ_STATUS_APPROVED = "approved"
ADJ_STATUS_REJECTED = "rejected"


class StockAdjustment(Base):
    __tablename__ = "stock_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    adjustment_type: Mapped[str] = mapped_column(String(40), index=True)
    quantity_change: Mapped[float] = mapped_column(Float)  # negative = reduce stock
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ADJ_STATUS_PENDING, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# --- Stock transfers ---
# Lifecycle: DRAFT → REQUESTED → APPROVED → DISPATCHED → RECEIVED
# Terminal: REJECTED | CANCELLED
# Legacy statuses draft / in_transit / received / cancelled remain readable.


TRANSFER_STATUS_DRAFT = "draft"
TRANSFER_STATUS_IN_TRANSIT = "in_transit"  # legacy ≈ dispatched
TRANSFER_STATUS_RECEIVED = "received"
TRANSFER_STATUS_CANCELLED = "cancelled"
TRANSFER_STATUS_REQUESTED = "requested"
TRANSFER_STATUS_APPROVED = "approved"
TRANSFER_STATUS_DISPATCHED = "dispatched"
TRANSFER_STATUS_REJECTED = "rejected"

TRANSFER_OPEN_STATUSES = (
    TRANSFER_STATUS_REQUESTED,
    TRANSFER_STATUS_APPROVED,
    TRANSFER_STATUS_DISPATCHED,
    TRANSFER_STATUS_IN_TRANSIT,
)


class StockTransfer(Base):
    """Inter-branch stock movement. Never creates sales revenue, COGS, Payment, or Expense."""

    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    transfer_number: Mapped[str] = mapped_column(String(50), index=True)
    from_branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    to_branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=TRANSFER_STATUS_DRAFT, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dispatch_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    dispatched_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    received_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # dispatched_at
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Offline / sync idempotency (alias: idempotency_key)
    client_transfer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    items: Mapped[list["StockTransferItem"]] = relationship(
        "StockTransferItem", back_populates="transfer", cascade="all, delete-orphan"
    )

    @property
    def source_branch_id(self) -> int:
        return int(self.from_branch_id)

    @property
    def destination_branch_id(self) -> int:
        return int(self.to_branch_id)

    @property
    def dispatched_at(self) -> Optional[datetime]:
        return self.sent_at

    @property
    def received_by_id(self) -> Optional[int]:
        return self.received_by

    @property
    def idempotency_key(self) -> Optional[str]:
        return self.client_transfer_id

    @idempotency_key.setter
    def idempotency_key(self, value: Optional[str]) -> None:
        self.client_transfer_id = value


class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_transfer_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(120))
    # quantity = requested_quantity (legacy column name)
    quantity: Mapped[Numeric] = mapped_column(Numeric(18, 4), default=0)
    approved_quantity: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 4), nullable=True)
    quantity_dispatched: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 4), nullable=True)
    quantity_received: Mapped[Numeric] = mapped_column(Numeric(18, 4), default=0)
    quantity_damaged: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 4), nullable=True)
    quantity_missing: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 4), nullable=True)
    unit_cost_snapshot: Mapped[Optional[Numeric]] = mapped_column(Numeric(12, 4), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dispatch_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    transfer: Mapped["StockTransfer"] = relationship("StockTransfer", back_populates="items")

    @property
    def requested_quantity(self):
        from decimal import Decimal

        return Decimal(str(self.quantity or 0))

    @property
    def dispatched_quantity(self):
        from decimal import Decimal

        if self.quantity_dispatched is not None:
            return Decimal(str(self.quantity_dispatched))
        return Decimal("0")

    @property
    def in_transit_quantity(self):
        from decimal import Decimal

        d = self.dispatched_quantity
        r = Decimal(str(self.quantity_received or 0))
        dmg = Decimal(str(self.quantity_damaged or 0))
        miss = Decimal(str(self.quantity_missing or 0))
        return d - r - dmg - miss

    @property
    def dispatched_value(self):
        from decimal import Decimal

        snap = Decimal(str(self.unit_cost_snapshot or 0))
        return (self.dispatched_quantity * snap).quantize(Decimal("0.0001"))

    @property
    def received_value(self):
        from decimal import Decimal

        snap = Decimal(str(self.unit_cost_snapshot or 0))
        return (Decimal(str(self.quantity_received or 0)) * snap).quantize(Decimal("0.0001"))

    @property
    def damaged_value(self):
        from decimal import Decimal

        snap = Decimal(str(self.unit_cost_snapshot or 0))
        return (Decimal(str(self.quantity_damaged or 0)) * snap).quantize(Decimal("0.0001"))


# --- Audit ---


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    device: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# --- WhatsApp integration (schema only; no Meta API) ---


class WhatsappIntegration(Base):
    __tablename__ = "whatsapp_integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(40), default="meta")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
