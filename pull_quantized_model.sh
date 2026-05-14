#!/bin/bash
# Pull quantized Phi model for faster inference on Raspberry Pi 5

echo "Pulling quantized Phi model (Q4_K_M) for faster inference..."
echo "This model is optimized for speed on Raspberry Pi 5"

ollama pull phi:Q4_K_M

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Successfully pulled phi:Q4_K_M"
    echo ""
    echo "The POS system is now configured to use this quantized model."
    echo "Restart your POS server to use the new model."
else
    echo ""
    echo "❌ Failed to pull model. Make sure Ollama is running:"
    echo "   ollama serve"
    exit 1
fi

