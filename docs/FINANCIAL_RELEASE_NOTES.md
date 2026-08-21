# Financial accuracy release — closed notes

**Workstream status: FINANCIAL RELEASE CLOSED**  
**Production acceptance:** PASSED on build `34fa2036dc4e`

This document closes the financial accuracy / refund integrity release. It records identifiers, accounting rules, production evidence, limitations, and handoff notes for multi-branch and GlazzerX. No application behaviour is defined here beyond what already shipped.

---

## Release identifiers

| Role | Full commit / artifact |
|------|------------------------|
| Password-reset fix (pre-release HEAD) | `170d278a1f3b4cd36dd619501fe4c43849819b38` |
| Migration tooling | `6a9358d17558f5c87ff85fb862690336d2a471a9` — `chore(db): harden financial schema migration` |
| Financial application release | `34fa2036dc4e621c140ec96261e26e7df3265b84` — `fix(finance): reconcile refunds and enforce financial integrity` |
| Production build (meta `pos-build`) | `34fa2036dc4e` |
| Production DB backup | `2026-08-21T03_35Z.dir.tar.gz` (dbname `doposai_postgres`, dashboard **Completed**, ~169 KiB; directory-format archive listable without extract) |

Do not store credentials, connection strings, or account secrets in this document.

---

## Production schema migration result

Order executed against production:

1. Verified backup (`2026-08-21T03_35Z.dir.tar.gz`).
2. Schema inspection (`migrate_financial_accuracy.py --dry-run`) — gaps before migrate: `sale_items.unit_cost`, `store_settings.currency`, `withdrawals.purpose`, `expenses`, `cash_movements`. Refund tables and JE `reference_type` / `reference_id` already present.
3. `python3 migrate_financial_accuracy.py --verify` — exit **0**.
4. `migrate_refunds.py` — **not required** (refund tables already present).
5. Idempotent re-verify — exit **0**.

Post-migration checklist (all present):

| Item | Result |
|------|--------|
| `sale_items.unit_cost` | Added; historical rows backfilled from `products.cost_price` |
| `store_settings.currency` | Added (default `USD`) |
| `withdrawals.purpose` | Added; backfilled from legacy reasons |
| `expenses` / `cash_movements` | Created |
| `refunds` / `refund_items` + audit fields | Already present |
| JE `reference_type` / `reference_id` | Already present |
| CoA `1050` / `1450` / `3300` | Inserted with `created_at` when CoA existed |

Commit 1’s Docker image initially omitted migrate scripts / `render_start.sh`; explicit migration was applied before Commit 2. Commit 2 Dockerfile copies `migrate_*.py` and starts via `scripts/render_start.sh`. Startup `_ensure_financial_accuracy_schema()` remains a **best-effort safety net only**.

### Preferred migrate commands (future hosts)

```bash
python3 migrate_financial_accuracy.py --dry-run
python3 migrate_financial_accuracy.py --verify
# Only if refunds tables are missing:
python3 migrate_refunds.py
python3 migrate_financial_accuracy.py --verify
```

---

## Automated test totals

| Suite | Result |
|-------|--------|
| Full local suite (at release) | **303 passed**, **2 skipped**, **0 failed** |
| Skips | `tests/test_refund_pg_concurrency.py` — no `TEST_DATABASE_URL` |
| Focused financial/refund/migration (release validation) | Passed (incl. reconciliation, integrity, product refund analytics, migrate helpers) |

---

## Final revenue and profit rules

```
net revenue =
  gross completed-sale revenue
  − approved refund revenue attributed to the reporting period

net COGS =
  gross historical COGS
  − historical COGS reversed for approved refunded quantities

gross profit =
  net revenue − net COGS
```

| Concept | Rule |
|---------|------|
| Historical sold cost | `coalesce(SaleItem.unit_cost, Product.cost_price)` |
| Refund reporting date | `coalesce(Refund.approved_at, Refund.created_at)` |
| Inventory-on-hand valuation | Current `Product.cost_price` (not historical sale cost) |
| Sale period attribution | Sale `created_at` period |
| Product ↔ aggregate | `sum(product net revenue) = aggregate net revenue`; same for net COGS and GP |

Where header discounts make `Sale.total` differ from `Σ SaleItem.line_total`, product-level metrics follow line history; document any residual header gap when investigating totals.

---

## Refund lifecycle

Supported transitions:

```
PENDING → APPROVED
PENDING → REJECTED
PENDING → CANCELLED
```

Rules:

- **Only approved** refunds affect stock and finances.
- Pending, rejected, and cancelled refunds have **no** financial, stock, or GL effect.
- Approval is **idempotent** for side effects; duplicate approval returns **HTTP 409** (conflict).
- Stock restores **once** per approval.
- **One** GL refund posting per approved refund.
- Refunds do **not** create `Payment` or `Expense` rows.
- Pending refunds do **not** reserve refundable quantity.
- Overlapping pending refunds may exist; approval **re-checks** remaining capacity against other **approved** refunds and rejects over-refunds.

---

## Product refund allocation

**Preferred:**

```
RefundItem → SaleItem → historical unit cost (SaleItem.unit_cost)
```

**Legacy** approved refunds without `RefundItem` rows use deterministic proportional allocation:

- proportional by original line revenue;
- rounded to cents with `ROUND_HALF_UP`;
- final `SaleItem` absorbs remainder;
- allocation respects remaining refundable capacity.

---

