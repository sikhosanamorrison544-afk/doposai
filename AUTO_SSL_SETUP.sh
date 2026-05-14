#!/bin/bash
# Automated SSL setup that checks DNS first

DOMAIN="doposai.com"
EXPECTED_IP="102.128.79.226"

echo "=========================================="
echo "Automated SSL Setup for $DOMAIN"
echo "=========================================="
echo ""

# Check DNS
echo "Step 1: Checking DNS configuration..."
DNS_READY=false

if command -v host >/dev/null 2>&1; then
    DNS_RESULT=$(host $DOMAIN 2>&1 | grep "$EXPECTED_IP")
    if [ -n "$DNS_RESULT" ]; then
        DNS_READY=true
    fi
elif command -v nslookup >/dev/null 2>&1; then
    DNS_RESULT=$(nslookup $DOMAIN 2>&1 | grep "$EXPECTED_IP")
    if [ -n "$DNS_RESULT" ]; then
        DNS_READY=true
    fi
elif command -v dig >/dev/null 2>&1; then
    DNS_RESULT=$(dig +short $DOMAIN | grep "$EXPECTED_IP")
    if [ -n "$DNS_RESULT" ]; then
        DNS_READY=true
    fi
fi

if [ "$DNS_READY" = true ]; then
    echo "✓ DNS is configured correctly"
    echo ""
    echo "Step 2: Setting up SSL certificate..."
    echo ""
    cd /home/morrison/Desktop/pos
    sudo ./setup_ssl.sh
else
    echo "✗ DNS is not configured yet"
    echo ""
    echo "Current DNS status:"
    if command -v host >/dev/null 2>&1; then
        host $DOMAIN 2>&1 || echo "Domain not found"
    elif command -v nslookup >/dev/null 2>&1; then
        nslookup $DOMAIN 2>&1 || echo "Domain not found"
    elif command -v dig >/dev/null 2>&1; then
        dig +short $DOMAIN 2>&1 || echo "Domain not found"
    fi
    echo ""
    echo "Please configure DNS first:"
    echo "1. Add A record: doposai.com → $EXPECTED_IP"
    echo "2. Add A record: www.doposai.com → $EXPECTED_IP"
    echo "3. Wait 5-60 minutes for propagation"
    echo "4. Run this script again: sudo ./AUTO_SSL_SETUP.sh"
    echo ""
    echo "See DNS_CONFIGURATION_GUIDE.md for detailed instructions"
    exit 1
fi

