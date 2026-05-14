#!/bin/bash
# Get the local IP address for accessing the POS system

echo "=========================================="
echo "POS System Network Access Information"
echo "=========================================="
echo ""

# Try to get IP address using different methods
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$LOCAL_IP" ]; then
    LOCAL_IP=$(ip addr show | grep -oP 'inet \K[\d.]+' | grep -v '127.0.0.1' | head -1)
fi

HOSTNAME=$(hostname)

if [ -n "$LOCAL_IP" ]; then
    echo "Local IP Address: $LOCAL_IP"
    echo ""
    echo "Access the POS system from other devices on your network at:"
    echo "  http://$LOCAL_IP:8000"
    echo ""
    echo "Or try using the hostname:"
    echo "  http://$HOSTNAME.local:8000"
    echo ""
else
    echo "Could not determine IP address automatically."
    echo "Please check your network connection."
    echo ""
    echo "You can manually find your IP with:"
    echo "  ip addr show"
    echo "  or"
    echo "  hostname -I"
    echo ""
fi

echo "=========================================="
echo ""
echo "Make sure the server is running with:"
echo "  ./start_server.sh"
echo "  or"
echo "  uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo ""

