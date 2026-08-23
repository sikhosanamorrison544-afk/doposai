"""
Multi-branch foundation models (Section 12).

Extends / complements enterprise Branch + BranchProductStock.
UserBranch enables multi-branch staff assignment (User.branch_id remains
compat default / legacy single assignment).

StockTransfer lifecycle columns are additive on the existing enterprise table
via migrate_branches.py — see docs/BRANCH_ARCHITECTURE.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


# Membership roles within a branch (orthogonal to tenant-wide User.role).
BRANCH_MEMBER_ROLES = (
    "owner",  # implicit via tenant admin — may still have membership rows
    "manager",
    "cashier",
    "stock_controller",
    "accountant",
    "viewer",
)


class UserBranch(Base):
    """Staff assignment: a user may access one or more branches in a tenant."""

    __tablename__ = "user_branches"
    __table_args__ = (
        UniqueConstraint("user_id", "branch_id", name="uq_user_branches_user_branch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    # Branch-local role profile (manager/cashier/…). Tenant-wide User.role still applies.
    role: Mapped[str] = mapped_column(String(40), default="cashier")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    assigned_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# Transfer lifecycle (target). Existing rows may still use draft/in_transit/received.
TRANSFER_STATUS_DRAFT = "draft"
TRANSFER_STATUS_REQUESTED = "requested"
TRANSFER_STATUS_APPROVED = "approved"
TRANSFER_STATUS_DISPATCHED = "dispatched"
TRANSFER_STATUS_RECEIVED = "received"
TRANSFER_STATUS_REJECTED = "rejected"
TRANSFER_STATUS_CANCELLED = "cancelled"

TRANSFER_STATUSES_V2 = (
    TRANSFER_STATUS_DRAFT,
    TRANSFER_STATUS_REQUESTED,
    TRANSFER_STATUS_APPROVED,
    TRANSFER_STATUS_DISPATCHED,
    TRANSFER_STATUS_RECEIVED,
    TRANSFER_STATUS_REJECTED,
    TRANSFER_STATUS_CANCELLED,
)

# Map legacy enterprise statuses → v2 semantics for reads.
LEGACY_TRANSFER_STATUS_MAP = {
    "draft": TRANSFER_STATUS_DRAFT,
    "in_transit": TRANSFER_STATUS_DISPATCHED,
    "received": TRANSFER_STATUS_RECEIVED,
    "cancelled": TRANSFER_STATUS_CANCELLED,
}
