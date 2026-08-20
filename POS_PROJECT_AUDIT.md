# POS Project Audit Report

**Audit date:** 2026-08-19  
**Workspace:** `/home/morrison/Desktop/pos`  
**Auditor role:** Read-only inspection for handoff to an external developer  
**Scope:** Full project inspection; safe tests and static checks only; no application code changes

> **Remediation note (2026-08-19 working tree, not yet committed):** Phase 1 auth hardening in this workspace removes unauthenticated `POST /api/repair-admin`, requires a validated `JWT_SECRET_KEY` (no code fallback), and stops factory-reset / bootstrap from creating default `admin`/`admin` credentials. Treat Critical items #1 and the JWT/default-credential bullets below as **addressed in the pending diff**; re-verify after commit/deploy.

---

## 1. Executive Summary

This repository is a hybrid **SaaS + offline POS** product (branded around **DoPOS / All In One POS / doposai.com**). It started as a Raspberry Pi offline SQLite POS and has grown into a multi-tenant FastAPI backend, vanilla JS web UI, Android offline APK (Room + sync queue), enterprise inventory modules, accounting, billing (Paynow), WhatsApp chatbot, and optional AI/BI services.

**Core POS checkout works end-to-end** (cart → `/api/sales` → stock deduction → payments → receipt print attempt), with Android offline sales and `client_sale_id` idempotency. The system is **not production-hardened**.

Highest-priority issues for the finishing developer:

1. **Critical unauthenticated admin recovery** (`POST /api/repair-admin`) resets/creates `admin` with a known default password.
2. **Client-trusted sale prices/discounts** — server does not re-validate against product selling prices.
3. **Dual inventory models** (`products.stock_qty` vs `branch_product_stock`) — sales do not update branch stock.
4. **Money type inconsistency** — `Float` stock vs `Numeric` money; Android cart math uses `Double`.
5. **Offline sync is real but fragile** — local deduct-then-push, permanent failed queues, product wipe-on-pull, weak conflict handling.
6. **Security debt** — default JWT secret fallback, factory-reset default credentials, hard-coded password utility scripts, XSS via `innerHTML` with product/customer names.
7. **Test gaps** — no sale/checkout/inventory/offline-sync E2E coverage; 4 platform-owner tests fail in full suite (import/env pollution).

**Readiness verdict:** Suitable for **local development** and cautious **internal testing**. Not ready for full production without Priority 0 security and financial integrity work. Limited pilot only after closing Critical/High findings.

---

## 2. Project Overview

| Item | Finding |
| ---- | ------- |
| **Project name** | POS / DoPOS AI / All In One POS (Android package `com.pos.mobile`, APK names `doposai-*`) |
| **Purpose** | Point-of-sale for retail (Zimbabwe-oriented: EcoCash/Paynow, VAT accounting, USD-style display), with SaaS tenancy, offline mobile, layby, credit, refunds, enterprise purchasing |
| **Languages** | Python 3.11+/3.13 (backend), JavaScript (web), Kotlin (Android), SQL (SQLite/Postgres), shell scripts |
| **Architecture** | Hybrid: local/desktop web + cloud SaaS API + Android native/WebView hybrid |
| **Package managers** | `pip` (`requirements.txt`); Android Gradle/Kotlin; no root `package.json` |
| **Database** | SQLite (`pos.db`) locally; PostgreSQL supported via `DATABASE_URL` (Render/docker-compose) |
| **ORM** | SQLAlchemy 2.0 |
| **Migrations** | Alembic (thin; many ad-hoc `migrate_*.py` scripts + `create_all` at startup) |
| **State management** | Server session/JWT; web `localStorage`; Android Room + SharedPreferences |
| **UI** | Jinja2 templates + vanilla JS/CSS; Android Jetpack (Activities/Fragments) + WebView shells |
| **Testing** | `pytest` (Python); no Android unit tests found in tree |
| **Build** | Uvicorn/Gunicorn; Docker; Render blueprint; Android Gradle APK/AAB scripts |
| **Deployment** | Render (`render.yaml`), Docker Compose, systemd, Cloudflare tunnel docs, desktop launcher |
| **Offline storage** | Android Room; browser `localStorage` mutation queue; SQLite on server/Pi |
| **Cloud sync** | Android → cloud API; optional Google Sheets backup; optional Firestore for billing/security plane |
| **Receipt printing** | ESC/POS (`app/escpos_printer.py`, Android Bluetooth/USB printers, browser print helpers) |
| **Barcode** | USB HID keyboard wedge into `#barcode-input`; API `GET /api/products/barcode/{barcode}`; auto `AUTO-######` barcodes |

**Architecture in plain language:** Cashiers use either the browser POS or the Android app. The Android app keeps products and sales locally and pushes sales when online. The FastAPI server is the system of record for cloud tenants. Each business is a **tenant**; users have roles (admin/supervisor/cashier). Enterprise features add suppliers, POs, branches, transfers, and adjustments. Billing gates some features by subscription plan.

---

## 3. Technology Stack

### Backend
- FastAPI `0.115.0`, Uvicorn, Gunicorn
- SQLAlchemy `2.0.35`, Alembic `1.13.3`
- Passlib (pbkdf2_sha256), python-jose (JWT HS256)
- Pydantic `2.9.2`, Jinja2, python-multipart
- ReportLab, pdfplumber, python-docx
- APScheduler, httpx, requests
- firebase-admin, paynow, psycopg2-binary

### Frontend (web)
- No React/Vue/Angular — server-rendered HTML + `static/js/*.js`
- Notable JS: `app.js` (POS), `admin.js`, `offline-fetch.js`, `receipt*.js`, `billing.js`, `enterprise.js`

### Android
- Kotlin, minSdk 24, targetSdk 34
- Room, Retrofit/OkHttp (via project deps), WorkManager-style sync (`SyncWorker` / `SyncScheduler`)
- versionName **1.4.4**, versionCode **29**
- Default API: `https://doposai.onrender.com/` (overridable in `local.properties`)

### AI / BI
- In-process `app/ai_service.py` (Ollama-oriented legacy)
- Separate `ai-service/` microservice (vLLM/Qwen)
- `app/bi/` analytics + advisor routes

### Not present
- No root npm/yarn workspace
- No Electron; “desktop” = launcher opening localhost browser
- No dedicated tax engine on the sale line (VAT mainly in accounting posts)

---

## 4. Folder Structure

