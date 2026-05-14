# Deploy backend to Render (GitHub) and build a test APK

## Part 1: GitHub

If this folder is not a git repository yet:

```bash
cd /path/to/pos
git init
git add .
git commit -m "Initial commit: POS backend + Android app"
```

Create a new empty repository on GitHub (no README/license), then:

```bash
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git branch -M main
git push -u origin main
```

## Part 2: Render

1. Sign in at [https://render.com](https://render.com) and connect your GitHub account.
2. **Option A – Blueprint (uses `render.yaml` in repo root)**  
   New → **Blueprint** → pick the repo → apply.  
   After deploy, open the web service → **Environment** → set a strong `JWT_SECRET_KEY` if you do not want the generated one, and adjust `DATABASE_URL` if you attach Postgres (see below).
3. **Option B – Web Service manually**  
   New → **Web Service** → select the repo.  
   - **Root directory:** leave empty (repo root).  
   - **Runtime:** Python 3  
   - **Build command:** `pip install -r requirements.txt`  
   - **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
   - **Environment variables:**  
     - `JWT_SECRET_KEY` – long random string (required for real use).  
     - `DATABASE_URL` – optional; defaults in code to local `pos.db`. For Render without Postgres, use `sqlite:////tmp/pos.db` (ephemeral; data lost on restart).  
     - For production, create **PostgreSQL** on Render, copy **Internal Database URL** into `DATABASE_URL`, and redeploy.

4. Wait for the first deploy. Your API base URL will be `https://<service-name>.onrender.com/` (note trailing slash for the Android app).

**Cold starts:** Free tier spins down when idle; the first request may take ~30–60s.

## Part 3: Point the Android app at Render

Default URL is still `https://doposai.com/` unless overridden.

**Recommended:** create `android-app/local.properties` (this file is gitignored) with:

```properties
pos.api.base.url=https://YOUR-SERVICE.onrender.com
```

No trailing slash required; Gradle normalizes it.

Then build a **debug** APK (unsigned; fine for testing):

```bash
cd android-app
./gradlew :app:assembleDebug
```

APK output:

`android-app/app/build/outputs/apk/debug/app-debug.apk`

Install on a device: `adb install -r app/build/outputs/apk/debug/app-debug.apk`

## Part 4: Optional release APK

Release builds use minification and optional signing via `keystore.properties`. For internal testing, debug APK is usually enough.

## Configuration reference

| Piece | Location |
|--------|----------|
| Server DB URL | `DATABASE_URL` env (see `app/config.py`) |
| JWT signing | `JWT_SECRET_KEY` env (see `app/auth.py`) |
| Android default API | `pos.api.base.url` in `android-app/local.properties` or `DEFAULT_API_BASE_URL` in `app/build.gradle.kts` |
