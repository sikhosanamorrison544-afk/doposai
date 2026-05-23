# Real vLLM + Qwen3 on Contabo (step-by-step)

Connect your live POS on Render to a GPU VPS running **vLLM** and **Qwen3** (no Ollama).

```
Web/Android POS  →  Render (analytics)  →  Contabo :8080 (ai-api)  →  vLLM  →  Qwen3 AWQ
```

---

## Important: there is no official “Qwen3-18B”

Alibaba’s **Qwen3** line on Hugging Face is: **0.6B, 1.7B, 4B, 8B, 14B, 32B**, plus MoE variants — **not 18B**.

| What you want | Official model to use | Typical GPU |
|---------------|----------------------|-------------|
| ~18B class (best quality per GB) | **`Qwen/Qwen3-14B-AWQ`** | 16–24 GB |
| Maximum Qwen3 quality | **`Qwen/Qwen3-32B-AWQ`** | 24 GB+ (tight on 24 GB) |
| Lighter / testing | **`Qwen/Qwen3-8B-AWQ`** | 12 GB+ |

This guide defaults to **Qwen3-14B-AWQ** as the practical “large” model.

---

## 1. What you need

| Item | Notes |
|------|--------|
| Contabo **GPU VPS** (Ubuntu 24.04) | e.g. NVIDIA with 16–24 GB VRAM |
| SSH as `root` | `ssh root@YOUR_VPS_IP` |
| Hugging Face account | Optional; some models need `HF_TOKEN` |
| Render dashboard access | To set `AI_SERVICE_URL` + `AI_SERVICE_API_KEY` |

---

## 2. One-time VPS setup

SSH in, then run (or follow manually):

```bash
apt update && apt install -y git curl
# Docker — see BI_TESTING_BEGINNER.md for full Docker install
# NVIDIA driver: nvidia-smi must work
# NVIDIA Container Toolkit — docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

Copy the AI service to the VPS:

```bash
mkdir -p /opt/doposai
cd /opt/doposai
# Option A: git clone your repo
# Option B: from your PC:
#   scp -r /path/to/pos/ai-service root@YOUR_VPS_IP:/opt/doposai/ai-service
```

---

## 3. Configure secrets

```bash
cd /opt/doposai/ai-service
cp .env.example .env
nano .env
```

Generate a strong API key (use the **same** value on Render later):

```bash
openssl rand -hex 32
```

Example `.env` for **Qwen3-14B AWQ** (~15B class):

```env
AI_SERVICE_API_KEY=paste-openssl-output-here

VLLM_MODEL=Qwen/Qwen3-14B-AWQ
VLLM_SERVED_NAME=qwen3-14b
VLLM_MAX_MODEL_LEN=8192
VLLM_GPU_UTIL=0.92

HF_TOKEN=hf_xxxx
AI_CACHE_TTL_SECONDS=1800
AI_MAX_TOKENS=2048
AI_TEMPERATURE=0.3
```

---

## 4. Start vLLM + AI API

**14B (recommended for “large” Qwen3):**

```bash
docker compose -f docker-compose.yml -f docker-compose.qwen3-14b.yml up -d --build
```

**8B (smaller GPU):**

```bash
docker compose up -d --build
```

**32B (24 GB+ only):**

```bash
docker compose -f docker-compose.yml -f docker-compose.qwen3-32b.yml up -d --build
```

Watch the model download (first boot **20–60+ minutes**):

```bash
docker compose logs -f vllm
```

Wait until you see the server ready (no crash loop). Then:

```bash
curl -s http://127.0.0.1:8080/ai/health | python3 -m json.tool
```

Expected when ready:

```json
{
  "status": "ok",
  "vllm_ready": true,
  "vllm_model": "qwen3-14b"
}
```

If `vllm_ready` is `false`, keep waiting or check `docker compose logs vllm` for OOM — lower `VLLM_MAX_MODEL_LEN` or use 8B.

Test with API key:

```bash
export KEY="your-AI_SERVICE_API_KEY"
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8080/ai/health
```

---

## 5. Firewall (only port 8080 public)

```bash
ufw allow OpenSSH
ufw allow 8080/tcp
ufw enable
```

Do **not** expose port `8000` (vLLM) to the internet.

---

## 6. Connect Render

Render → **Web Service** → **Environment**:

| Variable | Value |
|----------|--------|
| `AI_SERVICE_URL` | `http://YOUR_VPS_IP:8080` (or `https://ai.yourdomain.com` behind nginx) |
| `AI_SERVICE_API_KEY` | **Exact same** string as Contabo `.env` |
| `AI_SERVICE_TIMEOUT_SEC` | `90` (14B/32B first answer can be slow) |
| `AI_SERVICE_CONNECT_TIMEOUT_SEC` | `10` |

Save → wait for Render redeploy.

---

## 7. Verify from the website

1. Open **Analytics** (`/analytics`).
2. Status under **DoposAI Business Advisor** should say **“Qwen3 advisor connected”**.
3. Click **Ask advisor** → e.g. “What should I restock this week?”
4. First reply may take **30–120 seconds**; later ones use Redis cache and are faster.

Browser check (logged in, copy `pos_token`):

```bash
curl -s -H "Authorization: Bearer YOUR_JWT" "https://YOUR-SITE/api/bi/status"
```

Expect: `"ai_service_configured": true`

---

## 8. Troubleshooting

| Problem | Fix |
|---------|-----|
| `vllm` container restarting | GPU OOM → use `Qwen3-8B-AWQ` or lower `VLLM_MAX_MODEL_LEN` / `VLLM_GPU_UTIL` |
| `vllm_ready: false` for a long time | Model still downloading; `docker compose logs -f vllm` |
| Render “BI unavailable” / timeout | Increase `AI_SERVICE_TIMEOUT_SEC`; check firewall :8080 |
| 401 from Contabo | `AI_SERVICE_API_KEY` mismatch between Render and VPS |
| Advisor still rule-based | `AI_SERVICE_URL` empty or wrong on Render |
| CUDA / GPU not found | Install NVIDIA driver + `nvidia-container-toolkit`, restart Docker |

---

## 9. Optional: HTTPS on Contabo

Point `ai.yourdomain.com` to the VPS IP, install nginx + Let’s Encrypt, proxy to `127.0.0.1:8080`, then set:

`AI_SERVICE_URL=https://ai.yourdomain.com`

---

## 10. Files reference

| File | Purpose |
|------|---------|
| `ai-service/docker-compose.yml` | Base stack (redis, vllm, ai-api) |
| `ai-service/docker-compose.qwen3-14b.yml` | 14B AWQ tuning |
| `ai-service/docker-compose.qwen3-32b.yml` | 32B AWQ tuning |
| `ai-service/.env.example` | Template |
| `docs/BI_CONTABO_DEPLOY.md` | Architecture + security |
