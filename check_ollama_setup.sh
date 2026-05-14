#!/bin/bash
# Diagnostic script to check Ollama setup for POS system

echo "🔍 Checking Ollama Setup for POS System"
echo "========================================"
echo ""

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama is not installed"
    echo "   Install with: curl -fsSL https://ollama.com/install.sh | sh"
    exit 1
else
    echo "✅ Ollama is installed"
    OLLAMA_VERSION=$(ollama --version 2>&1 | head -1)
    echo "   Version: $OLLAMA_VERSION"
fi

echo ""

# Check if Ollama service is running
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama service is running on localhost:11434"
else
    echo "❌ Ollama service is NOT running"
    echo "   Start with: ollama serve"
    echo "   Or run in background: nohup ollama serve > /dev/null 2>&1 &"
    exit 1
fi

echo ""

# Check installed models
echo "📦 Checking installed models..."
MODELS=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | cut -d'"' -f4)

if [ -z "$MODELS" ]; then
    echo "❌ No models installed"
    echo ""
    echo "   Install Phi model with one of these:"
    echo "   - Quantized (recommended): ollama pull phi:Q4_K_M"
    echo "   - Standard: ollama pull phi:2.7b"
    echo "   - Latest: ollama pull phi"
    exit 1
else
    echo "✅ Installed models:"
    echo "$MODELS" | while read -r model; do
        echo "   - $model"
    done
fi

echo ""

# Check for Phi models specifically
PHI_MODELS=$(echo "$MODELS" | grep -i phi || true)
if [ -z "$PHI_MODELS" ]; then
    echo "⚠️  No Phi models found (recommended for POS system)"
    echo ""
    echo "   Install with: ollama pull phi:Q4_K_M"
else
    echo "✅ Phi model(s) found:"
    echo "$PHI_MODELS" | while read -r model; do
        echo "   - $model"
    done
fi

echo ""
echo "========================================"
echo "✅ Setup check complete!"
echo ""
echo "If all checks passed, restart your POS server."

