#!/usr/bin/env python3
"""
Test script to verify Ollama installation and integration.
Run this after installing Ollama to ensure everything works.
"""

import sys
import requests
import json
from datetime import datetime

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "phi:2.7b"

def test_ollama_connection():
    """Test if Ollama service is running."""
    print("=" * 60)
    print("Testing Ollama Connection")
    print("=" * 60)
    
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ Ollama service is running")
            models = response.json().get("models", [])
            print(f"   Found {len(models)} model(s)")
            for model in models:
                print(f"   - {model.get('name', 'unknown')}")
            return True
        else:
            print(f"❌ Ollama returned status code: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Ollama service")
        print("   Make sure Ollama is running: sudo systemctl start ollama")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_model_availability():
    """Test if Phi-2 model is available."""
    print("\n" + "=" * 60)
    print("Testing Phi-2 Model Availability")
    print("=" * 60)
    
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            
            # Check for phi:2.7b or similar
            phi_models = [m for m in model_names if "phi" in m.lower()]
            
            if phi_models:
                print(f"✅ Phi model found: {', '.join(phi_models)}")
                return True
            else:
                print("❌ Phi-2 model not found")
                print("   Install it with: ollama pull phi:2.7b")
                return False
        else:
            print(f"❌ Failed to check models: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_ai_generation():
    """Test AI text generation."""
    print("\n" + "=" * 60)
    print("Testing AI Text Generation")
    print("=" * 60)
    
    test_prompt = """You are a professional accountant. Analyze this sales data:

Last 30 days:
- Total Revenue: $5,000.00
- Number of Sales: 150
- Top Product: Cooking Oil - 50 units, $500 revenue

Provide a brief business analysis (2-3 sentences):"""
    
    print(f"Prompt: {test_prompt[:80]}...")
    print("Generating response...")
    
    try:
        url = f"{OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": test_prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 200,
            }
        }
        
        response = requests.post(url, json=payload, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result.get("response", "").strip()
            
            if ai_response:
                print("✅ AI generation successful!")
                print("\n" + "-" * 60)
                print("AI Response:")
                print("-" * 60)
                print(ai_response)
                print("-" * 60)
                return True
            else:
                print("❌ AI returned empty response")
                return False
        else:
            print(f"❌ AI generation failed: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ Request timed out (this may be normal on slower systems)")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_performance():
    """Test response time."""
    print("\n" + "=" * 60)
    print("Testing Performance")
    print("=" * 60)
    
    simple_prompt = "Say 'Hello, I am working!' in one sentence."
    
    try:
        start_time = datetime.now()
        
        url = f"{OLLAMA_BASE_URL}/api/generate"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": simple_prompt,
            "stream": False,
            "options": {
                "num_predict": 50,
            }
        }
        
        response = requests.post(url, json=payload, timeout=30)
        end_time = datetime.now()
        
        elapsed = (end_time - start_time).total_seconds()
        
        if response.status_code == 200:
            print(f"✅ Response time: {elapsed:.2f} seconds")
            if elapsed < 5:
                print("   ⚡ Excellent performance!")
            elif elapsed < 15:
                print("   ✓ Good performance")
            else:
                print("   ⚠️  Slow response (may be normal on Raspberry Pi)")
            return True
        else:
            print(f"❌ Request failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Ollama Integration Test Suite")
    print("=" * 60)
    print(f"Ollama URL: {OLLAMA_BASE_URL}")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    results = {
        "connection": test_ollama_connection(),
        "model": test_model_availability(),
        "generation": test_ai_generation(),
        "performance": test_performance(),
    }
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name.upper():20s} {status}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All tests passed! Ollama is ready to use.")
        print("\nNext steps:")
        print("1. Start your POS system")
        print("2. Navigate to Admin panel")
        print("3. Click the 🤖 AI Insights button")
        print("4. View your business analysis")
    else:
        print("❌ Some tests failed. Please fix the issues above.")
        print("\nTroubleshooting:")
        if not results["connection"]:
            print("- Make sure Ollama is running: sudo systemctl start ollama")
            print("- Check service status: sudo systemctl status ollama")
        if not results["model"]:
            print("- Install Phi-2 model: ollama pull phi:2.7b")
        if not results["generation"]:
            print("- Check Ollama logs: journalctl -u ollama -n 50")
    print("=" * 60 + "\n")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

