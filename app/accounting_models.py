"""
Accounting Models for Double-Entry Bookkeeping
Zimbabwe POS System - Accountant-Grade Accounting Layer
"""

from datetime import datetime
from typing import Optional
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .database import Base

# Forward reference for User - will be resolved at runtime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .models import User


class ChartOfAccount(Base):
    """Chart of Accounts - Zimbabwe-specific account structure."""
    __tablename__ = "chart_of_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # e.g., "1000", "4000"
    name: Mapped[str] = mapped_column(String(200), index=True)
    account_type: Mapped[str] = mapped_column(String(20), index=True)  # ASSET, LIABILITY, EQUITY, INCOME, EXPENSE
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chart_of_accounts.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    parent: Mapped[Optional["ChartOfAccount"]] = relationship(
        "ChartOfAccount", remote_side=[id], backref="children"
    )
    journal_entry_lines: Mapped[list["JournalEntryLine"]] = relationship(
        "JournalEntryLine", back_populates="account"
    )

    def __repr__(self):
        return f"<ChartOfAccount(code={self.code}, name={self.name}, type={self.account_type})>"


class AccountingPeriod(Base):
    """Accounting periods for period locking and reporting."""
    __tablename__ = "accounting_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    period_name: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # e.g., "2024-01"
    start_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)  # type: ignore
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    journal_entries: Mapped[list["JournalEntry"]] = relationship(
        "JournalEntry", back_populates="period"
    )


class JournalEntry(Base):
    """Journal Entry Header - represents a complete accounting transaction."""
    __tablename__ = "journal_entries"
    # Note: Balance check (debits = credits) is enforced at application level
    # SQLite doesn't support subqueries in CHECK constraints

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    entry_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # e.g., "JE-2024-0001"
    entry_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    description: Mapped[str] = mapped_column(String(500))
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), index=True)  # "SALE", "WITHDRAWAL", "ASSET", etc.
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)  # ID of the source transaction
    period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounting_periods.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_posted: Mapped[bool] = mapped_column(Boolean, default=True, index=True)  # All entries are posted immediately
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Stored totals for balance verification (enforced at application level, stored for performance)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_credit: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    
    __table_args__ = (
        CheckConstraint(
            "total_debit = total_credit",
            name="check_balanced_entry"
        ),
    )

    # Relationships
    period: Mapped[Optional["AccountingPeriod"]] = relationship("AccountingPeriod", back_populates="journal_entries")
    lines: Mapped[list["JournalEntryLine"]] = relationship(
        "JournalEntryLine", back_populates="journal_entry", cascade="all, delete-orphan"
    )
    creator: Mapped["User"] = relationship("User")

    def __repr__(self):
        return f"<JournalEntry(entry_number={self.entry_number}, date={self.entry_date}, description={self.description})>"


class JournalEntryLine(Base):
    """Journal Entry Line - individual debit/credit line."""
    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        CheckConstraint(
            "(debit_amount = 0 AND credit_amount > 0) OR (debit_amount > 0 AND credit_amount = 0)",
            name="check_debit_xor_credit"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    journal_entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("chart_of_accounts.id"), index=True)
    debit_amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    credit_amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    line_number: Mapped[int] = mapped_column(Integer, default=1)  # Order within entry

    # Relationships
    journal_entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="lines")
    account: Mapped["ChartOfAccount"] = relationship("ChartOfAccount", back_populates="journal_entry_lines")

    def __repr__(self):
        return f"<JournalEntryLine(account_id={self.account_id}, debit={self.debit_amount}, credit={self.credit_amount})>"


class ExpenseAccountMapping(Base):
    """Maps withdrawal reasons to expense accounts."""
    __tablename__ = "expense_account_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    reason: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # e.g., "Daily expenses", "Salary"
    account_id: Mapped[int] = mapped_column(ForeignKey("chart_of_accounts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    account: Mapped["ChartOfAccount"] = relationship("ChartOfAccount")


class FixedAsset(Base):
    """Fixed Assets Register."""
    __tablename__ = "fixed_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    asset_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # e.g., "FA-001"
    name: Mapped[str] = mapped_column(String(200), index=True)
    purchase_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    purchase_cost: Mapped[Numeric] = mapped_column(Numeric(12, 2))
    depreciation_method: Mapped[str] = mapped_column(String(20), default="straight_line")  # straight_line, declining_balance
    useful_life_months: Mapped[int] = mapped_column(Integer)  # e.g., 60 months = 5 years
    accumulated_depreciation: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    current_value: Mapped[Numeric] = mapped_column(Numeric(12, 2))  # purchase_cost - accumulated_depreciation
    is_disposed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    disposed_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    disposal_proceeds: Mapped[Optional[Numeric]] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # type: ignore

    # Relationships
    creator: Mapped["User"] = relationship("User")  # type: ignore
    depreciation_schedule: Mapped[list["AssetDepreciationSchedule"]] = relationship(
        "AssetDepreciationSchedule", back_populates="asset"
    )


class AssetDepreciationSchedule(Base):
    """Monthly depreciation schedule for fixed assets."""
    __tablename__ = "asset_depreciation_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("fixed_assets.id"), index=True)
    period: Mapped[str] = mapped_column(String(50), index=True)  # e.g., "2024-01"
    depreciation_amount: Mapped[Numeric] = mapped_column(Numeric(12, 2))
    journal_entry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("journal_entries.id"), nullable=True, index=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    asset: Mapped["FixedAsset"] = relationship("FixedAsset", back_populates="depreciation_schedule")
    journal_entry: Mapped[Optional["JournalEntry"]] = relationship("JournalEntry")

