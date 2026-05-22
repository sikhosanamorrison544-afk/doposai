# DoposAI Business Intelligence Engine — Phase 1

## Components

| Layer | Location | Role |
|-------|----------|------|
| Analytics engine | `app/bi/analytics/` | PostgreSQL aggregates, tenant-scoped |
| Forecasting | `app/bi/forecasting.py` | Linear trend, stockout, reorder (no LLM) |
| Health scores | `app/bi/scores.py` | Green / yellow / red dashboard widgets |
| Render API | `app/bi/routes.py` | `/api/bi/*` for POS clients |
| AI microservice | `ai-service/` | vLLM + Qwen3 on Contabo |
| RAG (future) | `ai-service/app/rag/interfaces.py` | Stubs only |

## Data flow

1. Authenticated user calls `/api/bi/...` on Render.
2. `build_tenant_analytics_summary()` runs SQL summaries (no raw export).
3. Optional `build_forecasts()` adds statistical projections.
4. Render POSTs summary JSON to Contabo `/ai/...` with `X-API-Key`.
5. Qwen3 returns structured JSON (summary, insights, risks, recommendations, action_plan).
6. Response cached (Redis on Contabo, optional Redis on Render).

## Security

- All SQL uses `tenant_scope` filters.
- AI service never connects to Postgres in Phase 1.
- `tenant_id` in AI payload is for logging/cache keys only; data is pre-filtered on Render.

## Environment

**Render:** `AI_SERVICE_URL`, `AI_SERVICE_API_KEY`, `BI_CACHE_TTL_SECONDS`, `BI_REDIS_URL` (optional)

**Contabo:** see `ai-service/.env.example` and `docs/BI_CONTABO_DEPLOY.md`
