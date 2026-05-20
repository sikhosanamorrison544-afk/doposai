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
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_branches_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class BranchProductStock(Base):
    """Per-branch inventory (tenant-wide product catalog, branch-specific qty)."""
    __tablename__ = "branch_product_stock"
    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", name="uq_branch_product"),
        CheckConstraint("stock_qty >= 0", name="check_branch_stock_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    stock_qty: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_qty: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


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


TRANSFER_STATUS_DRAFT = "draft"
TRANSFER_STATUS_IN_TRANSIT = "in_transit"
TRANSFER_STATUS_RECEIVED = "received"
TRANSFER_STATUS_CANCELLED = "cancelled"


class StockTransfer(Base):
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
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    items: Mapped[list["StockTransferItem"]] = relationship(
        "StockTransferItem", back_populates="transfer", cascade="all, delete-orphan"
    )


class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_transfer_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[float] = mapped_column(Float)
    quantity_received: Mapped[float] = mapped_column(Float, default=0)

    transfer: Mapped["StockTransfer"] = relationship("StockTransfer", back_populates="items")


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
