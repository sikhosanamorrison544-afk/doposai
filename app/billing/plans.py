"""Subscription plan catalog (Starter / Business / Pro)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from .features import PLAN_FEATURE_SUMMARIES, PLAN_FEATURES

PlanId = Literal["starter", "business", "pro"]
CycleId = Literal["monthly", "yearly"]

VALID_PLANS = ("starter", "business", "pro")
VALID_CYCLES = ("monthly", "yearly")
VALID_STATUSES = ("trial", "active", "expired", "suspended", "pending_payment")


@dataclass(frozen=True)
class PlanPrice:
    plan: str
    cycle: str
    amount_usd: float
    label: str


_DEFAULT_CATALOG: List[PlanPrice] = [
    PlanPrice("starter", "monthly", 19.99, "Starter — Monthly"),
    PlanPrice("starter", "yearly", 199.00, "Starter — Yearly"),
    PlanPrice("business", "monthly", 49.99, "Business — Monthly"),
    PlanPrice("business", "yearly", 499.00, "Business — Yearly"),
    PlanPrice("pro", "monthly", 99.99, "Pro — Monthly"),
    PlanPrice("pro", "yearly", 999.00, "Pro — Yearly"),
]


def _load_catalog() -> List[PlanPrice]:
    raw = os.environ.get("BILLING_PLANS_JSON", "").strip()
    if not raw:
        return list(_DEFAULT_CATALOG)
    try:
        data = json.loads(raw)
        out: List[PlanPrice] = []
        for row in data:
            out.append(
                PlanPrice(
                    str(row["plan"]).lower(),
                    str(row["cycle"]).lower(),
                    float(row["amount_usd"]),
                    str(row.get("label") or f"{row['plan']} — {row['cycle']}"),
                )
            )
        return out or list(_DEFAULT_CATALOG)
    except Exception:
        return list(_DEFAULT_CATALOG)


_CATALOG = _load_catalog()


def list_plans_public() -> List[Dict[str, Any]]:
    """API-safe plan list for web/Android pricing screens."""
    grouped: Dict[str, Dict[str, Any]] = {}
    for p in _CATALOG:
        g = grouped.setdefault(
            p.plan,
            {
                "id": p.plan,
                "name": p.plan.capitalize(),
                "monthly": None,
                "yearly": None,
                "features": sorted(PLAN_FEATURES.get(p.plan, frozenset())),
                "highlights": PLAN_FEATURE_SUMMARIES.get(p.plan, []),
            },
        )
        g[p.cycle] = {"amount_usd": p.amount_usd, "label": p.label, "currency": "USD"}
    return list(grouped.values())


def get_price(plan: str, cycle: str) -> PlanPrice:
    plan = plan.lower().strip()
    cycle = cycle.lower().strip()
    if plan not in VALID_PLANS:
        raise ValueError(f"Invalid plan: {plan}")
    if cycle not in VALID_CYCLES:
        raise ValueError(f"Invalid billing cycle: {cycle}")
    for p in _CATALOG:
        if p.plan == plan and p.cycle == cycle:
            return p
    raise ValueError(f"No price configured for {plan}/{cycle}")
