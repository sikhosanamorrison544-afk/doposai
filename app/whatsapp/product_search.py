"""Tenant-scoped product search for the WhatsApp bot.

Phase 1 = pragmatic SQL ILIKE search. Phase 2 will plug a vector store
into the same surface so callers don't need to change.
"""
from __future__ import annotations

import re
from typing import List

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Product


_MAX_RESULTS = 5
_STOPWORDS = {
    "do", "you", "have", "any", "the", "a", "an", "i", "need",
    "want", "looking", "for", "please", "pls", "with", "in", "of", "on",
}


def _tokenize(query: str) -> List[str]:
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query or "")]
    cleaned = [t for t in tokens if t and t not in _STOPWORDS and len(t) >= 2]
    return cleaned[:6]


def search_products(db: Session, tenant_id: int, query: str) -> List[Product]:
    """Return up to 5 matching, in-stock products for this tenant.

    Strategy:
      1. Exact barcode hit (highest signal).
      2. ILIKE every meaningful token against name & description.
    """
    if not query or tenant_id is None:
        return []

    barcode_candidate = re.sub(r"\D+", "", query)
    if barcode_candidate and len(barcode_candidate) >= 6:
        hit = (
            db.query(Product)
            .filter(
                Product.tenant_id == tenant_id,
                Product.is_active.is_(True),
                Product.barcode == barcode_candidate,
            )
            .first()
        )
        if hit:
            return [hit]

    tokens = _tokenize(query)
    if not tokens:
        return []

    q = db.query(Product).filter(
        Product.tenant_id == tenant_id,
        Product.is_active.is_(True),
    )
    for tok in tokens:
        pat = f"%{tok}%"
        q = q.filter(or_(Product.name.ilike(pat), Product.barcode.ilike(pat)))

    return q.order_by(Product.stock_qty.desc(), Product.name).limit(_MAX_RESULTS).all()


def format_results(products: List[Product], tenant_name: str) -> str:
    if not products:
        return (
            f"I couldn't find that in {tenant_name}'s catalog.\n\n"
            "Try a different keyword, or type AGENT to talk to a human."
        )

    lines = [f"Here's what I found at {tenant_name}:", ""]
    for p in products:
        stock = float(p.stock_qty or 0) - float(p.reserved_qty or 0)
        availability = "in stock" if stock > 0 else "out of stock"
        price = f"${float(p.selling_price or 0):,.2f}"
        lines.append(f"• {p.name} — {price} ({availability})")
    lines.append("")
    lines.append(
        "Reply with a product name to get details, "
        "or type AGENT to talk to a person. MENU switches business."
    )
    return "\n".join(lines)
