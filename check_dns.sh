#!/bin/bash
# Quick DNS check script

DOMAIN="doposai.com"
EXPECTED_IP="102.128.79.226"

echo "Checking DNS for $DOMAIN..."
echo "Expected IP: $EXPECTED_IP"
echo ""

# Try different methods
if command -v host >/dev/null 2>&1; then
    echo "Using 'host' command:"
    RESULT=$(host $DOMAIN 2>&1 | grep -o "$EXPECTED_IP")
    if [ -n "$RESULT" ]; then
        echo "✓ DNS is configured! Found: $RESULT"
        exit 0
    else
        echo "✗ DNS not pointing to expected IP"
        host $DOMAIN
    fi
elif command -v nslookup >/dev/null 2>&1; then
    echo "Using 'nslookup' command:"
    RESULT=$(nslookup $DOMAIN 2>&1 | grep -o "$EXPECTED_IP")
    if [ -n "$RESULT" ]; then
        echo "✓ DNS is configured! Found: $RESULT"
        exit 0
    else
        echo "✗ DNS not pointing to expected IP"
        nslookup $DOMAIN
    fi
elif command -v dig >/dev/null 2>&1; then
    echo "Using 'dig' command:"
    RESULT=$(dig +short $DOMAIN | grep "$EXPECTED_IP")
    if [ -n "$RESULT" ]; then
        echo "✓ DNS is configured! Found: $RESULT"
        exit 0
    else
        echo "✗ DNS not pointing to expected IP"
        dig +short $DOMAIN
    fi
else
    echo "No DNS tools found. Installing..."
    sudo apt-get install -y dnsutils
    host $DOMAIN
fi

echo ""
echo "DNS is not configured yet. Please:"
echo "1. Add A record: doposai.com → $EXPECTED_IP"
echo "2. Add A record: www.doposai.com → $EXPECTED_IP"
echo "3. Wait for propagation (5-60 minutes)"
echo "4. Run this script again to verify"
exit 1

