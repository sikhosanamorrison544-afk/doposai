# Enterprise POS Architecture

Multi-tenant, offline-first extensions for suppliers, purchasing, branches, audit, and future WhatsApp integration.

## Database (PostgreSQL + SQLite)

| Table | Purpose |
|-------|---------|
| `branches` | Tenant branch hierarchy |
| `branch_product_stock` | Per-branch inventory |
| `suppliers` | Supplier master data |
| `supplier_ledger_entries` | Supplier balance / purchase history |
| `purchase_orders` | PO header |
| `purchase_order_items` | PO lines |
| `stock_adjustments` | Damage, expiry, theft, corrections |
| `stock_transfers` | Inter-branch transfers |
| `stock_transfer_items` | Transfer lines |
| `audit_logs` | Enterprise audit trail |
| `whatsapp_integrations` | Future WhatsApp config (no API yet) |

Optional columns (migration): `users.branch_id`, `sales.branch_id`, `cashier_shifts.branch_id`.

**Migrate:** `python3 migrate_enterprise.py` then deploy. Render PostgreSQL: `create_all` + optional `ALTER` in script.

## API (`/api/enterprise`)

- **Suppliers:** CRUD, search, ledger, statements
- **Purchase orders:** create, send, approve, receive (partial/full), PDF, cancel
- **Adjustments:** create, approve/reject workflow
- **Transfers:** create, send, receive, cancel
- **Branches:** list, create, branch stock
- **Audit:** search, CSV export
- **Reorder:** rule-based suggestions (no AI)
- **Customer statements:** JSON + PDF
- **Dashboards:** `/dashboards/summary`
- **Branch reports:** sales, inventory
- **Offline:** `/offline-bundle` for Android master sync
- **WhatsApp:** `/whatsapp/integrations` (list only; stub provider)

## Permissions

| Role | Access |
|------|--------|
| admin (owner) | Full enterprise |
| supervisor | Inventory, suppliers, PO, receive; no audit/users |
| cashier | Sales + view inventory only |

See `app/permissions.py`.

## Workflow

```
Supplier → Purchase Order → Receive Goods → inventory_movements + product.stock_qty
         → supplier_ledger (on full receive)
```

Stock adjustments require approval unless user has `approve_adjustments` (admin).

## Offline-first

1. **Server:** `GET /api/enterprise/offline-bundle` caches suppliers, branches, open POs.
2. **Android:** `MasterSyncEndpoints` includes enterprise paths; extend Room entities in a follow-up PR for 3+ day offline writes.
3. **Sync queue:** Existing `sync_queue` for sales; enterprise writes should queue similarly (Phase 2).

## WhatsApp (prepared, not implemented)

- Table: `whatsapp_integrations`
- Interfaces: `app/whatsapp/interfaces.py` (`StubWhatsappProvider`)
- Future: quotations, statements, receipts, payment reminders per tenant/branch number

## UI

- Web: `/enterprise` (`templates/enterprise.html`, `static/js/enterprise.js`)
- Link from Admin (add shortcut as needed)

## Testing plan

1. Run `python3 migrate_enterprise.py`
2. Admin login → `/enterprise` → create supplier, list, edit
3. Create draft PO → send → approve → receive → verify product stock
4. Create adjustment as supervisor (pending) → approve as admin
5. Create branch → transfer draft → send → receive
6. Audit log after each action; export CSV
7. Reorder suggestions with sales history
8. Customer statement PDF
9. Android: login sync includes `/api/enterprise/offline-bundle`

## Render deployment

- No new env vars required
- Run migration on release (one-off job or startup hook)
- `Base.metadata.create_all` on boot creates new tables if missing
- Health check unchanged: `/health`

## Phase 2 (implemented)

- **Android Room:** `suppliers`, `branches`, `enterprise_cache` tables (DB v4); `pullEnterpriseData()` on master sync
- **PO UI:** `/enterprise` — create/edit draft PO, send, approve, receive all, PDF
- **Accounting:** `AccountingEngine.post_purchase_receive()` — Dr Inventory / Cr AP on each receive
- **Branch scope:** `sales.branch_id`, `cashier_shifts.branch_id`, `users.branch_id`; cashiers filtered to assigned branch
- **User admin:** assign `branch_id` when creating/updating users

## Phase 3 (implemented)

- **Partial PO receive:** per-line qty inputs + “Receive selected” / “Receive all remaining” on PO detail
- **Offline POST bodies:** `static/js/offline-fetch.js` patches `fetch()`; Android `PosAndroidOffline` bridge queues full body to Room; sync replays POST/PUT/PATCH/DELETE
- **Email statements:** `POST /api/enterprise/customers/{id}/statement/email` with PDF attachment (requires SMTP env vars)
- **Statements tab** on `/enterprise` — load, PDF, email

### SMTP (Render)

Set: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`
