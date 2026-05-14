#!/bin/bash
# Installation script for Ollama on Linux/Raspberry Pi
# This script installs Ollama and downloads the Phi-2 model

set -e

echo "=========================================="
echo "Ollama Installation Script"
echo "For Linux / Raspberry Pi"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo "Please do not run this script as root. It will prompt for sudo when needed."
   exit 1
fi

# Detect architecture
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

# Install Ollama
echo ""
echo "Step 1: Installing Ollama..."
if command -v ollama &> /dev/null; then
    echo "Ollama is already installed. Version: $(ollama --version 2>/dev/null || echo 'unknown')"
    read -p "Do you want to reinstall? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping Ollama installation."
    else
        echo "Removing existing Ollama..."
        sudo systemctl stop ollama 2>/dev/null || true
        sudo rm -f /usr/local/bin/ollama
    fi
fi

if ! command -v ollama &> /dev/null; then
    echo "Downloading and installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    
    # Verify installation
    if command -v ollama &> /dev/null; then
        echo "✅ Ollama installed successfully!"
    else
        echo "❌ Ollama installation failed. Please check the error messages above."
        exit 1
    fi
else
    echo "✅ Ollama is already installed."
fi

# Start Ollama service
echo ""
echo "Step 2: Starting Ollama service..."
if systemctl is-active --quiet ollama; then
    echo "Ollama service is already running."
else
    echo "Starting Ollama service..."
    sudo systemctl start ollama
    sudo systemctl enable ollama
    sleep 2
    
    if systemctl is-active --quiet ollama; then
        echo "✅ Ollama service started successfully!"
    else
        echo "⚠️  Warning: Ollama service may not be running. Trying to start manually..."
        ollama serve &
        sleep 3
    fi
fi

# Wait for Ollama to be ready
echo ""
echo "Step 3: Waiting for Ollama to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Ollama did not start within 30 seconds. Please check the service manually."
        exit 1
    fi
    sleep 1
done

# Download Phi-2 model
echo ""
echo "Step 4: Downloading Phi-2 model (~1.6GB)..."
echo "This may take several minutes depending on your internet connection..."
ollama pull phi:2.7b

# Verify model download
echo ""
echo "Step 5: Verifying Phi-2 model..."
if ollama list | grep -q "phi:2.7b"; then
    echo "✅ Phi-2 model downloaded successfully!"
else
    echo "❌ Phi-2 model verification failed."
    exit 1
fi

# Test the model
echo ""
echo "Step 6: Testing Phi-2 model..."
TEST_RESPONSE=$(ollama run phi:2.7b "Say 'Hello, I am working!'" 2>&1)
if echo "$TEST_RESPONSE" | grep -qi "hello\|working"; then
    echo "✅ Phi-2 model is working correctly!"
    echo "Test response: $(echo "$TEST_RESPONSE" | head -n 1)"
else
    echo "⚠️  Warning: Model test returned unexpected response."
    echo "Response: $TEST_RESPONSE"
fi

echo ""
echo "=========================================="
echo "✅ Installation Complete!"
echo "=========================================="
echo ""
echo "Ollama is now installed and running."
echo "Phi-2 model is ready to use."
echo ""
echo "To test manually, run:"
echo "  ollama run phi:2.7b 'Your question here'"
echo ""
echo "To check service status:"
echo "  sudo systemctl status ollama"
echo ""
echo "To stop Ollama:"
echo "  sudo systemctl stop ollama"
echo ""
echo "To start Ollama:"
echo "  sudo systemctl start ollama"
echo ""

