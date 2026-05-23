"""
Tenant-scoped business analytics summaries.

Never returns raw row-level DB dumps — only aggregated metrics for AI / dashboards.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ... import tenant_scope
from ...enterprise_models import Branch
from ...models import Customer, Product, Sale, User
from . import debt as debt_analytics
from . import inventory as inventory_analytics
from . import profit as profit_analytics
from . import sales as sales_analytics


def _tenant_meta(db: Session, user: User) -> Dict[str, Any]:
    tid = tenant_scope.tenant_id_for_row(user)
    name = None
    if tid is not None:
        from ...quotation_models import Tenant

        t = db.query(Tenant).filter(Tenant.id == tid).first()
        name = t.name if t else None
    return {
        "tenant_id": tid,
        "tenant_uid": getattr(user, "tenant_uid", None),
        "business_name": name,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def build_tenant_analytics_summary(
    db: Session,
    user: User,
    *,
    days: int = 30,
) -> Dict[str, Any]:
    """Full analytics payload for BI endpoints and AI service."""
    now = datetime.utcnow()
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)
    meta = _tenant_meta(db, user)

    sales_block = sales_analytics.sales_metrics(
        db, user, period_start, now, prev_start, period_start
    )
    inv_block = inventory_analytics.inventory_metrics(db, user)
    profit_block = profit_analytics.profit_metrics(
        db, user, period_start, now, prev_start, period_start
    )
    debt_block = debt_analytics.debt_metrics(db, user)
    branch_block = _branch_performance(db, user, period_start, now)
    customer_block = _customer_activity(db, user, period_start, now)

    summary = {
        **meta,
        "period_days": days,
        "period_start": period_start.isoformat() + "Z",
        "period_end": now.isoformat() + "Z",
        **sales_block,
        **inv_block,
        **profit_block,
        **debt_block,
        "branch_performance": branch_block,
        "customer_activity": customer_block,
    }
    return summary


def build_health_analytics_summary(
    db: Session,
    user: User,
    *,
    days: int = 30,
) -> Dict[str, Any]:
    """Lightweight aggregates for health score cards (under ~30s on Render)."""
    now = datetime.utcnow()
    period_start = now - timedelta(days=days)
    prev_start = period_start - timedelta(days=days)
    meta = _tenant_meta(db, user)

    return {
        **meta,
        "period_days": days,
        **sales_analytics.sales_metrics_for_health(
            db, user, period_start, now, prev_start, period_start
        ),
        **inventory_analytics.inventory_metrics_for_health(db, user),
        **profit_analytics.profit_metrics(
            db, user, period_start, now, prev_start, period_start
        ),
        **debt_analytics.debt_metrics(db, user),
    }


def _branch_performance(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    branches = tenant_scope.filter_by_tenant(
        db.query(Branch), Branch, user
    ).filter(Branch.is_active == True).all()  # noqa: E712
    if not branches:
        rows = (
            db.query(
                func.coalesce(func.sum(Sale.total), 0).label("revenue"),
                func.count(Sale.id).label("transactions"),
            )
            .filter(
                Sale.created_at >= start,
                Sale.created_at < end,
                tenant_scope.sale_tenant_match(user),
            )
            .first()
        )
        return [
            {
                "branch_id": None,
                "branch_name": "Main store",
                "revenue": float(rows.revenue or 0),
                "transactions": int(rows.transactions or 0),
            }
        ]

    out: List[Dict[str, Any]] = []
    for b in branches:
        q = db.query(
            func.coalesce(func.sum(Sale.total), 0).label("revenue"),
            func.count(Sale.id).label("transactions"),
        ).filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            Sale.branch_id == b.id,
            tenant_scope.sale_tenant_match(user),
        )
        row = q.first()
        out.append(
            {
                "branch_id": b.id,
                "branch_name": b.name,
                "code": b.code,
                "revenue": float(row.revenue or 0),
                "transactions": int(row.transactions or 0),
            }
        )
    out.sort(key=lambda x: x["revenue"], reverse=True)
    return out


def _customer_activity(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
) -> Dict[str, Any]:
    active_customers = (
        db.query(func.count(func.distinct(Sale.customer_id)))
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            Sale.customer_id.isnot(None),
            tenant_scope.sale_tenant_match(user),
        )
        .scalar()
        or 0
    )
    top_q = (
        db.query(
            Customer.id,
            Customer.name,
            func.sum(Sale.total).label("spent"),
            func.count(Sale.id).label("visits"),
        )
        .join(Sale, Sale.customer_id == Customer.id)
        .filter(
            Sale.created_at >= start,
            Sale.created_at < end,
            tenant_scope.sale_tenant_match(user),
        )
    )
    if user.tenant_id is None:
        top_q = top_q.filter(Customer.tenant_id.is_(None))
    else:
        top_q = top_q.filter(Customer.tenant_id == user.tenant_id)
    top_rows = (
        top_q.group_by(Customer.id, Customer.name)
        .order_by(func.sum(Sale.total).desc())
        .limit(5)
        .all()
    )

    return {
        "active_customers_period": int(active_customers),
        "top_customers_by_spend": [
            {
                "customer_id": r.id,
                "name": r.name,
                "total_spent": float(r.spent or 0),
                "visits": int(r.visits or 0),
            }
            for r in top_rows
        ],
    }
