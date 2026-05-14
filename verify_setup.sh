#!/bin/bash
# Verification script to check if internet setup is configured correctly

echo "=========================================="
echo "POS Internet Setup Verification"
echo "=========================================="
echo ""

ERRORS=0
WARNINGS=0

# Check if running as root for some checks
if [ "$EUID" -eq 0 ]; then
    IS_ROOT=true
else
    IS_ROOT=false
fi

# 1. Check DNS configuration
echo "1. Checking DNS configuration..."
if command -v nslookup >/dev/null 2>&1; then
    DNS_RESULT=$(nslookup doposai.com 2>&1)
    if echo "$DNS_RESULT" | grep -q "Name:"; then
        echo "   ✓ DNS is configured for doposai.com"
        echo "$DNS_RESULT" | grep -A 1 "Name:" | head -2
    else
        echo "   ✗ DNS not configured or not propagated"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "   ⚠ nslookup not found, skipping DNS check"
    WARNINGS=$((WARNINGS + 1))
fi

# 2. Check if required packages are installed
echo ""
echo "2. Checking required packages..."
for pkg in nginx certbot ufw; do
    if dpkg -l | grep -q "^ii.*$pkg"; then
        echo "   ✓ $pkg is installed"
    else
        echo "   ✗ $pkg is NOT installed"
        ERRORS=$((ERRORS + 1))
    fi
done

# 3. Check firewall configuration
echo ""
echo "3. Checking firewall configuration..."
if [ "$IS_ROOT" = true ]; then
    if ufw status | grep -q "Status: active"; then
        echo "   ✓ UFW firewall is active"
        if ufw status | grep -q "80/tcp"; then
            echo "   ✓ Port 80 (HTTP) is allowed"
        else
            echo "   ✗ Port 80 (HTTP) is NOT allowed"
            ERRORS=$((ERRORS + 1))
        fi
        if ufw status | grep -q "443/tcp"; then
            echo "   ✓ Port 443 (HTTPS) is allowed"
        else
            echo "   ✗ Port 443 (HTTPS) is NOT allowed"
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "   ⚠ UFW firewall is not active"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "   ⚠ Run as root to check firewall"
    WARNINGS=$((WARNINGS + 1))
fi

# 4. Check Nginx configuration
echo ""
echo "4. Checking Nginx configuration..."
if [ "$IS_ROOT" = true ]; then
    if [ -f "/etc/nginx/sites-enabled/pos" ] || [ -L "/etc/nginx/sites-enabled/pos" ]; then
        echo "   ✓ Nginx site configuration exists"
        if nginx -t 2>&1 | grep -q "successful"; then
            echo "   ✓ Nginx configuration is valid"
        else
            echo "   ✗ Nginx configuration has errors"
            nginx -t 2>&1 | grep -i error
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "   ✗ Nginx site configuration NOT found"
        ERRORS=$((ERRORS + 1))
    fi
    
    if systemctl is-active --quiet nginx; then
        echo "   ✓ Nginx service is running"
    else
        echo "   ✗ Nginx service is NOT running"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "   ⚠ Run as root to check Nginx"
    WARNINGS=$((WARNINGS + 1))
fi

# 5. Check SSL certificate
echo ""
echo "5. Checking SSL certificate..."
if [ "$IS_ROOT" = true ]; then
    if [ -d "/etc/letsencrypt/live/doposai.com" ]; then
        echo "   ✓ SSL certificate directory exists"
        if [ -f "/etc/letsencrypt/live/doposai.com/fullchain.pem" ]; then
            echo "   ✓ SSL certificate files exist"
            CERT_EXPIRY=$(openssl x509 -enddate -noout -in /etc/letsencrypt/live/doposai.com/cert.pem 2>/dev/null | cut -d= -f2)
            if [ -n "$CERT_EXPIRY" ]; then
                echo "   ✓ Certificate expires: $CERT_EXPIRY"
            fi
        else
            echo "   ✗ SSL certificate files NOT found"
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "   ⚠ SSL certificate NOT configured (run setup_ssl.sh)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "   ⚠ Run as root to check SSL certificate"
    WARNINGS=$((WARNINGS + 1))