## Cash and shift rules

```
expected cash =
  opening cash
  + cash sales
  − approved cash refunds
  − cash expenses
  − cash withdrawals
  + valid cash adjustments
```

```
net payment method =
  successful sales for method
  − approved refunds assigned to that method
```

Withdrawals affect **cash** (and may post to CoA by `purpose`) but are **not** operating expenses. Expenses affect P&L according to category/status and cash when paid in cash.

---

## Production acceptance evidence

Classification: **PRODUCTION ACCEPTANCE PASSED** on build `34fa2036dc4e` (`34fa2036dc4e621c140ec96261e26e7df3265b84`).

Controlled tenants (no credentials recorded):

| | |
|--|--|
| Tenant 6 | `SEC10 ACCEPTANCE STORE 20260821` |
| Isolation tenant 7 | `SEC10-ACCEPT-20260821 OTHER TENANT` |
| Test label | `SEC10-ACCEPT-20260821` |

Verified outcomes:

- Historical cost remained **10.00** on the sale line after live catalog cost changed to **14.00**.
- Cash refund reversed stock, revenue, COGS, GP, and cash **once**.
- Duplicate approval returned **409**; no duplicate inventory or second GL row.
- Non-cash (card) refund reduced the card method net without reducing cash-on-hand.
- Closed shift totals reconciled: **cash 91**, **card 12**, **total sales 103** (opening cash 100; four shift sales net of approved refunds).
- **One** journal entry per approved refund; rejected/cancelled refunds produced **no** JEs.
- **No** negative `Payment` rows; **no** refund-like `Expense` rows.
- Tenant isolation and cashier-without-approve permission checks passed.
- **No** acceptance-window HTTP **500** errors (Firestore credential warnings on register were non-blocking).

Acceptance rows remain labelled in production; do not delete financial history by hand.

---

## Known limitations

- PostgreSQL concurrent-approval test has **not** run with a dedicated `TEST_DATABASE_URL`.
- Cross-period production acceptance was **not** exercised across an actual UTC day boundary.
- Android withdrawal-purpose **runtime** testing remains pending.
- Browser console was not inspected interactively during acceptance.
- Firestore credential warnings occur during registration but do not fail registration.
- UTC-naive business-day UX remains deferred.
- Pending refunds do not reserve quantities.
- Header-level discount allocation is not redesigned.
- Cancellation lacks dedicated `cancelled_by` / `cancelled_at` fields.
- No post-approval refund reversal workflow exists.
- Existing `SEC10-ACCEPT-*` acceptance rows remain labelled in production.

---

## Rollback information

- Column adds (`unit_cost`, `currency`, `purpose`) are additive — rolling application code back to `170d278` / pre-finance app remains possible; unused columns/tables are harmless.
- New tables (`expenses`, `cash_movements`) can remain unused after app rollback.
- Backfills are data updates; restore from `2026-08-21T03_35Z.dir.tar.gz` (or a newer snapshot) if a backfill must be undone.
- CoA inserts (1050/1450/3300) are additive; safe to leave in place.
- Prefer restoring from the verified backup rather than manually editing production rows to “fix” totals.

---

## Next workstream: multi-branch handoff

The **next major workstream** is multi-branch support. Do **not** implement new `branch_id` wiring in the financial release commits or this documentation phase.

Future branch scope must include:

| Area | Direction |
|------|-----------|
| Stock | Per-branch on-hand (`BranchProductStock` / product stock semantics) |
| Sales | Consistent `Sale.branch_id` filters end-to-end |
| Cashiers and staff | Branch assignment and permissions |
| Shifts and tills | Per-branch till / cash-on-hand |
| Refunds | Inherit sale branch; restore correct branch stock |
| Expenses and withdrawals | Branch filter and till scope |
| Analytics | Branch and consolidated period metrics |
| Payment-method totals | Optional branch scope |
| Inventory movements | Branch provenance |
| Stock transfers | Inter-branch movement |
| GlazzerX | Glass sheets, putty, cutting plans, offcuts (branch-aware) |

Likely touchpoints already noted in earlier planning: `overview_service`, `finance_service`, `refund_service`, `cash_on_hand`, shift end, BI/forecasting, enterprise inventory routes.

---

## Next workstream: GlazzerX handoff

GlazzerX integration should begin **after** the branch foundation so that:

- glass inventory is branch-specific;
- putty inventory is branch-specific;
- quotations convert into the **selected branch’s** POS cart;
- offcuts belong to the cutting branch;
- inter-branch transfers can move full sheets and putty;
- branch and consolidated analytics remain consistent.

Do not start GlazzerX implementation until multi-branch inventory/sales foundations are in place.

---

## Schema checklist (reference)

| Item | Source |
|------|--------|
| `sale_items.unit_cost` | `migrate_financial_accuracy` |
| `store_settings.currency` | `migrate_financial_accuracy` |
| `withdrawals.purpose` | `migrate_financial_accuracy` |
| `expenses` / `cash_movements` | create_all via migrate script |
| `refunds` / `refund_items` + audit fields | `migrate_refunds` / create_all |
| JE `reference_type` / `reference_id` | existing accounting schema |

## PostgreSQL concurrency validation (still optional)

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST/DB
.venv/bin/python -m pytest tests/test_refund_pg_concurrency.py -v
```

SQLite unit tests cover sequential conflict; true concurrent `FOR UPDATE` was not executed in CI for this release.