```
pos/
├── app/                      # FastAPI application (core backend)
│   ├── main.py               # Large monolith: most POS API + pages (~5.2k lines)
│   ├── models.py             # Core ORM models
│   ├── auth.py, permissions.py, tenant_scope.py
│   ├── database.py, config.py, init_db.py
│   ├── accounting_*.py       # Double-entry accounting
│   ├── billing/              # SaaS plans, Paynow
│   ├── enterprise/           # Branches, PO, transfers, adjustments
│   ├── bi/                   # Business intelligence / AI advisor
│   ├── whatsapp/             # Meta WhatsApp Cloud API chatbot
│   ├── refund_service.py, quotation_*.py, backup_service.py
│   └── escpos_printer.py, product_barcodes.py, inventory_*.py
├── templates/                # Jinja2 HTML pages (POS, admin, layby, billing, …)
├── static/                   # CSS/JS/assets for web UI
├── android-app/              # Kotlin offline POS + WebView
├── ai-service/               # Optional Contabo/vLLM AI microservice
├── alembic/                  # Formal migrations (minimal)
├── tests/                    # pytest suite
├── docs/                     # Deployment / BI / architecture notes
├── scripts/                  # Deploy helpers, AI terminal test
├── nginx/, systemd/          # Ops configs
├── migrate_*.py              # One-shot schema migrations (legacy style)
├── requirements.txt
├── docker-compose.yml, Dockerfile, render.yaml
├── launch_pos.py, start_server.sh
├── pos.db                    # Local SQLite database (runtime data)
├── backup_config.json        # Google Sheets backup settings
└── *.md                      # Many historical status/design docs
```

### Major folder purposes

| Path | Purpose |
| ---- | ------- |
| `app/` | Server business logic and HTTP API |
| `templates/` | Multi-page web UI shells |
| `static/` | Client behavior (cart, admin, offline queue, printing) |
| `android-app/` | Offline-first mobile client + thermal printing |
| `ai-service/` | Separate AI inference service |
| `tests/` | Automated Python tests (narrow coverage) |
| `alembic/` | Intended long-term migration path |
| `docs/` | Deploy and architecture guides |
| Root `migrate_*.py` | Historical SQLite/Postgres patch scripts |

**Excluded from tree above:** `node_modules` (none), `.git`, `.venv`, `__pycache__`, Android `build/`, APK binaries, large media (`background.mov`, GLB).

---

## 5. Architecture

```
[Android APK] --offline--> Room DB --sync--> FastAPI (cloud or LAN)
[Browser POS] --JWT--> FastAPI <--SQLAlchemy--> SQLite or Postgres
                              |
                              +--> ESC/POS device (optional)
                              +--> Google Sheets Apps Script (optional backup)
                              +--> Firestore (optional billing/security)
                              +--> Paynow (subscriptions)
                              +--> WhatsApp Cloud API
                              +--> ai-service / Ollama (optional)
```

- **Monolith pressure:** `app/main.py` owns most POS routes; enterprise/billing/whatsapp/bi are routers but core sales remain in `main.py`.
- **Tenancy:** `Tenant` model + `tenant_id` on many tables; `tenant_scope.py` filters queries. Legacy rows use `tenant_id IS NULL`.
- **Branches:** Enterprise `Branch` + `BranchProductStock`; sales store `branch_id` but primary stock is still `products.stock_qty`.
- **Offline:** Android is the real offline POS; web `offline-fetch.js` queues mutations in localStorage as a lighter fallback.

---

## 6. Current Feature Matrix

| Feature | Status | Evidence | Relevant files | Problems found | Recommended next action |
| ------- | ------ | -------- | -------------- | -------------- | ----------------------- |
| Authentication (JWT) | Complete | Login token + `/api/auth/me` | `app/auth.py`, `app/saas_auth_routes.py`, `static/js/app.js` | Default JWT secret fallback | Require strong `JWT_SECRET_KEY` in production |
| Refresh tokens / password reset | Partially implemented | Models + SaaS routes | `app/saas_models.py`, `app/saas_auth_routes.py` | Depends on SMTP config | Verify email path in staging |
| Roles/permissions | Complete (API) | `Perm` enum + deps | `app/permissions.py` | Some UI-only gates; cashier limited | Add tests for every sensitive route |
| Products CRUD | Complete | `/api/products*` | `app/main.py`, `app/models.py` | Global unique barcode | Per-tenant barcode uniqueness |
| Categories | Partial | Created via import/`get_or_create_category`; no dedicated CRUD API | `app/main.py` | No `/api/categories` | Add category CRUD if needed |
| Inventory qty | Complete (mutable) | `stock_qty` + movements | `app/models.py`, sale path | Float; dual branch stock | Unify stock source of truth |
| Stock receiving (PO) | Complete (enterprise) | PO receive endpoints | `app/enterprise/routes.py` | May diverge from POS stock | Ensure sale + PO share one stock API |
| Stock adjustments | Complete | Adjust/approve | `enterprise/routes.py`, `inventory_ops.py` | Approval workflow only | Cover with tests |
| Stock transfers | Complete | Transfer send/receive | `enterprise/routes.py` | Branch stock vs product stock | Atomic branch+product updates |
| Sales / cart / checkout | Complete | Web + Android + API | `static/js/app.js`, `PosViewModel.kt`, `main.py` | Client prices trusted | Server-side price policy |
| Payments | Complete | cash/mobile/card/credit | `Payment` model, sale create | Overpayment allowed; no change field | Validate payment sum bounds |
| Receipts / printing | Partial–Complete | ESC/POS + Android printers | `escpos_printer.py`, `ReceiptPrinter.kt` | Pi device path often missing | Graceful no-printer path (mostly OK) |
| Customers / credit | Complete | Customer + credit payment | `models.py`, sale create | Credit balance only increases on credit pay | Credit collection flow clarity |
| Suppliers | Complete | Enterprise suppliers | `enterprise_models.py` | Plan-gated | — |
| Credit sales | Complete | `method=credit` | `main.py` | No credit limit | Add limits if required |
| Expenses / withdrawals | Complete | `/api/withdrawals` | `main.py` | Accounting mapping optional | — |
| Returns / refunds | Complete | Request/approve + stock restore | `refund_service.py` | Accounting can roll back approval path carefully | Add refund tests beyond stub |
| Discounts | Complete | Per-line discount | sale create, cart JS | No max-discount policy | Cap/permission discounts |
| Taxes on POS | Missing/partial | Quotation has `tax_total`; sale has no tax fields; VAT assumed 15% in accounting | `accounting_engine.py` | POS total ≠ VAT-aware | Explicit tax mode |
| Reports / analytics | Partial–Complete | Summary + analytics APIs + BI | `main.py`, `analytics*.py`, `app/bi/` | Expected profit deducts lifetime withdrawals oddly | Align report definitions |
| Branches / tenants | Partial–Complete | Models + filters | `tenant_scope.py`, enterprise | Branch FK missing on sales; stock not branch-aware on sale | Fix sale stock path |
| Settings | Complete | Store settings API | `main.py` | — | — |
| Barcode scanning | Complete | HID + lookup | `app.js`, barcode API | No weighted barcodes | Document scanner assumptions |
| Offline mode | Partial–Complete | Android Room sync; web queue | `SyncRepository.kt`, `offline-fetch.js` | Duplicate/stock race risks | Harden sync (Priority 3) |
| Cloud sync | Partial | Push sales + pull catalogs | Android sync | Wipe products on pull | Incremental sync |
| Backups | Partial | Google Sheets + factory reset | `backup_service.py` | Not a true DB backup/restore | SQLite/PG dump strategy |
| Audit logs | Partial | Enterprise audit | `audit_service.py` | Not on every sale | Log sales/refunds |
| Licensing / subscriptions | Complete | Paynow + feature middleware | `app/billing/` | Offline grace 72h | Test entitlement edge cases |
| Layby | Complete | Customers/txns/payments | `main.py`, templates | Reserved stock path | Tests |
| Quotations | Complete | Convert to sale | `quotation_*.py` | Tax total unused | — |
| WhatsApp ordering | Partial–Complete | Webhook + router | `app/whatsapp/` | External deps | Staging verification |
| Camera barcode | Missing | No camera scanner found | — | — | Optional Android ML Kit |
| Serial/batch tracking | Missing | No models | — | — | Out of scope unless needed |