fi

# 6. Check POS service
echo ""
echo "6. Checking POS service..."
if [ "$IS_ROOT" = true ]; then
    if [ -f "/etc/systemd/system/pos.service" ]; then
        echo "   ✓ POS systemd service file exists"
        if systemctl is-enabled --quiet pos.service 2>/dev/null; then
            echo "   ✓ POS service is enabled"
        else
            echo "   ⚠ POS service is NOT enabled"
            WARNINGS=$((WARNINGS + 1))
        fi
        if systemctl is-active --quiet pos.service 2>/dev/null; then
            echo "   ✓ POS service is running"
        else
            echo "   ✗ POS service is NOT running"
            ERRORS=$((ERRORS + 1))
        fi
    else
        echo "   ✗ POS systemd service file NOT found"
        ERRORS=$((ERRORS + 1))
    fi
else
    if systemctl --user is-active --quiet pos.service 2>/dev/null || pgrep -f "uvicorn app.main:app" > /dev/null; then
        echo "   ✓ POS application appears to be running"
    else
        echo "   ⚠ POS application may not be running"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

# 7. Check environment file
echo ""
echo "7. Checking environment configuration..."
ENV_FILE="/home/morrison/Desktop/pos/.env"
if [ -f "$ENV_FILE" ]; then
    echo "   ✓ .env file exists"
    if grep -q "JWT_SECRET_KEY" "$ENV_FILE"; then
        if grep "JWT_SECRET_KEY" "$ENV_FILE" | grep -qv "change-this"; then
            echo "   ✓ JWT_SECRET_KEY is configured"
        else
            echo "   ⚠ JWT_SECRET_KEY is still using default value"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        echo "   ✗ JWT_SECRET_KEY NOT found in .env"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "   ⚠ .env file NOT found (will be created by setup script)"
    WARNINGS=$((WARNINGS + 1))
fi

# 8. Check if POS is accessible locally
echo ""
echo "8. Checking local POS accessibility..."
if curl -s http://localhost:8000 > /dev/null 2>&1; then
    echo "   ✓ POS is accessible on localhost:8000"
else
    echo "   ✗ POS is NOT accessible on localhost:8000"
    ERRORS=$((ERRORS + 1))
fi

# 9. Check if domain is accessible (if DNS is configured)
echo ""
echo "9. Checking domain accessibility..."
if command -v curl >/dev/null 2>&1; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://doposai.com 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
        echo "   ✓ Domain is accessible via HTTP (code: $HTTP_CODE)"
    elif [ "$HTTP_CODE" = "000" ]; then
        echo "   ⚠ Domain may not be accessible (connection failed)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "   ⚠ Domain returned HTTP code: $HTTP_CODE"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    HTTPS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -k https://doposai.com 2>/dev/null || echo "000")
    if [ "$HTTPS_CODE" = "200" ] || [ "$HTTPS_CODE" = "301" ] || [ "$HTTPS_CODE" = "302" ]; then
        echo "   ✓ Domain is accessible via HTTPS (code: $HTTPS_CODE)"
    elif [ "$HTTPS_CODE" = "000" ]; then
        echo "   ⚠ HTTPS may not be configured (connection failed)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "   ⚠ HTTPS returned HTTP code: $HTTPS_CODE"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "   ⚠ curl not found, skipping domain check"
    WARNINGS=$((WARNINGS + 1))
fi

# Summary
echo ""
echo "=========================================="
echo "Verification Summary"
echo "=========================================="
echo "Errors:   $ERRORS"
echo "Warnings: $WARNINGS"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo "✓ All checks passed! Your setup looks good."
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo "⚠ Setup is mostly complete, but there are some warnings."
    exit 0
else
    echo "✗ Setup has errors that need to be fixed."
    echo ""
    echo "Next steps:"
    echo "1. Run: sudo ./setup_internet_access.sh"
    echo "2. Configure DNS and wait for propagation"
    echo "3. Run: sudo ./setup_ssl.sh"
    exit 1
fi

