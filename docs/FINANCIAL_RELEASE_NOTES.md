# Financial release — production migration & branch readiness

## Migration execution plan (do not run against production from this phase)

Preferred order:

1. **Backup** production database (Render snapshot / `pg_dump`).
2. **Inspect** current schema:
   ```bash
   python3 migrate_financial_accuracy.py --dry-run
   ```
3. **Migrate** (idempotent):
   ```bash
   python3 migrate_financial_accuracy.py --verify
   # If refunds tables are missing on older hosts:
   python3 migrate_refunds.py
   python3 migrate_financial_accuracy.py --verify
   ```
4. **Verify** checklist keys all `True` (script exits non-zero on failure with `--verify`).
5. **Deploy** application build that includes `app/finance_service.py`, expenses, refund integrity.
6. **Smoke**: `/health`, login, overview, reports summary, create/approve refund, cash till.

### Timing

- Run migration **before** application deploy (manual or Render **pre-deploy** command).
- Startup `_ensure_financial_accuracy_schema()` is a **best-effort safety net only** — not the primary path.
- Do **not** rely on `create_all` alone for production column adds.

### Rollback / recovery

- Column adds (`unit_cost`, `currency`, `purpose`) are additive/nullable or defaulted — app rollback to prior code remains possible.
- New tables (`expenses`, `cash_movements`) can remain unused if app is rolled back.
- Backfills are data updates; restore from backup if a backfill must be undone.
- CoA inserts (1050/1450/3300) are additive; safe to leave in place.

### Schema checklist

| Item | Source |
|------|--------|
| `sale_items.unit_cost` | migrate_financial_accuracy |
| `store_settings.currency` | migrate_financial_accuracy |
| `withdrawals.purpose` | migrate_financial_accuracy |
| `expenses` / `cash_movements` | create_all via migrate script |
| `refunds` / `refund_items` + audit fields | migrate_refunds / create_all |
| JE `reference_type` / `reference_id` | existing accounting schema |

## PostgreSQL concurrency validation

SQLite unit tests cover sequential conflict. True concurrent `FOR UPDATE` was not executed in CI.

When available:

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST/DB
.venv/bin/python -m pytest tests/test_refund_pg_concurrency.py -v
```

Procedure covers overlapping pending refunds and double-approve of the same refund.

## Branch-readiness assumptions (do not implement now)

| Current scope | Future branch scope | Likely touchpoints |
|---------------|---------------------|--------------------|
| Product stock (tenant) | Per-branch stock | `Product.stock_qty`, `BranchProductStock`, refund restore |
| Sales / SaleItems | `Sale.branch_id` already exists; filters incomplete | overview, finance helpers, BI |
| Refunds | Inherit sale branch; restore correct branch stock | `refund_service._apply_refund_effects` |
| Shifts / till cash | Branch till | `CashierShift`, `cash_on_hand`, `end_shift` |
| Expenses / withdrawals | Branch filter | `Expense.branch_id`, withdrawal tenant-only today |
| Payment-method nets | Branch optional | `payment_method_net_totals` |
| Analytics / AI rankings | Branch-aware period metrics | `product_period_metrics`, BI, forecasting |
| Inventory movements | Branch provenance | `InventoryMovement` (no tenant/branch today) |
| Reorder / GlazzerX glass/putty/offcuts | Branch inventory + enterprise ops | `enterprise/routes`, inventory_ops |

Do not add `branch_id` in the financial release commits.
