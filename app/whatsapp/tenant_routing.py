"""Tenant selection logic for the shared WhatsApp number.

Encapsulates the queries the state machine uses to:
  * list active, WhatsApp-enabled tenants (for the welcome menu),
  * resolve a numeric pick or keyword to a Tenant row,
  * build the interactive list payload for the menu.

Every helper takes an already-opened ``Session`` so the caller controls
transaction scope.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..quotation_models import Tenant
from . import config
from .meta_client import ListRow, ListSection

_KEYWORD_RX = re.compile(r"[A-Z0-9]{2,32}")


def normalize_keyword(raw: str) -> str:
    """Uppercase, strip non-[A-Z0-9], cap at 32 chars."""
    if not raw:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", raw).upper()
    return cleaned[:32]


def active_tenants(db: Session, limit: Optional[int] = None) -> List[Tenant]:
    """All tenants that opted in to the WhatsApp bot, ordered by name."""
    q = (
        db.query(Tenant)
        .filter(
            Tenant.is_active.is_(True),
            Tenant.whatsapp_enabled.is_(True),
            Tenant.subscription_status != "canceled",
        )
        .order_by(func.lower(Tenant.name))
    )
    cap = limit if limit is not None else config.WHATSAPP_MAX_MENU_TENANTS
    if cap and cap > 0:
        q = q.limit(cap)
    return q.all()


def find_tenant_by_keyword(db: Session, raw_text: str) -> Optional[Tenant]:
    """Match the text against tenant whatsapp_keyword (case-insensitive).

    Accepts the keyword as a standalone word inside a longer message:
        "GLASS"            -> match
        "glass please"     -> match (GLASS is a whole word)
        "fiberglass info"  -> no match (substring only)
    """
    if not raw_text:
        return None
    tokens = {tok.upper() for tok in re.findall(r"[A-Za-z0-9]+", raw_text)}
    if not tokens:
        return None
    return (
        db.query(Tenant)
        .filter(
            Tenant.is_active.is_(True),
            Tenant.whatsapp_enabled.is_(True),
            Tenant.whatsapp_keyword.isnot(None),
            func.upper(Tenant.whatsapp_keyword).in_(tokens),
        )
        .first()
    )


def find_tenant_by_index(db: Session, idx: int) -> Optional[Tenant]:
    """1-based pick from the same ordered list shown to the user."""
    if idx < 1:
        return None
    tenants = active_tenants(db)
    if idx > len(tenants):
        return None
    return tenants[idx - 1]


def find_tenant_by_id(db: Session, tenant_id: int) -> Optional[Tenant]:
    return (
        db.query(Tenant)
        .filter(
            Tenant.id == tenant_id,
            Tenant.is_active.is_(True),
            Tenant.whatsapp_enabled.is_(True),
        )
        .first()
    )


# ── menu rendering ──────────────────────────────────────────────────────


def build_text_menu(brand: str, tenants: List[Tenant]) -> str:
    """Plain-text fallback menu (for clients that don't render lists)."""
    if not tenants:
        return (
            f"Welcome to {brand}.\n\n"
            "No businesses are available right now. Please try again later."
        )
    lines = [f"Welcome to {brand}.", "", "Choose a business by number or keyword:"]
    for i, t in enumerate(tenants, start=1):
        keyword = t.whatsapp_keyword or "—"
        lines.append(f"{i}. {t.name}  ·  keyword: {keyword}")
    lines.append("")
    lines.append("Type the number or the keyword to continue.")
    return "\n".join(lines)


def build_list_sections(tenants: List[Tenant]) -> Tuple[List[ListSection], str]:
    """Build a WhatsApp list payload + a body fallback string.

    Returns (sections, body_text). The list message can carry up to 10 rows
    across all sections — we cap to that to stay within Meta limits.
    """
    rows: List[ListRow] = []
    for t in tenants[:10]:
        rows.append(
            ListRow(
                id=f"tenant:{t.id}",
                title=t.name[:24],
                description=(
                    (t.business_type or t.business_description or "")[:72] or None
                ),
            )
        )
    sections = [ListSection(title="Businesses", rows=rows)]
    body = "Choose a business below — or type its keyword (e.g. GLASS)."
    return sections, body
