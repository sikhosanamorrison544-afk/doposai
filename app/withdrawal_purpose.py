"""
Withdrawal purpose classification.

Cash withdrawals reduce till cash for every purpose. Only ``owner_draw`` hits
Owner Drawings equity. Operating P&L costs belong on the Expense ledger —
``expense_payment`` is a cash clearing movement, not a P&L expense post.

Clearing reconciliation (1450 Cash Disbursement Clearing)
---------------------------------------------------------
A standalone ``expense_payment`` Withdrawal posts: Dr 1450 / Cr Cash 1000.
That reduces till cash but does **not** create an Expense and does **not**
affect Overview operating expenses.

To recognize the operating cost later, record an approved Expense on the
Expense ledger (paid by cash creates its own CashMovement — do **not** also
create an ``expense_payment`` Withdrawal for the same outflow).

If cash already left via ``expense_payment`` Withdrawal and you later book the
Expense as non-cash / clearing settlement, credit 1450 (not Cash) when posting
the Expense so clearing nets to zero and cash is not reduced twice.

Never pair the same physical payment as both:
  (a) Expense CashMovement, and
  (b) expense_payment Withdrawal.
"""
from __future__ import annotations

from typing import Optional

# Canonical purpose codes (API / DB)
OWNER_DRAW = "owner_draw"
BANK_DEPOSIT = "bank_deposit"
CASH_TRANSFER = "cash_transfer"
EXPENSE_PAYMENT = "expense_payment"
CASH_ADJUSTMENT = "cash_adjustment"
OTHER = "other"
UNCLASSIFIED = "unclassified"

WITHDRAWAL_PURPOSES = (
    OWNER_DRAW,
    BANK_DEPOSIT,
    CASH_TRANSFER,
    EXPENSE_PAYMENT,
    CASH_ADJUSTMENT,
    OTHER,
    UNCLASSIFIED,
)

PURPOSE_LABELS = {
    OWNER_DRAW: "Owner draw",
    BANK_DEPOSIT: "Bank deposit",
    CASH_TRANSFER: "Cash transfer",
    EXPENSE_PAYMENT: "Expense payment",
    CASH_ADJUSTMENT: "Cash adjustment",
    OTHER: "Other",
    UNCLASSIFIED: "Unclassified",
}

# Debit account for Cr Cash (1000). Never post expense_payment to P&L expense accounts.
PURPOSE_DEBIT_ACCOUNT = {
    OWNER_DRAW: "3300",  # Owner Drawings (equity)
    BANK_DEPOSIT: "1020",  # Bank
    CASH_TRANSFER: "1050",  # Cash in transit / transfers
    EXPENSE_PAYMENT: "1450",  # Cash disbursement clearing (not P&L)
    CASH_ADJUSTMENT: "1450",  # Clearing — till variance
    OTHER: "1450",
    UNCLASSIFIED: "1450",
}

# Human reason strings (forms + historical) → purpose
_REASON_TO_PURPOSE = {
    "owner draw": OWNER_DRAW,
    "owner_draw": OWNER_DRAW,
    "owner drawings": OWNER_DRAW,
    "drawings": OWNER_DRAW,
    "bank deposit": BANK_DEPOSIT,
    "bank_deposit": BANK_DEPOSIT,
    "deposit to bank": BANK_DEPOSIT,
    "cash transfer": CASH_TRANSFER,
    "cash_transfer": CASH_TRANSFER,
    "transfer": CASH_TRANSFER,
    "expense payment": EXPENSE_PAYMENT,
    "expense_payment": EXPENSE_PAYMENT,
    "daily expenses": EXPENSE_PAYMENT,
    "salary": EXPENSE_PAYMENT,
    "rent": EXPENSE_PAYMENT,
    "utilities": EXPENSE_PAYMENT,
    "cash adjustment": CASH_ADJUSTMENT,
    "cash_adjustment": CASH_ADJUSTMENT,
    "till adjustment": CASH_ADJUSTMENT,
    "buying company assets": OTHER,
    "other": OTHER,
}


def normalize_purpose(purpose: Optional[str]) -> str:
    raw = (purpose or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in WITHDRAWAL_PURPOSES:
        return raw
    return UNCLASSIFIED


def purpose_from_reason(reason: Optional[str]) -> str:
    """Infer purpose from legacy / free-text reason when purpose not supplied."""
    if not reason:
        return UNCLASSIFIED
    key = reason.strip().lower()
    if key in _REASON_TO_PURPOSE:
        return _REASON_TO_PURPOSE[key]
    # Partial matches for free-text "Other" reasons
    if "owner" in key and "draw" in key:
        return OWNER_DRAW
    if "bank" in key and "deposit" in key:
        return BANK_DEPOSIT
    if "transfer" in key:
        return CASH_TRANSFER
    if any(w in key for w in ("salary", "wage", "rent", "utilit", "expense")):
        return EXPENSE_PAYMENT
    return OTHER


def resolve_purpose(
    *,
    purpose: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """Explicit purpose wins; otherwise infer from reason; never invent owner_draw."""
    if purpose is not None and str(purpose).strip():
        p = normalize_purpose(purpose)
        if p != UNCLASSIFIED or str(purpose).strip().lower() in {
            UNCLASSIFIED,
            "unclassified",
        }:
            return p if p in WITHDRAWAL_PURPOSES else UNCLASSIFIED
        # Unknown explicit value → try reason, else unclassified
    return purpose_from_reason(reason)


def debit_account_for_purpose(purpose: str) -> str:
    return PURPOSE_DEBIT_ACCOUNT.get(normalize_purpose(purpose), "1450")


def is_fixed_asset_reason(reason: Optional[str]) -> bool:
    return (reason or "").strip().lower() == "buying company assets"


# UI reason options (web + Android) — value stored in Withdrawal.reason
UI_REASON_OPTIONS = (
    ("Owner draw", OWNER_DRAW),
    ("Bank deposit", BANK_DEPOSIT),
    ("Cash transfer", CASH_TRANSFER),
    ("Expense payment", EXPENSE_PAYMENT),
    ("Cash adjustment", CASH_ADJUSTMENT),
    ("Buying company assets", OTHER),
    ("Salary", EXPENSE_PAYMENT),
    ("Other", OTHER),
)
