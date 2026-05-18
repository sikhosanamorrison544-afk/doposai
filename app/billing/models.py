"""PostgreSQL billing tables (multi-tenant subscriptions & Paynow payments)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(32), default="starter")  # starter | business | pro
    billing_cycle: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # monthly | yearly
    status: Mapped[str] = mapped_column(
        String(32), default="trial", index=True
    )  # trial | active | expired | suspended | pending_payment
    trial_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trial_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    subscription_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    payment_reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    paynow_reference: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    poll_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending | paid | failed | cancelled
    payment_method: Mapped[str] = mapped_column(String(32), default="ecocash")
    plan: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    billing_cycle: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BillingLog(Base):
    __tablename__ = "billing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