**Legend notes:** “Complete” means implemented and wired, not necessarily production-safe. Most features have **no dedicated automated tests**.

---

## 7. Database Review

### Tables present (local `pos.db`, 48 tables)

Core POS: `users`, `categories`, `products`, `customers`, `sales`, `sale_items`, `payments`, `inventory_movements`, `store_settings`, `cashier_shifts`, `notifications`, `import_jobs`

Layby: `layby_customers`, `layby_transactions`, `layby_payments`

Refunds: `refunds`, `refund_items`

Withdrawals: `withdrawals`

SaaS: `tenants`, `refresh_tokens`, `password_reset_tokens`, `subscriptions`, `subscription_payments`, `billing_logs`

Enterprise: `branches`, `branch_product_stock`, `suppliers`, `supplier_ledger_entries`, `purchase_orders`, `purchase_order_items`, `stock_adjustments`, `stock_transfers`, `stock_transfer_items`, `audit_logs`

Accounting: `chart_of_accounts`, `accounting_periods`, `journal_entries`, `journal_entry_lines`, `expense_account_mappings`, `fixed_assets`, `asset_depreciation_schedule`

Quotations: `quotations`, `quotation_items`

WhatsApp: `whatsapp_*` tables

### Important model notes

| Area | Detail |
| ---- | ------ |
| PKs | Integer surrogates almost everywhere; `import_jobs.id` UUID string |
| Money | Mostly `Numeric(10,2)` / `Numeric(12,2)` |
| Stock | `Float` on `products.stock_qty`, `reserved_qty`, movements `change_qty` |
| Soft delete | Generally **not** used (`is_active` on products/users/branches) |
| Tenant ownership | `tenant_id` nullable on most business tables |
| Branch ownership | On sales, shifts, some enterprise docs; **sales.branch_id has no FK** in live SQLite |
| Audit fields | `created_at` common; enterprise `audit_logs`; not universal |
| Idempotency | `sales.client_sale_id` unique per tenant (`uq_sales_tenant_client_sale_id`) |
| Inventory movements | Append-only log; **no `tenant_id`**; stock also stored mutably on product |
| Customer credit | `customers.credit_balance` mutable |
| Sync fields | Server: `client_sale_id`; Android local sync queue/status (client DB) |

### Snapshot counts (local DB at audit time; approximate)

Users ~14, tenants ~11, products ~1090, sales ~33, payments ~33, inventory_movements ~966, notifications ~1596, WhatsApp messages ~2132. **Do not treat as production metrics.**

### Migration status

- Alembic: `0001_placeholder_baseline`, `0002_billing_subscriptions` only
- Many one-shot `migrate_*.py` scripts
- App also runs ad-hoc `ALTER TABLE` at startup (e.g. `client_sale_id`)
- **Risk:** Schema drift between SQLite local, Postgres cloud, and ORM models

### Database problems

| Problem | Severity |
| ------- | -------- |
| Client-trusted money fields on sale create | High |
| `products.barcode` **globally** unique — breaks multi-tenant isolation | High |
| `users.username` globally unique — conflicts with every tenant wanting `admin` (mitigated partially by SaaS signup patterns; still fragile) | High |
| Dual stock: `products.stock_qty` vs `branch_product_stock` not updated together on sale | High |
| `inventory_movements` lacks `tenant_id` / `branch_id` / `sale_id` FK | Medium |
| Stock as `Float` — fractional drift / precision issues | Medium |
| No row locking (`FOR UPDATE`) on stock decrement — concurrent oversell | High |
| Sale create does not use explicit DB transaction API beyond session commit (OK if single session), but mid-loop HTTPException after flush can leave incomplete work depending on rollback discipline | Medium |
| Accounting tables lack `tenant_id` (CoA appears global) | High for SaaS |
| Nullable `tenant_id` legacy mode weakens isolation if mis-assigned | Medium |
| Refunds restore product stock but not branch stock | Medium |
| Payment unique `(sale_id, method)` prevents two cash tenders of same method | Low/Medium |
| Factory reset deletes SQLite file — unsafe on Postgres deployments | High if exposed |

---

## 8. Sales and Checkout Flow

### End-to-end map

| Step | Files / functions | DB ops | Validation | Error handling | Gaps / risks |
| ---- | ----------------- | ------ | ---------- | -------------- | ------------ |
| 1. Product search / barcode | `static/js/app.js` (`handleBarcodeEnter`, `productsIndex`); Android search; `GET /api/products/barcode/{barcode}` | Read products | Tenant filter on API | UI shows no match | Web relies on in-memory product index (stale risk) |
| 2. Add to cart | `app.js` / `PosViewModel` / `CartMath` | Local only | Stock warnings (web soft) | — | Web allows qty over stock with warning |
| 3. Qty changes | Cart UI | Local | `normalizedQty` on Android | — | Negative blocked on Android; web should clamp |
| 4. Price changes | Generally uses product selling price; line `unit_price` sent to API | — | **Server trusts client `unit_price`** | — | **Price manipulation risk** |
| 5. Discounts | Per-line | Trusted from client | Discount ≥ 0 mostly client-side | — | No server max % |
| 6. Taxes | Not on sale lines | Accounting assumes VAT inclusive 15% later | — | — | POS total has no tax breakdown |
| 7. Stock validation | Server: available = `stock_qty - reserved_qty` | Read product | Insufficient → 400 | HTTPException | No lock; race; ignores branch stock |
| 8. Customer | Optional `customer_id` | Scoped require | Tenant check | 404 | Required for credit path practically |
| 9. Payment selection | cash / mobile_money / card / credit | — | Sum ≥ total − 0.01 | 400 insufficient | Overpay OK; no change due computation |
| 10. Payment processing | Manual (no card gateway on sale) | Insert `payments` | Method string | — | Not real card capture |
| 11. Sale persistence | `create_sale` in `main.py` | Insert sale/items/payments | Items non-empty; total > 0 | Rollback on accounting/DB error | Idempotent via `client_sale_id` |
| 12. Stock deduction | Same request | Update `stock_qty`, insert `InventoryMovement` | After availability check | Constraint `stock_qty >= 0` | Not same as branch stock; reserved not increased for `to_collect` |
| 13. Receipt generation | Background `print_receipt_background` | Read sale | — | Log errors | Print failure does not undo sale (good) |
| 14. Receipt printing | ESC/POS device or Android printer | — | Device open | Returns false | `/dev/usb/lp0` often absent on cloud |
| 15. Offline queueing | Android sync queue; web `offline-fetch.js` | Local | Online check | Retry policy | Web queue has no idempotency UUID by default |
| 16. Cloud sync | `SyncRepository.pushSale` | POST `/api/sales` | HTTP retryable codes | Permanent fail after 40 attempts | Local stock already deducted |
| 17. Reports | `/api/reports/summary`, analytics | Aggregates | Tenant filter | — | Refunds may not adjust all report metrics equally |

