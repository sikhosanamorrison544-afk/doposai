"""Bounded list endpoints — avoid gateway 502 on huge product/customer payloads."""
from __future__ import annotations

from typing import Any, List, Tuple, TypeVar

from sqlalchemy.orm import Query, Session

from app.analytics_page_data import pg_statement_timeout

DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 2000
LIST_STATEMENT_TIMEOUT_MS = 15000

T = TypeVar("T")


def clamp_list_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIST_LIMIT))


def paginate_orm_query(
    db: Session,
    query: Query,
    *,
    limit: int,
    offset: int,
    timeout_ms: int = LIST_STATEMENT_TIMEOUT_MS,
    include_total: bool | None = None,
) -> Tuple[List[Any], int]:
    """Return (rows, total_count) with Postgres statement timeout.

    Total count runs only on the first page (offset=0) unless include_total is set.
    Skipping count on later pages avoids N slow COUNT(*) queries when clients page
    through large product lists.
    """
    pg_statement_timeout(db, timeout_ms)
    limit = clamp_list_limit(limit)
    offset = max(0, int(offset))
    if include_total is None:
        include_total = offset == 0
    if include_total:
        total = int(query.count())
    else:
        total = -1
    rows = query.offset(offset).limit(limit).all()
    return rows, int(total)
