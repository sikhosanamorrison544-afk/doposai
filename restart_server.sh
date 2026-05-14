#!/bin/bash
# Script to restart the POS server with AI routes

echo "🔄 Restarting POS Server..."
echo ""

# Kill existing server
echo "Stopping existing server..."
pkill -f "uvicorn app.main" || echo "No existing server found"

# Wait a moment
sleep 2

# Check if port is still in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 8000 is still in use. Killing process..."
    kill $(lsof -t -i:8000) 2>/dev/null || true
    sleep 2
fi

# Activate venv and start server
echo "Starting server..."
cd /home/morrison/Desktop/pos
source .venv/bin/activate
echo ""
echo "✅ Server starting on http://0.0.0.0:8000"
echo "   Watch for any import errors in the output below"
echo "   Press Ctrl+C to stop"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000