### Transaction boundary (critical)

In `create_sale`:

1. Create sale + flush (idempotency conflict handling)
2. Create items + decrement stock + movements
3. Update shift totals
4. Create payments + credit balance
5. Post accounting journal (**inside same session before commit**)
6. `db.commit()`
7. Background print + low-stock

**Sale + payments + stock + accounting are intended to commit together.** If accounting throws, sale is rolled back. Good.

**Missing:** pessimistic locking; branch stock update; server price verification; payment upper bound; linking movement to `sale_id`.

---

## 9. Inventory Review

### Supported capabilities

| Capability | Status |
| ---------- | ------ |
| Opening stock | Via product create/import |
| Purchases / receiving | Enterprise PO receive |
| Adjustments | Damage/expired/lost/theft/manual/count variance |
| Sales deductions | Yes on `products.stock_qty` |
| Returns | Via approved refunds |
| Damaged / expired | Adjustment types |
| Transfers | Between branches |
| Multiple branches | Models + APIs; POS sale stock not branch-primary |
| Reorder levels | `low_stock_threshold` + notifications + enterprise reorder suggestions |
| Low-stock alerts | In-app + optional email |
| Stock counts | Via adjustment type `stock_count_variance` |
| Batch / serial | **Missing** |
| Valuation | Report uses `stock_qty * cost_price` |
| COGS / profit | Report uses line_total − cost×qty; accounting posts COGS |

### Stock model

**Both mutable quantity and movement log:**

- Source of truth for POS selling: **`products.stock_qty`** (mutable)
- Audit trail: **`inventory_movements`**
- Optional parallel: **`branch_product_stock.stock_qty`**

Layby uses **`reserved_qty`** (reserve on create, deduct on full pay).  
`to_collect` sales **still deduct stock immediately** (comment in code); reservation is not used for that path — naming is misleading.

### Inaccuracy causes

1. Concurrent sales without row locks  
2. Branch vs product dual writes  
3. Offline local deduct then failed/duplicate sync  
4. Float arithmetic  
5. Imports setting vs adding stock (`inventory_import.py` modes)  
6. Refunds restoring product but not branch qty  
7. Manual DB edits / one-shot fix scripts (`fix_negative_stock.py`)

---

## 10. Money and Calculation Review

| Topic | Finding |
| ----- | ------- |
| Server money type | `Decimal` / `Numeric(10,2)` for prices/totals |
| Stock type | `Float` (not money, but affects valuation) |
| Android / JS | `Double` / JS `Number` — floating point |
| Rounding | Refunds use `quantize(Decimal("0.01"))`; sales less explicit |
| Tax order | Not applied on POS; accounting treats total as VAT-inclusive at 15% |
| Discount order | Line: `unit_price * qty - discount` |
| Server vs client totals | **Server recalculates** subtotal/discount/total from line inputs, but **trusts client unit_price & discount** |
| Negative totals | Rejected (`total <= 0`) |
| Negative qty | Rejected on server |
| Payments vs total | Must be ≥ total − 0.01; **may exceed** (change not modeled) |
| Refunds limited | Yes — cannot exceed remaining line qty |

### Calculation bugs / risks

1. **Price spoofing** via API `unit_price`  
2. **Android `CartMath` floating point** vs server Decimal mismatch on edge cents  
3. **VAT assumed 15%** in accounting regardless of store settings  
4. **Report “expected profit”** subtracts **lifetime** withdrawals from stock projection — conceptually confusing / likely wrong for operators  
5. **Credit refund** reduces `credit_balance` but original credit sale increased it — OK if methods align; mixed tender refunds approximate via method  
6. **Shift totals** use additive updates; concurrent sales on same shift possible race  
7. Quotation `tax_total` default 0 — unused  

---

## 11. Offline and Synchronization Review

### Components

| Component | Tech |
| --------- | ---- |
| Local DB | Android Room (`AppDatabase`, entities/DAOs) |
| Offline queue | `sync_queue` + `OfflineMutationEntity` |
| Sync worker | `SyncRepository`, `SyncWorker`, `SyncScheduler`, `ConnectivitySyncMonitor` |
| Retry | `SyncPolicy`: max 40 attempts; retry 401/408/429/5xx and network errors |
| Deadline | 3-day sync deadline (warn at 2 days) — aligns with billing offline grace concept |
| Web fallback | `static/js/offline-fetch.js` → localStorage `pos_offline_mutations` |
| Sheets backup | `backup_service.py` + `offline_changes.json` (inventory backup, not sale ledger) |
| Idempotency | `client_sale_id` / UUID on Android push |
| Conflict resolution | **Minimal** — server wins on product pull (`deleteAll` + insert) |

### Current sync flow (Android)

1. UI reads local products/customers.  
2. Sale completes offline → local sale rows + stock deduct + enqueue.  
3. When online + valid token → `pushSale` POSTs `/api/sales` with `client_sale_id`.  
4. Server returns existing sale if duplicate id.  
5. Pull products/customers periodically; **replaces entire local product table**.  
6. Mutations (non-sale API writes) drained separately with retry/fail.

### Sync risks

| Risk | Why |
| ---- | --- |
| Duplicate sales | Mitigated by `client_sale_id` if always set; web queue may lack it |
| Duplicate stock deduction | Local deduct + server deduct; if local DB restored from backup, double risk |
| Missing records | Permanent failed queue after 40 tries |
| Wrong order | Queue order mostly FIFO but multi-device no vector clocks |
| Conflicting product edits | Last pull wins; local edits can be wiped |
| Conflicting stock | Server absolute qty overwrite on pull vs local deductions |
| Retried payments | Sale idempotent; other POSTs may not be |
| Deleted local before sync | Data loss |
| Internet fail mid-sync | Partial drain leaves remainder — OK if idempotent |

### Recommended safe sync design (for later implementation)

