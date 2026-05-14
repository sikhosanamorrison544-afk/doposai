#!/bin/bash
# Start POS server accessible on local network

cd "$(dirname "$0")"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Get local IP address
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || ip addr show | grep -oP 'inet \K[\d.]+' | grep -v '127.0.0.1' | head -1)

echo "=========================================="
echo "Starting POS Server..."
echo "=========================================="
echo ""
echo "Server will be accessible at:"
echo "  - Local:    http://localhost:8000"
echo "  - Network:  http://${LOCAL_IP:-<IP_ADDRESS>}:8000"
echo ""
echo "To find your IP address on other devices, use:"
echo "  http://$(hostname).local:8000"
echo "  or check the IP above"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=========================================="
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down services..."
    exit 0
}

# Trap Ctrl+C and cleanup
trap cleanup INT TERM

echo ""

# Start uvicorn with network access
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

