"""
Business Overview Dashboard data (tenant-scoped, authoritative DB aggregates).

Stock source of truth for this dashboard: ``products.stock_qty`` (same field
used by POS sale deduction). Branch stock tables are not mixed in here to
avoid dual-source inconsistency.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from . import tenant_scope
from .cash_on_hand import compute_cash_on_hand
from .currency_util import normalize_currency
from .enterprise_models import Branch
from .finance_service import (
    approved_expenses_total,
    approved_refunds_total,
    payment_method_net_totals,
    product_period_metrics,
    refund_aware_gross_profit,
)
from .models import (
    Customer,
    Payment,
    Product,
    Sale,
    SaleItem,
    User,
)


def _d(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _f(v: Any) -> float:
    return float(_d(v))


def _parse_date(s: Optional[str], default: date) -> date:
    if not s:
        return default
    return date.fromisoformat(s[:10])


def _period_bounds(from_d: date, to_d: date) -> Tuple[datetime, datetime]:
    start = datetime.combine(from_d, datetime.min.time())
    end = datetime.combine(to_d, datetime.max.time())
    return start, end


def _previous_period(from_d: date, to_d: date) -> Tuple[date, date]:
    days = (to_d - from_d).days + 1
    prev_to = from_d - timedelta(days=1)
    prev_from = prev_to - timedelta(days=days - 1)
    return prev_from, prev_to


def _sale_base_filter(user: User, start: datetime, end: datetime, branch_id: Optional[int]):
    clauses = [
        Sale.created_at >= start,
        Sale.created_at <= end,
        tenant_scope.sale_tenant_match(user),
    ]
    if branch_id is not None:
        clauses.append(Sale.branch_id == branch_id)
    elif tenant_scope.is_branch_restricted(user):
        clauses.append(Sale.branch_id == tenant_scope.user_branch_id(user))
    return and_(*clauses)


def _resolve_branch(
    db: Session, user: User, branch_id: Optional[int]
) -> Tuple[Optional[int], Optional[str], List[dict]]:
    branches_q = db.query(Branch).filter(Branch.is_active == True)  # noqa: E712
    if user.tenant_id is None:
        branches_q = branches_q.filter(Branch.tenant_id.is_(None))
    else:
        branches_q = branches_q.filter(Branch.tenant_id == user.tenant_id)
    rows = branches_q.order_by(Branch.name).all()
    options = [{"id": b.id, "name": b.name} for b in rows]

    if tenant_scope.is_branch_restricted(user):
        bid = tenant_scope.user_branch_id(user)
        name = next((b["name"] for b in options if b["id"] == bid), "Assigned branch")
        return bid, name, options

    if branch_id is not None:
        br = tenant_scope.get_scoped(db, Branch, branch_id, user)
        if br is None or not br.is_active:
            raise ValueError("Invalid branch")
        return br.id, br.name, options

    return None, "All branches" if options else None, options


def _sales_totals(db: Session, user: User, start: datetime, end: datetime, branch_id: Optional[int]) -> dict:
    filt = _sale_base_filter(user, start, end, branch_id)
    row = (
        db.query(
            func.coalesce(func.sum(Sale.total), 0),
            func.coalesce(func.sum(Sale.discount_total), 0),
            func.count(Sale.id),
        )
        .filter(filt)
        .one()
    )
    revenue, discounts, count = _d(row[0]), _d(row[1]), int(row[2] or 0)

    gross_profit = refund_aware_gross_profit(
        db, user, start, end, branch_id=branch_id, sale_filter=filt
    )

    refunds = approved_refunds_total(db, user, start, end, branch_id=branch_id)

    net_revenue = revenue - refunds
    return {
        "revenue": net_revenue,
        "gross_sales": revenue,
        "refunds": refunds,
        "discounts": discounts,
        "completed_sales": count,
        "gross_profit": gross_profit,
        "average_transaction_value": (net_revenue / count) if count else Decimal("0"),
    }


def _expenses(
    db: Session, user: User, start: datetime, end: datetime, branch_id: Optional[int]
) -> Decimal:
    return approved_expenses_total(db, user, start, end, branch_id=branch_id)


def _inventory_stats(db: Session, user: User) -> dict:
    products = (
        tenant_scope.filter_products(db, user)
        .filter(Product.is_active == True)  # noqa: E712
        .all()
    )
    settings = tenant_scope.filter_store_settings(db, user).first()
    default_threshold = float(settings.default_low_stock_threshold) if settings else 10.0

    stock_value = Decimal("0")
    low = 0
    out = 0
    healthy = 0
    for p in products:
        qty = float(p.stock_qty or 0)
        reserved = float(p.reserved_qty or 0)
        available = qty - reserved
        stock_value += _d(qty) * _d(p.cost_price)
        thr = (
            float(p.low_stock_threshold)
            if p.low_stock_threshold is not None
            else default_threshold
        )
        if available <= 0:
            out += 1
        elif available <= thr:
            low += 1
        else:
            healthy += 1
    return {
        "stock_value": stock_value,
        "low_stock_count": low,
        "out_of_stock_count": out,
        "healthy_stock_count": healthy,
        "active_products": len(products),
    }


def _outstanding_credit(db: Session, user: User) -> Decimal:
    return _d(
        tenant_scope.filter_customers(db, user)
        .with_entities(func.coalesce(func.sum(Customer.credit_balance), 0))
        .filter(Customer.credit_balance > 0)
        .scalar()
    )


def _sales_trend(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    branch_id: Optional[int],
    *,
    from_d: date,
    to_d: date,
) -> List[dict]:
    """Group by hour for a single day, otherwise by calendar day (dialect-safe)."""
    filt = _sale_base_filter(user, start, end, branch_id)
    single_day = from_d == to_d
    if single_day:
        rows = (
            db.query(Sale.created_at, Sale.total)
            .filter(filt)
            .order_by(Sale.created_at)
            .all()
        )
        buckets: Dict[str, dict] = {}
        for created_at, total in rows:
            if not created_at:
                continue
            key = created_at.strftime("%Y-%m-%d %H:00")
            slot = buckets.setdefault(key, {"revenue": Decimal("0"), "sales_count": 0})
            slot["revenue"] += _d(total)
            slot["sales_count"] += 1
        return [
            {
                "date": k,
                "revenue": _f(v["revenue"]),
                "sales_count": v["sales_count"],
                "granularity": "hour",
            }
            for k, v in sorted(buckets.items())
        ]

    day_col = func.date(Sale.created_at)
    rows = (
        db.query(
            day_col.label("day"),
            func.coalesce(func.sum(Sale.total), 0),
            func.count(Sale.id),
        )
        .filter(filt)
        .group_by(day_col)
        .order_by(day_col)
        .all()
    )
    return [
        {
            "date": str(r[0]),
            "revenue": _f(r[1]),
            "sales_count": int(r[2] or 0),
            "granularity": "day",
        }
        for r in rows
    ]


def _payment_breakdown(
    db: Session, user: User, start: datetime, end: datetime, branch_id: Optional[int]
) -> List[dict]:
    totals = payment_method_net_totals(
        db, user, start, end, branch_id=branch_id, end_exclusive=False
    )
    return [
        {"method": method, "amount": _f(amt)}
        for method, amt in sorted(totals.items(), key=lambda x: x[0])
    ]


def _top_products(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    branch_id: Optional[int],
    limit: int = 8,
) -> List[dict]:
    rows = product_period_metrics(
        db,
        user,
        start,
        end,
        branch_id=branch_id,
        end_exclusive=False,
        active_only=True,
    )
    ranked = [r for r in rows if r.gross_units > 0 or r.net_units > 0]
    ranked.sort(key=lambda r: (r.net_revenue, r.net_units), reverse=True)
    return [
        {
            "product_id": r.product_id,
            "name": r.name,
            "quantity": int(r.net_units),
            "revenue": _f(r.net_revenue),
        }
        for r in ranked[:limit]
    ]


def _pct_change(current: Decimal, previous: Decimal) -> Optional[float]:
    if previous == 0:
        if current == 0:
            return 0.0
        return None
    return float((current - previous) / abs(previous) * 100)


def _alerts(db: Session, user: User, inv: dict, credit: Decimal) -> List[dict]:
    alerts: List[dict] = []
    if inv["out_of_stock_count"]:
        alerts.append(
            {
                "type": "out_of_stock",
                "severity": "high",
                "message": f"{inv['out_of_stock_count']} product(s) out of stock",
                "href": "/admin",
            }
        )
    if inv["low_stock_count"]:
        alerts.append(
            {
                "type": "low_stock",
                "severity": "medium",
                "message": f"{inv['low_stock_count']} product(s) low on stock",
                "href": "/admin",
            }
        )
    if credit > 0:
        alerts.append(
            {
                "type": "outstanding_credit",
                "severity": "medium",
                "message": f"Outstanding customer credit: ${_f(credit):,.2f}",
                "href": "/debts/outstanding",
            }
        )
    pending = (
        tenant_scope.filter_sales(db, user)
        .filter(Sale.collection_status == "to_collect")
        .count()
    )
    if pending:
        alerts.append(
            {
                "type": "pending_collection",
                "severity": "medium",
                "message": f"{pending} sale(s) awaiting collection",
                "href": "/pending-collection",
            }
        )
    return alerts


def _recent_activity(
    db: Session, user: User, branch_id: Optional[int], limit: int = 8
) -> List[dict]:
    q = tenant_scope.filter_sales(db, user).order_by(Sale.created_at.desc())
    if branch_id is not None:
        q = q.filter(Sale.branch_id == branch_id)
    sales = q.limit(limit).all()
    out = []
    for s in sales:
        cashier = tenant_scope.get_scoped(db, User, s.cashier_id, user)
        out.append(
            {
                "type": "sale",
                "at": s.created_at.isoformat() if s.created_at else None,
                "reference": f"Sale #{s.id}",
                "user": (cashier.full_name or cashier.username) if cashier else "—",
                "amount": _f(s.total),
                "status": s.collection_status or "collected",
            }
        )
    return out


def build_business_overview(
    db: Session,
    user: User,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    branch_id: Optional[int] = None,
) -> Dict[str, Any]:
    today = datetime.utcnow().date()
    to_d = _parse_date(to_date, today)
    from_d = _parse_date(from_date, today)
    if from_d > to_d:
        raise ValueError("from_date must be on or before to_date")
    if (to_d - from_d).days > 366:
        raise ValueError("Date range cannot exceed 366 days")

    effective_branch, branch_label, branch_options = _resolve_branch(db, user, branch_id)
    start, end = _period_bounds(from_d, to_d)
    prev_from, prev_to = _previous_period(from_d, to_d)
    prev_start, prev_end = _period_bounds(prev_from, prev_to)

    store = tenant_scope.filter_store_settings(db, user).first()
    business_name = store.store_name if store else "Business"
    currency = normalize_currency(getattr(store, "currency", None) if store else None)

    cur = _sales_totals(db, user, start, end, effective_branch)
    prev = _sales_totals(db, user, prev_start, prev_end, effective_branch)
    expenses = _expenses(db, user, start, end, effective_branch)
    prev_expenses = _expenses(db, user, prev_start, prev_end, effective_branch)
    net = cur["gross_profit"] - expenses
    prev_net = prev["gross_profit"] - prev_expenses
    inv = _inventory_stats(db, user)
    credit = _outstanding_credit(db, user)
    till = compute_cash_on_hand(
        db, user, start, end, branch_id=effective_branch
    )
    prev_till = compute_cash_on_hand(
        db, user, prev_start, prev_end, branch_id=effective_branch
    )

    def card(
        key: str,
        label: str,
        value: Optional[Decimal],
        prev_value: Optional[Decimal],
        href: Optional[str],
        money: bool = True,
        compare: bool = True,
        subtitle: Optional[str] = None,
        *,
        available: bool = True,
        unavailable_label: Optional[str] = None,
    ):
        if not available:
            return {
                "key": key,
                "label": label,
                "value": None,
                "previous_value": None,
                "change_pct": None,
                "direction": "neutral",
                "money": money,
                "href": href,
                "subtitle": subtitle,
                "available": False,
                "display": unavailable_label or "Unavailable",
            }
        assert value is not None and prev_value is not None
        change = _pct_change(value, prev_value) if compare else None
        direction = "neutral"
        if compare:
            if change is None and value > 0:
                direction = "up"
            elif change is not None:
                if change > 0.05:
                    direction = "up"
                elif change < -0.05:
                    direction = "down"
        return {
            "key": key,
            "label": label,
            "value": _f(value),
            "previous_value": _f(prev_value) if compare else None,
            "change_pct": change,
            "direction": direction,
            "money": money,
            "href": href,
            "subtitle": subtitle,
            "available": True,
        }

    cash_available = bool(till.get("available", True))
    cash_card = card(
        "cash_on_hand",
        "Cash on hand",
        till["cash_on_hand"] if cash_available else None,
        prev_till["cash_on_hand"] if cash_available and prev_till.get("available", True) else Decimal("0"),
        "/withdrawals/history" if cash_available else None,
        subtitle=till["subtitle"],
        compare=cash_available,
        available=cash_available,
        unavailable_label="Unavailable",
    )

    summary_cards = [
        card("revenue", "Sales revenue", cur["revenue"], prev["revenue"], "/admin"),
        cash_card,
        card(
            "completed_sales",
            "Completed sales",
            Decimal(cur["completed_sales"]),
            Decimal(prev["completed_sales"]),
            None,
            money=False,
        ),
        card(
            "gross_profit",
            "Gross profit",
            cur["gross_profit"],
            prev["gross_profit"],
            "/accounting",
        ),
        card(
            "expenses",
            "Operating expenses",
            expenses,
            prev_expenses,
            "/expenses",
        ),
        card("net_result", "Net profit", net, prev_net, "/accounting"),
        card(
            "atv",
            "Average transaction",
            cur["average_transaction_value"],
            prev["average_transaction_value"],
            None,
        ),
        card(
            "low_stock",
            "Low stock products",
            Decimal(inv["low_stock_count"]),
            Decimal(0),
            "/admin",
            money=False,
            compare=False,
        ),
        card(
            "out_of_stock",
            "Out of stock",
            Decimal(inv["out_of_stock_count"]),
            Decimal(0),
            "/admin",
            money=False,
            compare=False,
        ),
        card(
            "stock_value",
            "Stock value (cost)",
            inv["stock_value"],
            Decimal(0),
            "/admin",
            compare=False,
        ),
        card(
            "outstanding_credit",
            "Outstanding credit",
            credit,
            Decimal(0),
            "/debts/outstanding",
            compare=False,
        ),
    ]

    return {
        "business": {
            "name": business_name,
            "branch_name": branch_label,
            "currency": currency,
        },
        "period": {
            "from": from_d.isoformat(),
            "to": to_d.isoformat(),
            "previous_from": prev_from.isoformat(),
            "previous_to": prev_to.isoformat(),
        },
        "branches": {
            "selected_id": effective_branch,
            "options": branch_options,
            "can_select": len(branch_options) > 0
            and not tenant_scope.is_branch_restricted(user),
        },
        "summary": {
            "revenue": _f(cur["revenue"]),
            "cash_on_hand": _f(till["cash_on_hand"]) if till.get("available", True) else None,
            "cash_payments": _f(till["cash_payments"]),
            "cash_refunds": _f(till["cash_refunds"]),
            "withdrawals_total": _f(till["withdrawals_total"]),
            "cash_expense_outflows": _f(till.get("cash_expense_outflows") or 0),
            "completed_sales": cur["completed_sales"],
            "gross_profit": _f(cur["gross_profit"]),
            "expenses": _f(expenses),
            "net_result": _f(net),
            "net_profit": _f(net),
            "average_transaction_value": _f(cur["average_transaction_value"]),
            "low_stock_count": inv["low_stock_count"],
            "out_of_stock_count": inv["out_of_stock_count"],
            "stock_value": _f(inv["stock_value"]),
            "outstanding_credit": _f(credit),
            "refunds": _f(cur["refunds"]),
        },
        "cash_on_hand_meta": {
            "as_of_start": till["as_of_start"],
            "as_of_end": till["as_of_end"],
            "scope": till["scope"],
            "subtitle": till["subtitle"],
            "note": till["note"],
            "withdrawals_included": till["withdrawals_included"],
            "available": bool(till.get("available", True)),
            "reason": till.get("reason"),
            "meaning": till.get("meaning", "period"),
        },
        "cards": summary_cards,
        "sales_trend": _sales_trend(
            db, user, start, end, effective_branch, from_d=from_d, to_d=to_d
        ),
        "payment_methods": _payment_breakdown(db, user, start, end, effective_branch),
        "top_products": _top_products(db, user, start, end, effective_branch),
        "inventory_status": [
            {"label": "Healthy", "count": inv["healthy_stock_count"]},
            {"label": "Low stock", "count": inv["low_stock_count"]},
            {"label": "Out of stock", "count": inv["out_of_stock_count"]},
        ],
        "alerts": _alerts(db, user, inv, credit),
        "recent_activity": _recent_activity(db, user, effective_branch),
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "stock_source": "products.stock_qty",
        },
    }