1. Append-only **operation log** with UUID, device_id, timestamp, tenant_id.  
2. Server applies ops idempotently inside DB transactions with stock locks.  
3. Never trust client stock; server returns authoritative qty.  
4. Incremental product sync with `updated_at` / version, not full wipe.  
5. Dead-letter UI for failed ops; block app wipe until drained or exported.  
6. Separate “financial ops” (sales/payments/refunds) from “catalog ops”.

---

## 12. Multi-Tenant and Branch Review

### How identity works

- JWT includes `sub` (username) and `tid` (tenant id); `get_current_user` rejects tid mismatch.  
- Row visibility via `tenant_scope.filter_*` and `get_scoped`.  
- Branch restriction: cashiers with `branch_id` see filtered sales/shifts; admins/supervisors unrestricted.

### Isolation strengths

- Most POS entities carry `tenant_id` and are filtered.  
- Platform owner APIs gated by allowlist (email preferred).  
- Product barcode lookup is tenant-filtered in queries.

### Isolation weaknesses (with paths)

| Issue | Path |
| ----- | ---- |
| Global unique `products.barcode` | `app/models.py` — tenant A blocks tenant B’s barcode |
| Global unique `users.username` | `app/models.py` — SaaS multi-admin naming pain |
| Accounting CoA / journals lack tenant_id | `app/accounting_models.py` |
| Inventory movements lack tenant_id | `app/models.py` |
| `POST /api/repair-admin` creates unscoped admin | `app/main.py` |
| Nullable tenant legacy rows | `tenant_scope.py` design |
| Sales `branch_id` without FK | Live DB schema |
| Sale stock ignores `branch_product_stock` | `create_sale` vs `inventory_ops.py` |
| Chart of accounts `code` globally unique | Multi-tenant accounting collision |
| Username-based platform owner allowlist | `app/config.py`, `platform_routes.py` — dangerous if set to `admin` |

---

## 13. Authentication and Permissions

### Login / tokens

- `POST /api/auth/token` — OAuth2 password form → JWT (8h).  
- Refresh tokens + password reset in SaaS routes.  
- Passwords: **pbkdf2_sha256** via passlib (good).  
- JWT secret: `JWT_SECRET_KEY` or insecure default string in `auth.py`.

### Roles

| Role | Access summary |
| ---- | -------------- |
| admin / owner | All `Perm` values |
| supervisor | Sales, view inventory, withdrawals, refunds approve, pending collection, reports, shifts |
| cashier | Sales, view inventory, request refunds |

### Enforcement

- FastAPI `Depends(dep_perm(...))` / admin deps on many routes.  
- Feature gating via billing middleware/plans.  
- UI also uses `role-permissions.js` / Android prefs — **not sufficient alone**.

### Problems

| Finding | Severity |
| ------- | -------- |
| Unauthenticated `/api/repair-admin` | **Critical** |
| Factory reset recreates `admin`/`admin` | High |
| Hard-coded password utility `reset_morrison_password.py` | High (ops script) |
| Default JWT secret | Critical if deployed without env |
| Tokens in `localStorage` / SharedPreferences | Medium (XSS/device theft) |
| Some pages may rely on client redirects | Medium |

**Default credentials:** Do not use in production. Factory/repair paths recreate known defaults — remove or protect before any public deploy.

---

## 14. Security Findings

| Sev | Description | Evidence | File | Impact | Fix |
| --- | ----------- | -------- | ---- | ------ | --- |
| Critical | Unauthenticated admin password reset/create to known default | `repair_admin_user` | `app/main.py` | Full takeover | Remove endpoint or require out-of-band secret + disable in prod |
| Critical | JWT falls back to hard-coded secret | `SECRET_KEY = os.getenv(..., "change-this-...")` | `app/auth.py` | Token forgery | Fail fast if unset in production |
| High | Client-controlled sale prices | `unit_price` from payload | `app/main.py` `create_sale` | Fraudulent discounts/prices | Re-price from DB unless admin override permission |
| High | Factory reset + default admin credentials | `factory_reset` | `app/main.py` | Data wipe + weak login | Disable on cloud; require typed confirmation phrase |
| High | XSS via `innerHTML` with product/customer names | Template strings | `static/js/app.js` | Session token theft | Prefer `textContent` / sanitize |
| High | Global barcode uniqueness across tenants | Unique on `barcode` | `models.py` | DoS / data conflict | Unique `(tenant_id, barcode)` |
| High | Concurrent stock oversell | No `with_for_update` | `create_sale` | Negative/oversell attempts | Lock rows; serialize stock updates |
| Medium | CORS configurable to `*` | `get_cors_origins_and_credentials` | `config.py` | CSRF-ish API abuse with tokens in JS | Keep explicit origins + credentials |
| Medium | Sensitive scripts in repo | password reset script | `reset_morrison_password.py` | Credential reset if run | Remove from prod images; rotate passwords |
| Medium | Google Sheets webhook URL in `backup_config.json` | enabled config | `backup_config.json` | Inventory exfil if URL leaked | Treat as secret; rotate Apps Script deployment |
| Medium | Error messages may include exception strings | HTTP 500 details | `main.py` | Info leak | Generic client errors |
| Medium | SQL injection | Mostly ORM | — | Low if stays ORM | Avoid raw f-string SQL in migrations on user input |
| Low | `datetime.utcnow` deprecations | many files | — | Future break | Migrate to aware UTC |
| Low | Debug-ish repair endpoints | repair-admin | — | — | Gate by `APP_ENV` |

**Dependency vulnerabilities:** Not scanned in this audit (`pip audit` / Dependabot not run). Recommend running in CI.

**Test accounts in production:** Repair/factory paths recreate them — treat as Critical process risk.

---

## 15. Receipt and Printing Review

| Aspect | Status |
| ------ | ------ |
| Templates | Procedural ESC/POS builder (not HTML template); web receipt JS helpers |
| Numbering | Uses sale id; layby payments have `receipt_number` |
| Business info | From `StoreSettings` / config fallbacks |
| Customer / cashier | Included when available |
| Items, qty, prices, discounts, totals | Yes |
| Taxes | Not shown as separate POS tax lines |
| Payment method / amounts | Yes |
| Change | Not first-class |
| Branch details | Not clearly on ESC/POS header |
| Printer integration | `/dev/usb/lp0` server-side; Android BT/USB |
| Paper sizes | Comments for 48/80mm; width constant 48 chars |
| Reprint | Client-side reprint possible; server print is fire-and-forget |
| Duplicate indicators | Collection status text; no explicit DUPLICATE mark |
| PDF | Quotations/price list/statements — not primary sale receipt |
| Thermal support | Yes (ESC/POS) |

**Incomplete/broken behaviors:** Cloud hosts cannot open Pi printer device (print fails silently after sale — acceptable). Receipt depends on background task succeeding. Android printing more relevant for mobile deployments.

---

## 16. Barcode Review

