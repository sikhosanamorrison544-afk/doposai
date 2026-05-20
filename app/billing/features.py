"""
Subscription plan → POS feature matrix.

Trial (14 days): effective plan is Pro — all features unlocked.
Starter: core POS only.
Business: growth features (analytics, layby, shifts, …).
Pro: everything including accounting, enterprise, AI.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Set

from sqlalchemy.orm import Session

from ..quotation_models import Tenant
from .models import Subscription


class Feature(str, Enum):
    ANALYTICS = "analytics"
    LAYBY = "layby"
    QUOTATIONS = "quotations"
    WITHDRAWALS = "withdrawals"
    SHIFTS = "shifts"
    PENDING_COLLECTION = "pending_collection"
    OUTSTANDING_DEBTS = "outstanding_debts"
    PRODUCT_IMPORT = "product_import"
    PRODUCT_EXPORT = "product_export"
    BACKUP_SYNC = "backup_sync"
    ACCOUNTING = "accounting"
    ENTERPRISE = "enterprise"
    AI_ASSISTANT = "ai_assistant"


# Human labels for billing UI / upgrade messages
FEATURE_LABELS: Dict[str, str] = {
    Feature.ANALYTICS.value: "Sales analytics & dashboards",
    Feature.LAYBY.value: "Layby (layaway) management",
    Feature.QUOTATIONS.value: "Customer quotations",
    Feature.WITHDRAWALS.value: "Cash withdrawals",
    Feature.SHIFTS.value: "Cashier shifts",
    Feature.PENDING_COLLECTION.value: "Pending collection sales",
    Feature.OUTSTANDING_DEBTS.value: "Outstanding debts",
    Feature.PRODUCT_IMPORT.value: "Bulk product import",
    Feature.PRODUCT_EXPORT.value: "Inventory export (CSV)",
    Feature.BACKUP_SYNC.value: "Google Sheets backup sync",
    Feature.ACCOUNTING.value: "Full accounting module",
    Feature.ENTERPRISE.value: "Enterprise (branches, POs, suppliers)",
    Feature.AI_ASSISTANT.value: "AI sales assistant",
}

# Minimum paid plan required for each feature
FEATURE_MIN_PLAN: Dict[str, str] = {
    f.value: "business"
    for f in (
        Feature.ANALYTICS,
        Feature.LAYBY,
        Feature.QUOTATIONS,
        Feature.WITHDRAWALS,
        Feature.SHIFTS,
        Feature.PENDING_COLLECTION,
        Feature.OUTSTANDING_DEBTS,
        Feature.PRODUCT_IMPORT,
        Feature.PRODUCT_EXPORT,
        Feature.BACKUP_SYNC,
    )
}
FEATURE_MIN_PLAN.update(
    {
        Feature.ACCOUNTING.value: "pro",
        Feature.ENTERPRISE.value: "pro",
        Feature.AI_ASSISTANT.value: "pro",
    }
)

_BUSINESS_FEATURES: FrozenSet[str] = frozenset(
    k for k, v in FEATURE_MIN_PLAN.items() if v == "business"
)
_PRO_FEATURES: FrozenSet[str] = frozenset(FEATURE_MIN_PLAN.keys())

PLAN_FEATURES: Dict[str, FrozenSet[str]] = {
    "starter": frozenset(),
    "business": _BUSINESS_FEATURES,
    "pro": _PRO_FEATURES,
}

PLAN_FEATURE_SUMMARIES: Dict[str, list[str]] = {
    "starter": [
        "Point of sale & receipts",
        "Products & inventory",
        "Customers",
        "Store settings",
        "Basic sales reports",
        "Multi-user (admin, supervisor, cashier)",
    ],
    "business": [
        "Everything in Starter",
        "Sales analytics",
        "Layby management",
        "Quotations",
        "Withdrawals & shifts",
        "Pending collection",
        "Outstanding debts",
        "CSV import / export",
        "Google Sheets backup",
    ],
    "pro": [
        "Everything in Business",
        "Full accounting (P&L, balance sheet, VAT)",
        "Enterprise (branches, suppliers, purchase orders)",
        "AI sales assistant",
    ],
}


def resolve_effective_plan(sub: Subscription) -> str:
    """During an active trial window, tenants get Pro-level features."""
    now = datetime.utcnow()
    if sub.trial_end and now <= sub.trial_end:
        return "pro"
    if sub.status == "trial":
        return "pro"
    plan = (sub.plan or "starter").lower()
    if plan not in PLAN_FEATURES:
        return "starter"
    return plan


def features_for_plan(plan: str) -> FrozenSet[str]:
    return PLAN_FEATURES.get(plan.lower(), frozenset())


def tenant_features(db: Session, tenant: Tenant, sub: Optional[Subscription] = None) -> Set[str]:
    from . import service as billing_service

    if sub is None:
        sub = billing_service.get_or_create_subscription(db, tenant)
    plan = resolve_effective_plan(sub)
    return set(features_for_plan(plan))


def tenant_has_feature(db: Session, tenant: Tenant, feature: Feature, sub: Optional[Subscription] = None) -> bool:
    return feature.value in tenant_features(db, tenant, sub)


def feature_denied_payload(feature: Feature, effective_plan: str) -> Dict[str, Any]:
    required = FEATURE_MIN_PLAN.get(feature.value, "pro")
    return {
        "detail": (
            f"{FEATURE_LABELS.get(feature.value, feature.value)} is not included in your "
            f"{effective_plan.capitalize()} plan. Upgrade to {required.capitalize()} or higher."
        ),
        "code": "plan_feature_locked",
        "feature": feature.value,
        "feature_label": FEATURE_LABELS.get(feature.value, feature.value),
        "current_plan": effective_plan,
        "required_plan": required,
        "upgrade_url": "/billing",
    }


def feature_for_api_path(path: str) -> Optional[Feature]:
    """Map API path prefix to a gated feature (None = not plan-gated)."""
    if path.startswith("/api/analytics"):
        return Feature.ANALYTICS
    if path.startswith("/api/ai/"):
        return Feature.AI_ASSISTANT
    if path.startswith("/api/accounting"):
        return Feature.ACCOUNTING
    if path.startswith("/api/layby"):
        return Feature.LAYBY
    if path.startswith("/api/quotations"):
        return Feature.QUOTATIONS
    if path.startswith("/api/withdrawals"):
        return Feature.WITHDRAWALS
    if path.startswith("/api/shifts"):
        return Feature.SHIFTS
    if path.startswith("/api/debts/"):
        return Feature.OUTSTANDING_DEBTS
    if path.startswith("/api/sales/pending-collection"):
        return Feature.PENDING_COLLECTION
    if path.startswith("/api/backup"):
        return Feature.BACKUP_SYNC
    if path.startswith("/api/products/import"):
        return Feature.PRODUCT_IMPORT
    if path.startswith("/api/products/export"):
        return Feature.PRODUCT_EXPORT
    if path.startswith("/api/enterprise"):
        return Feature.ENTERPRISE
    return None


def feature_for_page_path(path: str) -> Optional[Feature]:
    if path.startswith("/analytics"):
        return Feature.ANALYTICS
    if path.startswith("/accounting"):
        return Feature.ACCOUNTING
    if path.startswith("/enterprise"):
        return Feature.ENTERPRISE
    if path.startswith("/layby"):
        return Feature.LAYBY
    if path.startswith("/quotations"):
        return Feature.QUOTATIONS
    if path.startswith("/pending-collection"):
        return Feature.PENDING_COLLECTION
    if path.startswith("/debts/"):
        return Feature.OUTSTANDING_DEBTS
    if path.startswith("/withdrawals/"):
        return Feature.WITHDRAWALS
    return None
