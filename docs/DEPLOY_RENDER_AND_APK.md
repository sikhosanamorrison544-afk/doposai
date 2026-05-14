# Deploy POS backend on Render (GitHub) + test APK

Public web app URL: **`https://doposai.com/`** (and API for the Android app at the same origin unless you split them).

---

## 1. Push the repo to GitHub

From the machine that has the project:

```bash
cd /path/to/pos
git status   # ensure changes are committed
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git   # skip if already added
git branch -M main
git push -u origin main
```

---

## 2. Create the service on Render

1. Open [Render](https://render.com) and connect **GitHub**.
2. **Blueprint (recommended):** **New** → **Blueprint** → select this repository → Render reads **`render.yaml`** at the repo root.  
   **Or Web Service:** **New** → **Web Service** → same repo, then set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. In the service **Environment**, keep or set:
   - **`JWT_SECRET_KEY`** – long random secret (Render can generate one in the blueprint).
   - **`DATABASE_URL`** – blueprint default is `sqlite:////tmp/pos.db` (fine for smoke tests; data is lost on restarts). For production, add **Render PostgreSQL** and set `DATABASE_URL` to the **Internal** URL.

First deploy gives you a URL like `https://pos-backend.onrender.com`.

---

## 3. Point **doposai.com** at Render (web + API)

1. In Render: open your **Web Service** → **Settings** → **Custom Domains** → add **`doposai.com`** and **`www.doposai.com`** if you use it.
2. At your DNS host (Cloudflare, registrar, etc.), add the **CNAME** / records Render shows (usually CNAME `doposai.com` → `your-service.onrender.com` or the target they provide).
3. Wait for TLS to provision. Then the **web UI** and **API** are both at **`https://doposai.com/`** (FastAPI serves HTML and `/api/...` on the same host).

**Cold starts (free tier):** the service may sleep; the first request after idle can take ~30–60s.

---

## 4. Android test APK (uses doposai.com)

The app is built to use **`https://doposai.com/`** by default (`BuildConfig.DEFAULT_API_BASE_URL`).  
`PosApplication` keeps SharedPreferences `base_url` aligned with that build default, so installs track doposai after you deploy DNS.

**Do not** set `pos.api.base.url` in `android-app/local.properties` unless you are debugging against another host.

Build debug APK:

```bash
cd android-app
./gradlew :app:assembleDebug
```

Output:

**`android-app/app/build/outputs/apk/debug/app-debug.apk`**

Install:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

---

## Quick reference

| What | Where |
|------|--------|
| Render build / start | `render.yaml` or Render dashboard |
| Database | `DATABASE_URL` env → `app/config.py` |
| JWT | `JWT_SECRET_KEY` env → `app/auth.py` |
| Web + API in browser | `https://doposai.com/` |
| Android default server | `https://doposai.com/` in `app/build.gradle.kts` |
