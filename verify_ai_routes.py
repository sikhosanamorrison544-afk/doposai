#!/usr/bin/env python3
"""
Quick script to verify AI routes are accessible.
Run this after restarting your server.
"""

import sys
import requests

BASE_URL = "http://localhost:8000"

def check_route(path, requires_auth=True):
    """Check if a route exists."""
    try:
        url = f"{BASE_URL}{path}"
        headers = {}
        
        if requires_auth:
            # Try without auth first to see if route exists
            response = requests.get(url, timeout=2)
            if response.status_code == 401:
                return True, "Route exists (requires authentication)"
            elif response.status_code == 404:
                return False, "Route not found (404)"
            else:
                return True, f"Route exists (status: {response.status_code})"
        else:
            response = requests.get(url, timeout=2)
            if response.status_code == 404:
                return False, "Route not found (404)"
            else:
                return True, f"Route exists (status: {response.status_code})"
    except requests.exceptions.ConnectionError:
        return None, "Cannot connect to server (is it running?)"
    except Exception as e:
        return None, f"Error: {e}"

def main():
    print("=" * 60)
    print("Verifying AI Routes")
    print("=" * 60)
    print(f"Server: {BASE_URL}\n")
    
    routes = [
        ("/api/ai/status", True),
        ("/api/ai/analyze", True),
    ]
    
    all_ok = True
    for path, requires_auth in routes:
        exists, message = check_route(path, requires_auth)
        if exists is True:
            print(f"✅ {path:30s} {message}")
        elif exists is False:
            print(f"❌ {path:30s} {message}")
            all_ok = False
        else:
            print(f"⚠️  {path:30s} {message}")
            all_ok = False
    
    print("\n" + "=" * 60)
    if all_ok:
        print("✅ All AI routes are accessible!")
        print("\nIf you're still getting 404 errors in the browser:")
        print("1. Hard refresh the page (Ctrl+Shift+R or Cmd+Shift+R)")
        print("2. Clear browser cache")
        print("3. Check browser console for errors")
    else:
        print("❌ Some routes are not accessible")
        print("\nTroubleshooting:")
        print("1. Make sure the server is running")
        print("2. Restart the server: uvicorn app.main:app --host 0.0.0.0 --port 8000")
        print("3. Check server logs for import errors")
    print("=" * 60)
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())

