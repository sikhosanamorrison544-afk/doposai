# Multi-branch POS architecture (Section 12–13)

**Status:** Section 12 foundation + Section 13 management/switching.
Financial release closed at app commit `34fa203`.
**Do not** run `migrate_branches.py` against production in this phase.

## Section 14 decisions (locked)

| Topic | Decision |
|-------|----------|
| Stock SoT | `BranchProductStock.stock_qty` (NUMERIC 18,4) is authoritative |
| Legacy shadow | `Product.stock_qty` = sum of branch quantities; remove after Android + all readers migrate |
| Writes | Require concrete branch; `scope=all` rejected with 400 |
| JournalEntry | Additive nullable `branch_id` stamped on new sale/refund/expense/withdrawal posts |
| Deactivation | Blocked by open shifts, pending refunds, or non-zero stock |
| Offline | `branch_id` on sale payload validated; same `client_sale_id` + different branch → 409 |

---

Production reference commits:

| Role | Hash |
|------|------|
| Financial app release | `34fa2036dc4e621c140ec96261e26e7df3265b84` |
| Financial docs | `bb5da743b09ef3d81343ea32da640410f23b5875`, `5bb2aad945abe120cd9daf81f19235963c1525b0` |

---

## 1. Current single-store assumptions (discovered)

| Area | Behaviour today | Risk |
|------|-----------------|------|
| **Product stock** | `Product.stock_qty` is POS source of truth | Multi-branch stock incorrect until dual-write + read path switch |
| **BranchProductStock** | Exists; updated on some enterprise paths only | Incomplete coverage |
| **Sale / Shift / User** | Have nullable `branch_id` | Many historical rows NULL; cashiers filtered via `User.branch_id` |
| **Refund / Withdrawal** | Tenant-scoped; branch nullable (additive) | Refund stock restore still hits product-global qty |
| **Expense / CashMovement** | Have `branch_id` | Filters incomplete in some analytics |
| **Payment / SaleItem / RefundItem** | No `branch_id` | Inherit from parent — intentional |
| **InventoryMovement** | Was product-only | Additive `tenant_id` / `branch_id` |
| **JournalEntry** | No tenant/branch | Trace via reference; consolidated GL later |
| **StoreSettings** | One branding row per tenant | Tenant-scoped lookups (Section 13 fixed unsafe `.first()`) |
| **Offline Android** | `client_sale_id` idempotent; no `branch_id` in DTO | Branch assigned from server user assignment until Section 17 |

Tenant isolation remains primary. Branch is an **additional** scope inside a tenant.

---

## 2. Ownership hierarchy

```
Tenant / Shop Owner
├── Main Branch   (is_default / is_main, code=MAIN)
├── Branch 2
└── Branch 3
```

**Branch** (`branches`): `id`, `tenant_id`, `name`, `code`, `address`, `phone`, `email`, `manager_user_id`, `is_default` (= `is_main`), `is_active`, timestamps.

Constraints:

- Unique `(tenant_id, name)` and `(tenant_id, code)`
- Application / migration ensure exactly one `is_default` Main Branch per tenant
- Soft deactivate; do not hard-delete branches with financial history

---

## 3. Staff membership

**UserBranch** (`user_branches`): `user_id`, `branch_id`, `tenant_id`, `role`, `is_default`, `is_active`, `assigned_at`, `assigned_by_id`.

- Owners/admins may access all tenant branches without exclusive reliance on membership rows (memberships still backfilled for consistency).
- Cashiers/supervisors require active membership **or** legacy `User.branch_id`.
- Prefer membership over a single mutable `User.branch_id` for multi-branch staff; keep `User.branch_id` as default/compat.

---

## 4. Active branch context

Module: `app/branch_context.py`

| Source | Use |
|--------|-----|
| `X-Branch-Id` header | Explicit request branch (validated) |
| Query `branch_id` | Explicit (validated) |
| Membership / `User.branch_id` / Main Branch | Default when none supplied |

Rules:

1. Tenant from authenticated identity only.
2. Branch must belong to that tenant.
3. User must have access; owners see all active (and inactive for history).
4. Invalid / unauthorized explicit branch → **400/403/404**, never silent fallback.
5. Frontend `localStorage` may remember last branch; **never** authorization.
6. Log `tenant_id`, `branch_id`, `branch_source` on resolution.

