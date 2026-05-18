"""Billing tables: subscriptions, subscription_payments, billing_logs."""
from alembic import op
import sqlalchemy as sa

revision = "0002_billing_subscriptions"
down_revision = "0001_placeholder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan", sa.String(32), server_default="starter"),
        sa.Column("billing_cycle", sa.String(16), nullable=True),
        sa.Column("status", sa.String(32), server_default="trial"),
        sa.Column("trial_start", sa.DateTime(), nullable=True),
        sa.Column("trial_end", sa.DateTime(), nullable=True),
        sa.Column("subscription_start", sa.DateTime(), nullable=True),
        sa.Column("subscription_end", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])

    op.create_table(
        "subscription_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_reference", sa.String(64), nullable=False),
        sa.Column("paynow_reference", sa.String(64), nullable=True),
        sa.Column("poll_url", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(8), server_default="USD"),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("payment_method", sa.String(32), server_default="ecocash"),
        sa.Column("plan", sa.String(32), nullable=True),
        sa.Column("billing_cycle", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("payment_reference", name="uq_subscription_payments_reference"),
    )
    op.create_index("ix_subscription_payments_tenant_id", "subscription_payments", ["tenant_id"])

    op.create_table(
        "billing_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_billing_logs_tenant_id", "billing_logs", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("billing_logs")
    op.drop_table("subscription_payments")
    op.drop_table("subscriptions")
