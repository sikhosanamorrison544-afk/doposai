#!/bin/bash
# Quick setup script for ultra-fast Ollama on Raspberry Pi 5
# Run with: bash setup_ollama_fast.sh

set -e

echo "🚀 Setting up Ollama for ultra-fast responses on Raspberry Pi 5..."

# 1. Set environment variables for current session
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_THREAD=4
export OLLAMA_FLASH_ATTENTION=0
export OLLAMA_KEEP_ALIVE=5m

echo "✅ Environment variables set"

# 2. Pull Phi-2 model if not exists
echo "📦 Checking Phi-2 model..."
if ! ollama list | grep -q "phi:2.7b"; then
    echo "Downloading Phi-2 model (this may take a few minutes)..."
    ollama pull phi:2.7b
else
    echo "✅ Phi-2 model already installed"
fi

# 3. Set CPU governor to performance mode
echo "⚡ Setting CPU governor to performance mode..."
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null 2>&1 || {
        echo "⚠️  Could not set CPU governor (may need sudo or governor not available)"
    }
else
    echo "⚠️  CPU governor not available (may be running on different system)"
fi

# 4. Test Ollama response time
echo ""
echo "🧪 Testing Ollama response time..."
echo "Expected: <2 seconds"
echo ""

START_TIME=$(date +%s.%N)
RESPONSE=$(curl -s http://localhost:11434/api/generate -d '{
  "model": "phi:2.7b",
  "prompt": "Data: $1000 rev, $800 profit. Advice:",
  "stream": false,
  "options": {
    "temperature": 0.0,
    "num_predict": 25,
    "num_ctx": 512,
    "top_p": 0.3,
    "top_k": 10
  }
}' 2>/dev/null | grep -o '"response":"[^"]*"' | cut -d'"' -f4)

END_TIME=$(date +%s.%N)
ELAPSED=$(echo "$END_TIME - $START_TIME" | bc)

if [ -n "$RESPONSE" ]; then
    echo "✅ Response received in ${ELAPSED} seconds"
    echo "Response: $RESPONSE"
    if (( $(echo "$ELAPSED < 2.0" | bc -l) )); then
        echo "🎉 SUCCESS: Response time is under 2 seconds!"
    else
        echo "⚠️  Response time is ${ELAPSED}s (target: <2s). Check Ollama configuration."
    fi
else
    echo "❌ ERROR: No response from Ollama. Is Ollama running?"
    echo "Start Ollama with: OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_THREAD=4 ollama serve"
fi

echo ""
echo "📋 Next steps:"
echo "1. Start Ollama with optimized settings:"
echo "   OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_THREAD=4 ollama serve"
echo ""
echo "2. Or create a systemd service (see OLLAMA_RASPBERRY_PI_OPTIMIZATION.md)"
echo ""
echo "3. Test your POS AI chat - it should respond in <2 seconds!"

