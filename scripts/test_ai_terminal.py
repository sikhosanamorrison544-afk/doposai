#!/usr/bin/env python3
"""
Test Ollama / Business Sage AI from the terminal.

Run from project root:
  python scripts/test_ai_terminal.py

Or with full path:
  cd /home/morrison/Desktop/pos && python scripts/test_ai_terminal.py

Quick curl checks (no Python):
  curl -s http://localhost:11434/api/version
  curl -s http://localhost:11434/api/tags
  curl -s -X POST http://localhost:11434/api/generate -d '{"model":"phi:2.7b","prompt":"Say hello","stream":false}' --max-time 60
"""
import sys
import time

# Add app to path so we can import ai_service
sys.path.insert(0, ".")

def test_ollama_direct():
    """Test Ollama with simple HTTP calls (no app DB)."""
    try:
        import requests
    except ImportError:
        print("Install requests: pip install requests")
        return False

    base = "http://localhost:11434"
    model = "phi:2.7b"

    print("=== 1. Ollama version (is it running?) ===")
    try:
        r = requests.get(f"{base}/api/version", timeout=2)
        print(f"   OK: {r.json()}")
    except requests.exceptions.ConnectionError:
        print("   FAIL: Cannot connect. Start Ollama: ollama serve")
        return False
    except Exception as e:
        print(f"   FAIL: {e}")
        return False

    print("\n=== 2. Available models ===")
    try:
        r = requests.get(f"{base}/api/tags", timeout=5)
        data = r.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        print(f"   Models: {models}")
        if not models:
            print("   No models. Run: ollama pull phi:2.7b")
            return False
        # Use first phi if phi:2.7b not found
        if model not in models:
            phi = [m for m in models if "phi" in m.lower()]
            if phi:
                model = phi[0]
                print(f"   Using instead: {model}")
            else:
                print(f"   Phi not found. Run: ollama pull {model}")
                return False
    except Exception as e:
        print(f"   FAIL: {e}")
        return False

    print("\n=== 3. Short test prompt (60 sec timeout; first run may load model) ===")
    prompt = "In one short sentence, what is 2+2? Reply with just the number."
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 20},
    }
    try:
        start = time.time()
        r = requests.post(f"{base}/api/generate", json=payload, timeout=60)
        elapsed = time.time() - start
        if r.status_code == 200:
            out = r.json().get("response", "").strip()
            print(f"   OK in {elapsed:.1f}s: {out[:200]}")
        else:
            print(f"   HTTP {r.status_code}: {r.text[:300]}")
    except requests.exceptions.Timeout:
        print("   TIMEOUT after 60s. Model may be too slow on this device or stuck.")
        print("   Try in another terminal: ollama run phi:2.7b 'Hi'  (wait for reply)")
        return False
    except Exception as e:
        print(f"   FAIL: {e}")
        return False

    print("\n=== 4. Chat-style test (40 tokens, 90 sec timeout) ===")
    prompt2 = "One tip for a small shop in one short sentence:"
    payload2 = {
        "model": model,
        "prompt": prompt2,
        "stream": False,
        "options": {"num_predict": 40, "temperature": 0.7},
    }
    try:
        start = time.time()
        r = requests.post(f"{base}/api/generate", json=payload2, timeout=90)
        elapsed = time.time() - start
        if r.status_code == 200:
            out = r.json().get("response", "").strip()
            print(f"   OK in {elapsed:.1f}s: {out[:300]}")
        else:
            print(f"   HTTP {r.status_code}: {r.text[:300]}")
    except requests.exceptions.Timeout:
        print("   TIMEOUT after 90s. Model is slow; use instant answers in the app (e.g. 'profit', 'business tips').")
        # Don't return False - step 3 already proved Ollama works
    except Exception as e:
        print(f"   FAIL: {e}")

    print("\n=== Ollama is working. If chat is slow in the app, use instant answers: profit, revenue, business tips. ===")
    return True


def test_app_ai_service():
    """Optionally test the app's AIService (needs app venv + DB)."""
    print("\n=== 5. App AIService (optional) ===")
    try:
        from app.ai_service import ai_service
        from app.database import SessionLocal
        ok = ai_service._check_ollama_available(retries=1, use_cache=False)
        print(f"   AIService sees Ollama: {ok}")
        if ok:
            db = SessionLocal()
            try:
                start = time.time()
                reply = ai_service.chat_with_sales_context(db, "What is 2+2? Reply with one number.", days=7)
                elapsed = time.time() - start
                print(f"   Chat reply in {elapsed:.1f}s: {(reply or '')[:150]}")
            finally:
                db.close()
    except ImportError as e:
        print(f"   Skip (run from app venv for full test): {e}")
    except Exception as e:
        print(f"   Skip: {e}")


if __name__ == "__main__":
    print("Testing Ollama AI (Business Sage backend)\n")
    ok = test_ollama_direct()
    if ok:
        test_app_ai_service()
    print("\n--- Where to use Business Sage ---")
    print("  Open your POS in the browser → Analytics → open the 'Chat with Business Sage' panel.")
    print("  Type there: give me business tips, profit, revenue, sales, summary, etc.")
    print("  (Do not type these in the terminal; they are chat messages for the web app.)")
    sys.exit(0 if ok else 1)