---

## 5. Branch inventory

**BranchProductStock** (= BranchInventory): unique `(branch_id, product_id)`; `stock_qty` / `reserved_qty` (float for GlazzerX readiness); optional `reorder_level`, `reorder_quantity`, `tenant_id`.

**Transition path:**

1. Backfill Main Branch inventory from `Product.stock_qty` (copy, do not zero product).
2. Dual-write on stock changes when `branch_id` known.
3. Later: POS reads branch stock; retire product qty as SoT (separate phase).

---

## 6. Transactional branch scope

| Model | `branch_id` | Notes |
|-------|-------------|-------|
| Sale | Yes | Set at create |
| Payment | No | Via sale |
| SaleItem | No | Via sale |
| CashierShift | Yes | One branch + cashier |
| Refund | Yes (additive) | Must match `sale.branch_id` for stock restore |
| RefundItem | No | Via refund |
| Expense | Yes | |
| Withdrawal | Yes (additive) | |
| CashMovement | Yes | |
| InventoryMovement | Yes (additive) | |
| JournalEntry | No (yet) | Inherit from reference |

---

## 7. Financial compatibility (unchanged formulas)

```
net revenue = gross sales − approved refunds
net COGS = gross historical COGS − reversed historical COGS
gross profit = net revenue − net COGS
```

Branch filters must be applied consistently to revenue, COGS, profit, refunds, expenses, withdrawals, cash-on-hand, payment methods, product analytics, shifts, inventory turnover.

**Consolidated owner views** sum branch metrics.
**Inter-branch transfers must never** create sales revenue, COGS, Payment rows, Expense rows, customer debt, or gross profit.

---

## 8. Stock transfer lifecycle (model ready; workflow later)

```
DRAFT → REQUESTED → APPROVED → DISPATCHED → RECEIVED
                 ↘ REJECTED / CANCELLED
```

- **DISPATCHED:** source qty ↓, in-transit ↑
- **RECEIVED:** in-transit ↓, destination qty ↑
- Do **not** credit destination at request/approval.

Idempotency: `client_transfer_id`; separate keys for dispatch vs receive events.

---

## 9. Offline / idempotency

| Event | Key |
|-------|-----|
| Sale | `(tenant_id, client_sale_id)` |
| Refund | existing refund number / client key (extend with branch) |
| Inventory movement | `client_movement_id` |
| Transfer | `client_transfer_id` |
| Transfer dispatch / receive | event-scoped keys (future) |

Every offline payload must store **originating `branch_id`** explicitly (`ensure_offline_branch_id`). Wrong branch must fail validation, not be reassigned silently.

---

## 10. GlazzerX readiness (not integrated)

Architecture allows later:

- Branch-owned sheets, putty, offcuts, cutting plans, quotations
- Decimal quantities, dimensions, m², kg, containers
- Identifiable sheet/offcut records (not integer-only stock)
- Inter-branch transfer of sheets/putty; optional offcuts
- Consolidated glass sales / waste analytics

Avoid designing stock exclusively around integer item counts.

---

## 11. Migration order

```
create / alter schema
→ one Main Branch per tenant (idempotent)
→ UserBranch memberships
→ BranchProductStock from Product.stock_qty
→ backfill branch_id on transactional rows
→ verify counts / null branch / financial totals unchanged
→ enable branch-aware app paths (later)
→ retire legacy Product.stock_qty SoT (later)
```

Script: `python3 migrate_branches.py --dry-run | --verify | (apply)`.

**Rollback / recovery:** additive columns and rows; reverse by leaving data (prefer soft flags). Do not delete Main Branch rows. Restore from DB backup if needed.

---

## 12. Permissions (proposed + wired)

`branch.create|view|update|deactivate|switch`, `branch.staff.assign`, `branch.stock.view|adjust`, `branch.transfer.request|approve|dispatch|receive`, `branch.analytics.view|consolidated`.

Roles: owner/admin (all), supervisor (ops + limited transfers), cashier (view/switch/stock view on assigned), plus future stock_controller / accountant via membership role.

Existing single-store users continue via Main Branch after backfill.
