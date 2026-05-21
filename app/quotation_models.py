"""
Models for quotations (tenant placeholder for future multi-tenant use).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Tenant(Base):
    """Tenant (business) for multi-tenant SaaS."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_uid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    owner_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_status: Mapped[str] = mapped_column(
        String(32), default="trial", index=True
    )  # trial, active, past_due, canceled
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    last_subscription_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    firestore_doc_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    business_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    business_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    whatsapp_keyword: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, unique=True, index=True
    )
    whatsapp_welcome_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    quotations: Mapped[list["Quotation"]] = relationship(
        "Quotation", back_populates="tenant"
    )


class Quotation(Base):
    """Quotation records."""
    __tablename__ = "quotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    quotation_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    subtotal: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    discount_total: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    tax_total: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    total: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    converted_to_sale_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tenant: Mapped[Optional["Tenant"]] = relationship("Tenant", back_populates="quotations")
    items: Mapped[list["QuotationItem"]] = relationship(
        "QuotationItem", back_populates="quotation", cascade="all, delete-orphan"
    )


class QuotationItem(Base):
    """Items in a quotation."""
    __tablename__ = "quotation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("quotations.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    discount: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    line_total: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    quotation: Mapped["Quotation"] = relationship("Quotation", back_populates="items")
