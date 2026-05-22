# DoposAI Business Intelligence — Contabo VPS Deployment

## Architecture

```
Android / Web POS  →  Render (FastAPI + PostgreSQL analytics)  →  Contabo AI API  →  vLLM  →  Qwen3
```

- **Render**: `app/bi/` aggregates tenant data; never sends raw rows to AI.
- **Contabo**: `ai-service/` runs FastAPI + Redis + vLLM (no Ollama).

## 1. VPS requirements (Ubuntu 24.04)

- NVIDIA GPU recommended (Qwen3-8B)
- Docker Engine + Docker Compose v2
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- Open firewall: **8080** (AI API) from Render IPs only; do not expose vLLM :8000 publicly

## 2. Deploy AI stack

```bash
cd ai-service
cp .env.example .env
# Edit AI_SERVICE_API_KEY and HF_TOKEN if needed
docker compose up -d --build
```

Verify:

```bash
curl http://127.0.0.1:8080/ai/health
curl -H "X-API-Key: YOUR_KEY" http://127.0.0.1:8080/ai/health
```

vLLM first boot downloads the model (10–30+ minutes).

## 3. Configure Render backend

Set environment variables on the Render web service:

| Variable | Example |
|----------|---------|
| `AI_SERVICE_URL` | `https://ai.yourdomain.com` or `http://VPS_IP:8080` |
| `AI_SERVICE_API_KEY` | Same as Contabo `.env` |
| `BI_CACHE_TTL_SECONDS` | `1800` |
| `BI_REDIS_URL` | Optional Render Redis URL |

Redeploy Render after saving.

## 4. API usage (from POS)

All routes require JWT + **Pro / trial** (`AI_ASSISTANT` feature):

| Method | Path |
|--------|------|
| GET | `/api/bi/status` |
| GET | `/api/bi/health-scores` |
| POST | `/api/bi/business-insights?days=30` |
| POST | `/api/bi/sales-analysis?days=30` |
| POST | `/api/bi/inventory-analysis?days=30` |
| POST | `/api/bi/profit-analysis?days=30` |
| POST | `/api/bi/forecast?days=30` |
| POST | `/api/bi/ask` body: `{"question": "...", "days": 30}` |

## 5. Security

- Rotate `AI_SERVICE_API_KEY` regularly
- Restrict Contabo :8080 to Render egress IPs (UFW / cloud firewall)
- Every analytics query on Render is filtered by `tenant_scope` before summarization
- AI service only receives aggregated JSON + `tenant_id` — no cross-tenant DB access

## 6. Caching

- **Contabo Redis**: AI narrative responses (15–60 min, `AI_CACHE_TTL_SECONDS`)
- **Render**: optional `BI_REDIS_URL` for health scores and advisor payloads

## 7. Future RAG (Phase 2)

Interfaces in `ai-service/app/rag/interfaces.py` for Qdrant, embeddings, and tenant memory — not enabled in Phase 1.

## 8. Troubleshooting

| Issue | Action |
|-------|--------|
| 502 from Render | Check `AI_SERVICE_URL`, VPS firewall, vLLM health |
| Fallback text only | `AI_SERVICE_URL` / key missing — rule-based advisor used |
| vLLM OOM | Use smaller quant model or `Qwen/Qwen2.5-7B-Instruct` |
| Slow first response | Model load + cold GPU; cache repeats |

## 9. CPU-only fallback

Remove GPU `deploy` block in `docker-compose.yml` and use a smaller model; expect slower inference.
