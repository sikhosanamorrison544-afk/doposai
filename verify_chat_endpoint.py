#!/usr/bin/env python3
"""
Quick script to verify the AI chat endpoint is available.
Run this after restarting your POS server.
"""

import requests
import sys

BASE_URL = "http://localhost:8000"

def check_endpoint():
    """Check if the chat endpoint exists."""
    print("Checking AI chat endpoint...")
    print(f"Server: {BASE_URL}")
    print()
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/api/ai/status", timeout=5)
        print("✅ Server is running")
    except requests.exceptions.ConnectionError:
        print("❌ Server is not running or not accessible at http://localhost:8000")
        print("   Please start your POS server first.")
        return False
    except Exception as e:
        print(f"❌ Error connecting to server: {e}")
        return False
    
    # Check if chat endpoint exists (will get 401 without auth, but that means endpoint exists)
    try:
        response = requests.post(
            f"{BASE_URL}/api/ai/chat",
            json={"message": "test", "days": 30},
            timeout=5
        )
        if response.status_code == 401:
            print("✅ Chat endpoint exists (401 = authentication required, which is expected)")
            print("   The endpoint is properly registered!")
            return True
        elif response.status_code == 404:
            print("❌ Chat endpoint not found (404)")
            print("   The server needs to be restarted to load the new endpoint.")
            return False
        else:
            print(f"✅ Chat endpoint exists (status: {response.status_code})")
            return True
    except requests.exceptions.Timeout:
        print("⏱️ Request timed out (server might be slow)")
        return False
    except Exception as e:
        print(f"❌ Error checking endpoint: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("  AI Chat Endpoint Verification")
    print("=" * 60)
    print()
    
    success = check_endpoint()
    
    print()
    print("=" * 60)
    if success:
        print("✅ Endpoint verification complete!")
        print("   If you're still getting 404 errors, try:")
        print("   1. Hard refresh your browser (Ctrl+Shift+R)")
        print("   2. Clear browser cache")
    else:
        print("❌ Endpoint not available")
        print("   Please restart your POS server:")
        print("   1. Stop the current server (Ctrl+C)")
        print("   2. Restart with: uvicorn app.main:app --host 0.0.0.0 --port 8000")
    print("=" * 60)


