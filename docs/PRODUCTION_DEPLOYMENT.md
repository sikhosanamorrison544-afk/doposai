# Production deployment on Render (DoPosAI)

This runbook describes how the multi-tenant offline-first POS stack is prepared for production: **API** at `https://api.doposai.com`, **web** at `https://doposai.com`, **PostgreSQL** on Render, optional **Firestore** for subscription/device security, and **Android** builds pointing at the production API.

## Architecture (current)

| Layer | Role |
|--------|------|
| **Render Web Service** (`doposai-api`) | FastAPI: REST API, JWT auth, sync endpoints, tenant middleware, Jinja web POS served from the same process today |
| **Render PostgreSQL** | Tenants, users, products, orders, subscriptions (transactional source of truth) |
| **Firebase Firestore** (optional) | Trial/subscription mirrors, device binding, billing audit events; enforced in app when credentials are set |
| **Android APK** | Offline SQLite, sync queue, `BuildConfig` API base URL default `https://api.doposai.com` |
| **Future** | Remote AI (e.g. Ollama on Hetzner) via `app/integrations/placeholders.py`; WhatsApp via same module — not implemented |

**Single service vs split:** You can attach **both** custom domains (`doposai.com`, `api.doposai.com`) to the same Render web service and set `CORS_ALLOW_ORIGINS` accordingly. Later, move the marketing or static web POS to a **Render Static Site** and keep only `api.doposai.com` on the API service.

## Repository layout (deployment-related)

```
Dockerfile                 # API container image
docker-compose.yml         # Local: API + Postgres
.dockerignore
render.yaml                # Render Blueprint (web + Postgres)
scripts/render_start.sh    # Migrations + uvicorn (Render start command)
.env.production.example    # Env template (copy to .env for compose)
alembic/                   # Migrations (DATABASE_URL)
app/config.py              # APP_ENV, URLs, CORS, trial/grace defaults
app/billing/               # Payment abstraction + stub routes
app/integrations/          # Future WhatsApp / remote AI placeholders
app/firestore_service.py   # Optional Firestore writes/reads
docs/PRODUCTION_DEPLOYMENT.md
```

## Render: create from Blueprint

1. Push this repo to GitHub/GitLab (with `render.yaml` on the default branch).
2. Render → **New** → **Blueprint** → select the repo.
3. Confirm resources: **Web** `doposai-api` + **PostgreSQL** `doposai-postgres`.
4. After first deploy, open the web service → **Environment** and set any missing secrets (see below).
5. **Custom domains:** add `api.doposai.com` and (if same service) `doposai.com` / `www.doposai.com`. Render shows **CNAME** targets (usually `xxx.onrender.com`). Create DNS records at your registrar:

   | Host | Type | Value |
   |------|------|--------|
   | `api` | CNAME | *(value from Render)* |
   | `@` or `www` | CNAME | *(same or separate service)* |

6. Wait for **SSL** provisioning (automatic once DNS propagates).

**Plans:** `render.yaml` uses `plan: free` for the web service and `basic-256mb` for Postgres. Adjust in the dashboard or YAML to match your Render catalog and SLA needs.

## Environment variables (Render + Docker)

Copy from `.env.production.example`. Critical keys:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Render injects from managed Postgres (`fromDatabase` in blueprint) |
| `JWT_SECRET_KEY` | Strong random secret (blueprint can `generateValue: true`) |
| `APP_ENV` | `production` |
| `WEB_PUBLIC_URL` | `https://doposai.com` |
| `API_PUBLIC_URL` | `https://api.doposai.com` |
| `CORS_ALLOW_ORIGINS` | Comma-separated browser origins (must include your web origin; avoid `*` if you need cookies) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to JSON in container **or** use Render secret file mount |
| `FIREBASE_PROJECT_ID` | Helps default app init when not using a file path |
| `BILLING_WEBHOOK_SECRET` | Future Paynow/EcoCash webhook HMAC |
| `TRIAL_DAYS` / `OFFLINE_GRACE_HOURS` | Policy defaults (see `app/config.py`) |

**Firestore on Render:** Prefer a **secret file** containing the service account JSON and set `GOOGLE_APPLICATION_CREDENTIALS` to that path, or use workload identity if you move to GCP Run later.