| Topic | Finding |
| ----- | ------- |
| Scanner input | Keyboard wedge into focused input |
| Camera scanning | Not found |
| Generation | `AUTO-######` per tenant sequence (`product_barcodes.py`) |
| Uniqueness | DB unique **global** on `barcode` — conflict with per-tenant generation |
| Duplicate handling | Create/update errors on constraint |
| Lookup speed | Indexed barcode; web uses in-memory map |
| Unknown barcode | Search/no-add UX |
| Weighted barcodes | Not supported |
| Barcode printing | Not a dedicated label module |
| Offline lookup | Android local Room by barcode |

**Files:** `app/product_barcodes.py`, `GET /api/products/barcode/{barcode}`, `static/js/app.js`, Android product DAO/search.

---

## 17. Reporting and Analytics Review

| Report | Data source | Notes |
| ------ | ----------- | ----- |
| Summary (`/api/reports/summary`) | Live SQL aggregates | Tenant filtered; profit from sale lines − cost |
| Top/least selling, revenue, zero sales | Live | Analytics endpoints |
| Analytics bootstrap/dashboard | Live + helpers | `analytics_page_data.py` |
| Accounting P&L, BS, VAT, TB, GL | Journal entries | Requires CoA init |
| Enterprise branch sales/inventory | Live | |
| BI advisor | Analytics + AI service | Can degrade gracefully |
| Expected profit metric | Stock × margin − **all-time withdrawals** | Suspicious definition |
| Cash on hand | Cash payments − withdrawals − cash refunds in range | Reasonable |

**Mock data:** Primary reports use DB. AI text may hallucinate if model weak — verify numerically against APIs.

**Refund alignment:** Confirm summary net sales does not subtract refunds unless coded — inspect showed sales sum without refund deduction in the opening aggregates (potential overstatement).

---

## 18. Testing Results

### Framework
- `pytest` with FastAPI/SQLAlchemy tests under `tests/`

### Coverage map

| Area | Present? |
| ---- | -------- |
| Unit | Yes (WhatsApp parser/signature, permissions, CSV, platform gate) |
| Integration | Partial (quotation stock/pdf, refunds stub, admin reset) |
| E2E POS sale | **No** |
| Inventory concurrency | **No** |
| Offline sync | **No** |
| Tenant isolation suite | Partial (WhatsApp tenant routing; not full matrix) |
| Receipt | **No** |
| Money rounding | **No** |

### Command run

```bash
.venv/bin/python -m pytest tests/ --tb=line -q
```

| Result | Detail |
| ------ | ------ |
| Exit code | **1** |
| Passed | **65** |
| Failed | **4** |
| Warnings | ~230 (mostly `datetime.utcnow` deprecation, Pydantic config) |

**Failed tests (full suite only):**

- `tests/test_platform_owner_gate.py::test_email_match_grants_access`
- `...::test_email_match_is_case_insensitive`
- `...::test_username_match_grants_access`
- `...::test_is_platform_owner_tenant_by_tenant_email`

**Cause:** Import-order / env allowlist pollution — `PLATFORM_OWNER_*` frozensets empty when module loaded amid full suite; **same file passes in isolation** (9 passed).

Also run:

```bash
.venv/bin/python -m compileall -q app tests   # exit 0
.venv/bin/python -c "from app.main import app"  # success, ~195 routes
```

---

## 19. Build and Static-Check Results

| Command | Exit | Result | Notes |
| ------- | ---- | ------ | ----- |
| `pytest tests/` | 1 | 65 pass / 4 fail | See §18 |
| `python -m compileall -q app tests` | 0 | OK | Syntax clean |
| Import `app.main` | 0 | OK | Quotation routes registered |
| `ruff` / `mypy` / `eslint` | N/A | Not configured / not run | No standard lint command found |
| `pip install` / upgrades | **Not run** | Per audit rules | |
| Android Gradle assemble | **Not run** | Would need SDK/network; APKs already present | |
| Docker build | **Not run** | Avoid heavy/non-readonly side effects | |
| Production `uvicorn` load test | **Not run** | | |

---

## 20. Git Status and Recent Work

| Item | Value |
| ---- | ----- |
| Branch | `main` tracking `origin/main` |
| Working tree | Dirty: `.vscode/settings.json` modified only |
| Staged | None observed |
| Untracked | None from status snapshot (audit file created after) |

### Recent 15 commits

```
8755214 Bump APK to 1.4.4 with doposai.onrender.com as default API.
a97f5c8 Point APK default server URL at doposai.onrender.com.
df0f3c3 Fix cart column alignment on narrow/APK screens with explicit column widths.
d36daa0 Distinguish billing payment history headers from body text in classic theme.
79f927b Fix classic billing cards: dark backgrounds for readable white text.
04837b3 Make layby page text white in classic theme.
576e37a Make pending collection page text white in classic theme.
0c646fe Make classic the default POS theme with white heading and button text.
1ce39e2 Keep admin product search on one row with action buttons.
f1b3cb1 Keep admin product search on the same row as action buttons.
4079790 Fix admin Products title layout and add desktop product search.
d1b899d Show daily cash on hand in admin Summary Report.
a09c45e Prepare POS Mobile for Google Play Store release.
3aa4606 Harden offline APK sync so queued sales upload within 3 days.
8b7bb1a Require admin password confirmation before deleting a product.
```

**Latest commit:** APK 1.4.4 defaulting API to Render.  
**Unfinished-work theme:** UI polish + Play Store + offline sync hardening — core financial integrity still open.

---

## 21. TODOs and Incomplete Features

| Item | Path | Impact |
| ---- | ---- | ------ |
| Placeholder integrations | `app/integrations/placeholders.py` | Stub WhatsApp/remote AI interfaces (WhatsApp real impl exists separately) |
| Alembic baseline placeholder | `alembic/versions/0001_placeholder_baseline.py` | Migrations not authoritative |
| Quotation tax “later” | `quotation_service.py` | Tax incomplete |
| WhatsApp interface placeholder comment | `app/whatsapp/interfaces.py` | Docs drift |
| AI advisor fallback copy | `ai-service/.../advisor.py` | Soft failure messaging |
| Large historical docs claiming “not multi-tenant” | `EXISTING_POS_SYSTEM_ANALYSIS.md` | **Outdated** — system now has tenants |
| Hard-coded password reset script | `reset_morrison_password.py` | Security risk if retained |
| `repair-admin` / factory default credentials | `app/main.py` | Production blocker |
| Empty/`pass`-style catches | scattered | Some silent degradation (print/low-stock) |
| No dedicated categories API | — | Feature gap |
| Camera scanning | — | Missing |
| True DB backup/restore UX | — | Missing |

---

## 22. Error-Handling Review

