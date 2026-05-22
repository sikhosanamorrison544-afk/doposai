"""Intent detection for natural-language BI questions."""
from __future__ import annotations

import re
from typing import Tuple


INTENTS = (
    "sales",
    "inventory",
    "profit",
    "forecast",
    "debt",
    "general",
)


_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\b(restock|reorder|stock\s*out|low\s*stock|inventory|dead\s*stock|slow\s*moving)\b", "inventory"),
    (r"\b(profit|margin|cost|profitable|loss)\b", "profit"),
    (r"\b(forecast|predict|next\s*week|next\s*month|projection)\b", "forecast"),
    (r"\b(owe|debt|credit|layby|outstanding|debtor)\b", "debt"),
    (r"\b(sales|revenue|selling|promot|trend|down|up|category)\b", "sales"),
)


def detect_intent(question: str) -> str:
    q = (question or "").lower().strip()
    if not q:
        return "general"
    for pattern, intent in _PATTERNS:
        if re.search(pattern, q, re.I):
            return intent
    return "general"
