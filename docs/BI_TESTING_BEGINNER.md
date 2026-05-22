# Deploy DoposAI BI for testing (beginner guide)

Two paths:

- **Path A (15 minutes)** — Test on your live site **without** a GPU server. You get health scores + basic advisor text from your real sales data.
- **Path B (1–2 hours)** — Add **Contabo VPS + Qwen3** for full AI answers.

---

## Path A — Test BI on Render only (no VPS yet)

### Step 1: Put the BI code on GitHub

On your Pi (or PC), in the project folder:

```bash
cd /home/morrison/Desktop/pos
git add app/bi ai-service static/js/bi-advisor.js templates/analytics.html app/main.py app/config.py docs/
git status
git commit -m "feat(bi): DoposAI Business Intelligence engine phase 1"
git push origin main
```

Wait for **Render** to finish deploying (Dashboard → your web service → Events).

### Step 2: Log in to your POS

1. Open your site (e.g. `https://doposai.com` or your Render URL).
2. Log in as an **admin** on a store that has some sales/products.
3. You need **Pro** or **trial** (trial includes AI features).

### Step 3: Open Analytics

1. Go to **Admin** → open **Analytics** (or go directly to `/analytics`).
2. You should see a new section: **DoposAI Business Advisor** with four colored score cards.
3. If you see “BI unavailable”, check you’re logged in and the deploy finished.

### Step 4: Try the buttons

| Button | What it does |
|--------|----------------|
| **Full insights** | Business summary (rule-based until AI is connected) |
| **Sales analysis** | Sales-focused advice |
| **Inventory** | Stock / restock hints |
| **Ask advisor** | Type a question, e.g. “What should I restock?” |

Without `AI_SERVICE_URL` set, text will say something like “Connect AI_SERVICE_URL for full Qwen3 analysis” — that is **normal** for Path A.

### Step 5: Quick API check (optional)

While logged in, browser DevTools → Network, or use curl with your JWT:

```bash
# Replace TOKEN with value from localStorage key pos_token in browser
curl -s -H "Authorization: Bearer TOKEN" "https://YOUR-SITE/api/bi/status"
```

Expected: `"ai_service_configured": false` until Path B.

**Path A success =** health scores load + advisor buttons return JSON/text without 502 errors.

---

## Path B — Full AI (Contabo VPS + vLLM + Qwen3)

### What you need

| Item | Why |
|------|-----|
| Contabo VPS (Ubuntu 24.04) | Runs Docker |
| NVIDIA GPU (e.g. RTX 3060 12GB+) | Qwen3-8B needs GPU VRAM |
| SSH access | You install software remotely |
| Hugging Face account (optional) | Some models need `HF_TOKEN` |

**Raspberry Pi is not suitable** for Qwen3-8B inference — use Contabo (or a PC with NVIDIA GPU).

### Step 1: Install Docker on the VPS

SSH into the VPS:

```bash
ssh root@YOUR_VPS_IP
```

Install Docker (Ubuntu 24.04):

```bash
apt update && apt install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### Step 2: Install NVIDIA drivers + container toolkit (GPU VPS only)

```bash
# Driver install varies by Contabo image — follow Contabo GPU docs if provided
nvidia-smi   # must show your GPU

# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt update && apt install -y nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### Step 3: Copy the AI service to the VPS

On your **local machine** (Pi), copy the folder:

```bash
scp -r /home/morrison/Desktop/pos/ai-service root@YOUR_VPS_IP:/opt/doposai-ai
```

Or clone the repo on the VPS:

```bash
cd /opt
git clone YOUR_REPO_URL pos
cd pos/ai-service
```

### Step 4: Create secrets

```bash
cd /opt/doposai-ai   # or .../pos/ai-service
cp .env.example .env
nano .env
```

Set at minimum:

```env
AI_SERVICE_API_KEY=pick-a-long-random-password-here-32chars
VLLM_MODEL=Qwen/Qwen3-8B
HF_TOKEN=hf_xxxx   # only if Hugging Face asks for it when downloading
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano).

Generate a random key:

```bash
openssl rand -hex 32
```

### Step 5: Start the stack

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f vllm
```

**First start takes 10–40 minutes** — vLLM downloads the model. Wait until logs show the server is ready.

Check health:

```bash
curl http://127.0.0.1:8080/ai/health
```

### Step 6: Open port 8080 for Render only

```bash
ufw allow OpenSSH
ufw allow 8080/tcp
ufw enable
```

Better: restrict `8080` to Render’s outbound IPs in Contabo firewall if you know them.

Test from your laptop (replace IP and key):

```bash
curl -H "X-API-Key: YOUR_AI_SERVICE_API_KEY" http://YOUR_VPS_IP:8080/ai/health
```

### Step 7: Connect Render to the VPS

1. Render Dashboard → your **Web Service** → **Environment**.
2. Add:

| Key | Value |
|-----|--------|
| `AI_SERVICE_URL` | `http://YOUR_VPS_IP:8080` (or `https://ai.yourdomain.com` if you add nginx + SSL) |
| `AI_SERVICE_API_KEY` | **Same** string as in VPS `.env` |

3. **Save** → Render redeploys automatically.

### Step 8: Test full AI from the website

1. Open `/analytics` again.
2. Status line should say **“Qwen3 advisor connected”**.
3. Click **Ask advisor** → “Why did revenue change this month?”
4. First answer may take **30–90 seconds**; later ones are faster (cache).

### Step 9: Troubleshooting

| Problem | Fix |
|---------|-----|
| `ai_service_configured: false` on site | Check Render env vars, redeploy, no typo in API key |
| Connection refused | VPS firewall, `docker compose ps`, port 8080 |
| vLLM keeps restarting | GPU memory too small — try smaller model in `.env` |
| Very slow | Normal on first request; use smaller model for tests |
| 401 from AI service | API keys on Render and VPS must match exactly |

CPU-only VPS (no GPU): use `docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d` — slow, for wiring tests only.

---

## Checklist

**Path A**
- [ ] Code pushed to `main`, Render deployed
- [ ] Logged in as admin (trial/Pro)
- [ ] `/analytics` shows health score cards
- [ ] Advisor buttons return a response

**Path B**
- [ ] VPS + Docker + (GPU) working
- [ ] `docker compose up` healthy
- [ ] `curl` to `:8080/ai/health` works
- [ ] Render `AI_SERVICE_URL` + `AI_SERVICE_API_KEY` set
- [ ] Site shows “Qwen3 advisor connected”
- [ ] Ask advisor returns a detailed AI answer