| Pattern | Where | Risk |
| ------- | ----- | ---- |
| Broad `except Exception` | `main.py` many routes | Mask root cause; sometimes return 500 with message |
| Print failures logged only | `print_receipt_background` | OK (non-fatal) |
| Accounting failure rolls back sale | `create_sale` | Good |
| Offline flush leaves failed items | `offline-fetch.js` | Silent partial sync |
| Android permanent failed queue | `SyncPolicy.MAX_PUSH_ATTEMPTS` | Needs user-visible recovery |
| Empty catch in fetch patch | `offline-fetch.js` | Rare ignore |
| Import job errors stored in DB | `import_jobs.py` | Good pattern |
| Missing user notification on background print fail | — | Cashier may assume printed |

**Partial success examples:** Sale committed but receipt not printed; local sale saved but cloud push failed; PO receive vs accounting mismatch if one path errors after commit (review enterprise commits carefully).

---

## 23. Performance Review

| Issue | Evidence | Recommendation |
| ----- | -------- | -------------- |
| Load many products into browser memory | `app.js` product index | Paginate / search API for large catalogs |
| Android pull up to 20k products, page 500 | `SyncRepository` | Incremental sync |
| Full product table wipe/replace | `productDao.deleteAll()` | Upsert by id/version |
| Report loops all products in Python for stock value | `report_summary` | SQL aggregate with care for Numeric |
| `main.py` monolith size | 5k+ lines | Split routers/services |
| N+1 potential in some list serializers | scattered | Use joinedload |
| Notifications table growth | ~1500+ rows local | Retention job |
| WhatsApp messages growth | 2000+ | Archive |
| Missing composite indexes | e.g. `(tenant_id, created_at)` on sales | Add for reports |
| Large media in repo | `background.mov` ~54MB | Keep out of deploy context if unused |

---

## 24. Backup and Recovery Review

| Capability | Status |
| ---------- | ------ |
| Local DB backup | Manual file copy of `pos.db`; no first-class UI |
| Cloud backup | Google Sheets product sync (not full DB) |
| Automatic backup | Scheduler hooks exist around notifications/backup — Sheets oriented |
| Restore | Sheets import paths; factory reset destroys DB |
| Export | Product CSV, some enterprise CSV, statements PDF |
| Import | Inventory CSV/XLS jobs |
| Backup encryption | Not evident |
| Verification | Not evident |

### Failure scenarios

| Scenario | Likely outcome |
| -------- | -------------- |
| Power loss mid-sale | SQLite WAL helps; uncommitted sale lost; committed sale kept |
| DB corruption | App break; need file restore — procedure undocumented in-app |
| Internet fail during sync | Queue retains; 3-day pressure; possible permanent fail |
| Cloud down | Offline Android continues locally |
| Reinstall app | Local Room data lost unless backed up — **cloud pull won’t restore unsynced sales** |
| User deletes local data | Unsynced sales gone |

---

## 25. Deployment Readiness

| Area | Status |
| ---- | ------ |
| Prod config examples | `.env.example`, `.env.production.example`, `render.yaml` |
| Env requirements | `DATABASE_URL`, `JWT_SECRET_KEY`, Paynow, SMTP, WhatsApp, CORS, platform owners |
| Desktop packaging | Launcher scripts / `.desktop` — not a full installer |
| Web deploy | Docker + Render |
| DB deploy | Postgres on Render; SQLite local |
| Migrations | Weak Alembic story |
| Seed data | `init_db` interactive admin; `seed_products.py` |
| Logging | std logging + `server.log` artifact in repo |
| Error monitoring | No Sentry/etc. found |
| Updates | APK version bumps; server redeploy |
| Licensing | Billing subscriptions + offline grace |

### Readiness by stage

| Stage | Ready? | Why |
| ----- | ------ | --- |
| Local development | **Yes** | venv, SQLite, tests mostly green |
| Internal testing | **Yes, with caution** | Disable repair-admin; set secrets |
| Pilot | **Conditional** | After Critical security + price trust + stock lock |
| Limited production | **Not yet** | Tenant accounting isolation + sync hardening needed |
| Full production | **No** | Security, financial integrity, migration discipline, monitoring |

---

## 26. Critical Problems

1. **`POST /api/repair-admin` unauthenticated credential reset**  
2. **Default JWT secret fallback**  
3. **Client-trusted unit prices/discounts on `/api/sales`**  
4. **Race on stock decrement (no row lock)**  
5. **Dual inventory truth (product vs branch) on sales**  
6. **Global barcode uniqueness vs multi-tenant SaaS**  
7. **Accounting layer not tenant-scoped**  
8. **Offline sync can permanently drop sales / wipe local catalog**  
9. **Factory reset defaults and hard-coded password scripts**  
10. **XSS via `innerHTML` with untrusted names while JWT in localStorage**

---

## 27. Recommended Development Order

### Priority 0 — Data-loss, security, or financial-calculation risks

| Item | Why | Files | Deps | Size | Approach | Tests |
| ---- | --- | ----- | ---- | ---- | -------- | ----- |
| Remove/disable `repair-admin` in prod | Account takeover | `app/main.py` | env `APP_ENV` | Small | Gate or delete; emergency break-glass via CLI only | HTTP test 404/401 when prod |
| Require `JWT_SECRET_KEY` | Token forgery | `auth.py`, startup | config | Small | Refuse boot if default in production | Startup unit test |
| Server-side reprice sales | Fraud | `main.py` create_sale | permissions | Medium | Load product prices; allow override only with perm | Sale price spoof test |
| Lock stock rows | Oversell | `create_sale`, `inventory_ops.py` | DB | Medium | `SELECT … FOR UPDATE` / atomic update | Concurrent sale test |
| Fix XSS in POS JS | Token theft | `static/js/app.js` (+ admin.js) | — | Medium | textContent / escape | Basic DOM test or manual |
| Tenant-safe barcode unique | SaaS integrity | `models.py` + migration | Alembic | Medium | UniqueConstraint(tenant_id, barcode) | Multi-tenant insert test |

### Priority 1 — Essential POS functions

| Item | Why | Files | Deps | Size | Approach | Tests |
| ---- | --- | ----- | ---- | ---- | -------- | ----- |
| Payment bounds + change | Till accuracy | `main.py`, cart UI | P0 prices | Small | Reject overpay or return change field | Payment matrix tests |
| Sale↔refund report alignment | Trust numbers | reports in `main.py` | refunds | Medium | Net sales after approved refunds | Report fixtures |
| Explicit tax mode (or document VAT-in) | Legal clarity | models, UI, accounting | — | Large | Store setting tax_rate / inclusive flag | VAT fixtures |
| Harden factory-reset for Postgres | Don’t delete wrong store | `main.py` | — | Medium | Disable on non-SQLite | Guard test |

### Priority 2 — Inventory and business controls

| Item | Why | Files | Deps | Size | Approach | Tests |
| ---- | --- | ----- | ---- | ---- | -------- | ----- |
| Single stock apply API | Accuracy | `inventory_ops.py`, `create_sale`, refunds | P0 locks | Large | Always update product + branch together | Branch sale tests |
| Movement metadata | Audit | `InventoryMovement` | migration | Medium | Add tenant_id, branch_id, reference | — |
| Credit limits | Risk | customers, sale | — | Medium | Enforce max credit_balance | — |

