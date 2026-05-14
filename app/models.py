from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20), index=True)  # "admin", "supervisor", or "cashier"
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    sales: Mapped[list["Sale"]] = relationship("Sale", back_populates="cashier")
    shifts: Mapped[list["CashierShift"]] = relationship("CashierShift", back_populates="cashier")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_categories_tenant_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )

    products: Mapped[list["Product"]] = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint('stock_qty >= 0', name='check_stock_qty_non_negative'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    stock_qty: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_qty: Mapped[float] = mapped_column(Float, default=0.0)  # Stock reserved for "to collect" sales
    cost_price: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    selling_price: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    low_stock_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Per-product threshold (null = use global default)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Expiry date for products that expire
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )

    category: Mapped[Optional[Category]] = relationship("Category", back_populates="products")
    sale_items: Mapped[list["SaleItem"]] = relationship("SaleItem", back_populates="product")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credit_balance: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )

    sales: Mapped[list["Sale"]] = relationship("Sale", back_populates="customer")


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    subtotal: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    discount_total: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    total: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    shift_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cashier_shifts.id"), nullable=True, index=True)
    collection_status: Mapped[str] = mapped_column(String(20), default="collected")  # "collected" or "to_collect"
    cashier: Mapped[User] = relationship("User", back_populates="sales")
    customer: Mapped[Optional[Customer]] = relationship("Customer", back_populates="sales")
    shift: Mapped[Optional["CashierShift"]] = relationship("CashierShift", back_populates="sales")
    items: Mapped[list["SaleItem"]] = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    discount: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)
    line_total: Mapped[Numeric] = mapped_column(Numeric(10, 2))

    sale: Mapped[Sale] = relationship("Sale", back_populates="items")
    product: Mapped[Product] = relationship("Product", back_populates="sale_items")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("sale_id", "method", name="uq_sale_method_once"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    method: Mapped[str] = mapped_column(String(30))  # cash, mobile_money, card, credit
    amount: Mapped[Numeric] = mapped_column(Numeric(10, 2))

    sale: Mapped[Sale] = relationship("Sale", back_populates="payments")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    change_qty: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    product: Mapped[Product] = relationship("Product")


class StoreSettings(Base):
    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_name: Mapped[str] = mapped_column(String(120), default="Store")
    store_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    store_location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notification_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # Email for low-stock notifications
    low_stock_email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Enable/disable email alerts
    default_low_stock_threshold: Mapped[float] = mapped_column(Float, default=10.0)  # Global default threshold
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class LaybyCustomer(Base):
    __tablename__ = "layby_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    layby_item_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    transactions: Mapped[list["LaybyTransaction"]] = relationship(
        "LaybyTransaction", back_populates="customer", cascade="all, delete-orphan"
    )


class LaybyTransaction(Base):
    __tablename__ = "layby_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("layby_customers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(120))  # Store name for historical reference
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    total_amount: Mapped[Numeric] = mapped_column(Numeric(10, 2))  # Total amount to pay
    paid_amount: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Amount paid so far
    balance: Mapped[Numeric] = mapped_column(Numeric(10, 2))  # Remaining balance
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, completed, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    customer: Mapped[LaybyCustomer] = relationship("LaybyCustomer", back_populates="transactions")
    product: Mapped[Product] = relationship("Product")
    payments: Mapped[list["LaybyPayment"]] = relationship(
        "LaybyPayment", back_populates="transaction", cascade="all, delete-orphan"
    )


class LaybyPayment(Base):
    __tablename__ = "layby_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("layby_transactions.id"), index=True)
    amount: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    payment_method: Mapped[str] = mapped_column(String(30))  # cash, mobile_money, card
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    receipt_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    transaction: Mapped[LaybyTransaction] = relationship("LaybyTransaction", back_populates="payments")
    cashier: Mapped[User] = relationship("User")


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    reason: Mapped[str] = mapped_column(String(200))  # e.g., "Daily expenses", "Buying company assets"
    receipt_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )

    cashier: Mapped[User] = relationship("User")


class Notification(Base):
    """System notifications (e.g., low stock alerts)."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String(50), index=True)  # e.g., "LOW_STOCK"
    message: Mapped[str] = mapped_column(Text)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )

    product: Mapped[Optional["Product"]] = relationship("Product")


class CashierShift(Base):
    """Cashier shift tracking and reporting."""
    __tablename__ = "cashier_shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    starting_cash: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Cash at shift start
    ending_cash: Mapped[Optional[Numeric]] = mapped_column(Numeric(10, 2), nullable=True)  # Cash at shift end
    total_sales: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Total sales amount
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)  # Number of transactions
    total_cash: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Cash payments received
    total_mobile_money: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Mobile money payments
    total_card: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Card payments
    total_credit: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Credit sales
    total_discounts: Mapped[Numeric] = mapped_column(Numeric(10, 2), default=0)  # Total discounts given
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Shift notes
    report_generated: Mapped[bool] = mapped_column(Boolean, default=False)  # Whether report was generated
    report_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tenant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=True, index=True
    )

    cashier: Mapped[User] = relationship("User", back_populates="shifts")
    sales: Mapped[list["Sale"]] = relationship("Sale", back_populates="shift")