## Start command and migrations

- **Native Python on Render:** `startCommand: sh scripts/render_start.sh` (runs `alembic upgrade head` when `DATABASE_URL` is PostgreSQL, then `uvicorn`).
- **Docker image:** `Dockerfile` copies `scripts/`; override start command to the same script if you want parity.

## PostgreSQL

- **Connection:** Use Render’s **internal** URL for the API service in the same region; use **external** only for admin tools.
- **Pooling:** For high concurrency, add PgBouncer (Render supports connection pooling on some plans) or SQLAlchemy pool settings in your DB session module.
- **Migrations:** `alembic upgrade head` on deploy. Add real revisions under `alembic/versions/` as you evolve schema; baseline placeholder exists.
- **Tenant safety:** Keep `tenant_id` (or equivalent) on all tenant-scoped rows; enforce in middleware and every query.

## Web frontend

- Production API base: **`https://api.doposai.com`** (set in web build env if you split static site).
- Ensure auth tokens are stored appropriately for your model (localStorage vs httpOnly cookies); CORS must allow the web origin.
- Offline: service worker / cache strategy is frontend-specific; API should support **idempotent sync** and **pagination** for low bandwidth.

## Android APK

- Default release/debug base URL is configured in `android-app/app/build.gradle.kts` (`DEFAULT_API_BASE_URL` → `https://api.doposai.com/`). Override with `pos.api.base.url` in `local.properties` for staging.
- **Security:** Use EncryptedSharedPreferences or Keystore for tokens; never store raw passwords. Queue mutations locally; retry sync with backoff when online.

## Firestore collections (intended use)

| Collection | Use |
|------------|-----|
| `devices` | Install IDs, last seen tenant, reinstall signals |
| `subscriptions` | Plan, status, renewal (mirror of billing provider) |
| `billing_events` | Immutable webhook / payment audit (`append_billing_event`) |
| `tenant_security` | Risk flags, trial abuse counters (optional split from `tenants`) |
| `tenants` | Current code paths merge subscription/security docs here (`upsert_tenant_security_record`) |

You may migrate writes from `tenants` to `tenant_security` + `subscriptions` as policies harden.

## API surface (high level)

- Auth and SaaS routes under existing routers (paths vary: some clients use `/auth/...` without `/api` prefix — verify Android/web clients).
- Billing stubs: `/api/billing/health`, `/api/billing/webhook/payment` (implement signature verification before production traffic).
- Rate limiting: in-memory limiter in `app/http_rate_limit.py` (replace with Redis for multi-instance).

## Offline-first policy (product)

- Target **~72h offline grace** via `OFFLINE_GRACE_HOURS` (default in config); **14-day trial** via `TRIAL_DAYS`.
- Writes **local-first**; sync queue persisted; background sync when connectivity returns; **JWT refresh** when online.
- **Subscription cache** on device with TTL; reject sensitive server actions when expired beyond grace (enforce in API + Firestore).

## Scaling recommendations

- Move to **multiple instances** only after **shared rate limit** (Redis) and **idempotent sync**.
- Split **read replicas** or reporting DB when analytics grows.
- Static **CDN** for web assets; **GZip** already enabled on API.
- **Future AI:** point `OLLAMA_BASE_URL` at Hetzner; keep inference off the request hot path (queue/async).
- **Future WhatsApp:** implement `integrations/placeholders.py` with a dedicated worker service or Render background worker.

## Smoke test after deploy

1. `GET https://api.doposai.com/` (health or root).
2. `GET https://api.doposai.com/api/billing/health` (stub).
3. Login / token flow from web and APK against production.
4. Create test tenant + order; verify sync from offline queue.

## DNS checklist

- [ ] CNAME `api.doposai.com` → Render target  
- [ ] CNAME apex/`www` → Render or redirect to canonical `https://doposai.com`  
- [ ] SSL active in Render for both custom domains  
- [ ] `CORS_ALLOW_ORIGINS` includes every browser origin that calls the API  

This document is the single source of truth for production cutover; adjust plans and URLs if you add a separate static site or microservices.