### Priority 3 — Offline synchronization and reliability

| Item | Why | Files | Deps | Size | Approach | Tests |
| ---- | --- | ----- | ---- | ---- | -------- | ----- |
| Stop full product wipe | Data loss | `SyncRepository.kt` | — | Medium | Upsert incremental | Instrumented test |
| Dead-letter UI | Recover failed sales | Android UI + sync | — | Medium | Export/retry failed queue | — |
| Web queue idempotency | Dup sales | `offline-fetch.js`, app.js | client_sale_id | Medium | Always send UUID | — |

### Priority 4 — Reports and analytics

| Item | Why | Files | Deps | Size | Approach | Tests |
| ---- | --- | ----- | ---- | ---- | -------- | ----- |
| Fix expected profit definition | Misleading | `report_summary` | — | Small | Remove lifetime withdrawal subtract or redefine | Golden tests |
| Tenant-scoped accounting | SaaS | accounting_* | migration | Large | Add tenant_id to CoA/journals | Isolation tests |

### Priority 5 — Improvements and optional features

Camera scanning, label printing, batch/serial, Sentry, split `main.py`, stronger Alembic discipline, Playwright E2E.

---

## 28. First Implementation Phase

### Exact objective

**Close Critical security holes and establish trustworthy sale persistence (server prices + stock locking), with automated tests — without expanding features.**

### Problems to fix

1. Disable/remove unauthenticated `repair-admin` in production (and prefer complete removal).  
2. Fail startup when `JWT_SECRET_KEY` missing/insecure under `APP_ENV=production`.  
3. Recompute sale line prices from DB (optional admin override later).  
4. Atomic stock decrement with row lock / single SQL update guarding quantity.  
5. Escape POS `innerHTML` for names (minimum on cart/search).

### Files likely to change

- `app/main.py` (sale create, repair-admin)  
- `app/auth.py` / `app/startup_config.py` / `app/config.py`  
- `static/js/app.js`  
- New tests under `tests/test_sales_security.py` (name flexible)

### Database changes

- Possibly none for phase 1  
- Optional: prepare migration notes for later barcode unique constraint (can defer to phase 1b)

### API changes

- Sale API behavior: ignore spoofed prices (breaking for intentional client price edits — confirm product requirement)  
- `repair-admin` removed or 404 in production  

### UI changes

- Minimal — sanitize rendering; show error if server rejects price/stock  

### Tests required

- Unauthenticated repair-admin rejected  
- Sale with wrong unit_price stored at catalog price (or 400)  
- Concurrent insufficient stock only one succeeds  
- JWT boot failure without secret in prod mode  

### Acceptance criteria

- No public endpoint can reset admin password  
- Production process refuses weak JWT secret  
- Spoofed sale prices cannot reduce amount charged  
- Stock never goes negative under parallel requests in test  
- Existing 65 tests still pass; platform-owner tests fixed or isolated  

### Risks

- Breaking clients that relied on ad-hoc price overrides  
- Lock contention on busy SQLite  
- Repair-admin was used as recovery — replace with documented CLI

### Validation commands

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m compileall -q app tests
# manual: attempt POST /api/repair-admin without auth → expect failure in prod mode
```

**Do not implement this phase until the project owner approves.**

---

## 29. Files Needed for External Review

Share at most these (~30) — **exclude** `.env`, keystores, `backup_config.json` if it contains live webhook URLs, and `pos.db` if it has real customer data:

1. `requirements.txt`  
2. `app/config.py`  
3. `app/database.py`  
4. `app/models.py`  
5. `app/auth.py`  
6. `app/permissions.py`  
7. `app/tenant_scope.py`  
8. `app/main.py` (sales + repair-admin sections especially)  
9. `app/refund_service.py`  
10. `app/enterprise/inventory_ops.py`  
11. `app/enterprise_models.py`  
12. `app/enterprise/routes.py`  
13. `app/accounting_engine.py`  
14. `app/accounting_models.py`  
15. `app/billing/middleware.py` / `app/billing/features.py`  
16. `app/saas_auth_routes.py`  
17. `app/platform_routes.py`  
18. `app/product_barcodes.py`  
19. `app/escpos_printer.py`  
20. `app/backup_service.py` (redact secrets)  
21. `static/js/app.js`  
22. `static/js/offline-fetch.js`  
23. `android-app/app/src/main/java/com/pos/mobile/data/sync/SyncRepository.kt`  
24. `android-app/app/src/main/java/com/pos/mobile/sync/SyncPolicy.kt`  
25. `android-app/app/src/main/java/com/pos/mobile/ui/CartMath.kt`  
26. `android-app/app/src/main/java/com/pos/mobile/ui/PosViewModel.kt`  
27. `tests/test_platform_owner_gate.py`  
28. `tests/test_permissions.py`  
29. `tests/test_refunds.py`  
30. `docker-compose.yml` + `.env.example` (names only; no real secrets)

Optional addendum: this file `POS_PROJECT_AUDIT.md`.

---

## 30. Commands Run

| Command | Purpose | Outcome |
| ------- | ------- | ------- |
| `find` / `ls` project trees | Structure | OK |
| `.venv/bin/python` SQLAlchemy inspect + counts | Schema | OK (48 tables) |
| `git status -sb`; `git log -15 --oneline`; `git diff --stat` | Git state | OK; dirty `.vscode/settings.json` |
| `.venv/bin/python -m pytest tests/ -q` | Tests | **Exit 1** — 65 passed, 4 failed |
| `.venv/bin/python -m pytest tests/test_platform_owner_gate.py` | Isolate failures | **9 passed** |
| `.venv/bin/python -m compileall -q app tests` | Syntax | Exit 0 |
| `from app.main import app` | Import/smoke | OK (~195 routes) |
| Greps for TODO/security/sale/tax/barcode | Static review | OK |
| Read package/config/model/source files | Architecture | OK |

### Commands not run

- Package installs/upgrades  
- Alembic migrations / DB alterations  
- Docker image build  
- Android Gradle release build  
- `pip audit` / npm audit  
- Live Paynow/WhatsApp/Firestore integration calls  
- Destruction of `pos.db` or factory reset  

### Could not fully determine

- Whether cloud Render deployment currently has `repair-admin` reachable publicly  
- Exact production env var values (intentionally unread beyond key names)  
- Full Android UI parity vs web for every enterprise screen  
- Whether all enterprise routes are plan-gated consistently  
- Historical accuracy of older markdown status docs vs code  
- Real thermal printer behavior on this host (no device exercised)  
- Precise root cause ordering of platform-owner test pollution beyond import/env interaction  

---

*End of audit. No application fixes were implemented.*
