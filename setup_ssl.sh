#!/bin/bash
# SSL Certificate Setup using Let's Encrypt
# Run this script as root or with sudo after DNS is configured

set -e

DOMAIN="doposai.com"

echo "=========================================="
echo "SSL Certificate Setup for $DOMAIN"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Check if domain resolves
echo "Step 1: Checking DNS configuration..."
if ! nslookup $DOMAIN > /dev/null 2>&1; then
    echo "WARNING: $DOMAIN does not resolve. Please configure DNS first."
    echo "Continue anyway? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✓ DNS is configured for $DOMAIN"
fi

# Obtain SSL certificate
echo ""
echo "Step 2: Obtaining SSL certificate from Let's Encrypt..."
certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN --redirect

if [ $? -eq 0 ]; then
    echo "✓ SSL certificate obtained successfully"
else
    echo "ERROR: Failed to obtain SSL certificate"
    exit 1
fi

# Update Nginx configuration with security headers
echo ""
echo "Step 3: Adding security headers to Nginx configuration..."
NGINX_CONFIG="/etc/nginx/sites-available/pos"

# Check if SSL configuration exists
if grep -q "listen 443" "$NGINX_CONFIG"; then
    # Add security headers to SSL server block
    sed -i '/server_name/a\
    # Security headers\
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\
    add_header X-Frame-Options "SAMEORIGIN" always;\
    add_header X-Content-Type-Options "nosniff" always;\
    add_header X-XSS-Protection "1; mode=block" always;\
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;\
    add_header Content-Security-Policy "default-src '\''self'\''; script-src '\''self'\'' '\''unsafe-inline'\''; style-src '\''self'\'' '\''unsafe-inline'\''; img-src '\''self'\'' data: https:; font-src '\''self'\'' data:; connect-src '\''self'\''; frame-ancestors '\''self'\'';" always;
' "$NGINX_CONFIG"
    
    # Test and reload Nginx
    nginx -t
    if [ $? -eq 0 ]; then
        systemctl reload nginx
        echo "✓ Security headers added"
    else
        echo "WARNING: Nginx configuration test failed after adding headers"
    fi
fi

# Setup auto-renewal
echo ""
echo "Step 4: Setting up automatic certificate renewal..."
systemctl enable certbot.timer
systemctl start certbot.timer
echo "✓ Auto-renewal configured"

# Test renewal
echo ""
echo "Step 5: Testing certificate renewal..."
certbot renew --dry-run
if [ $? -eq 0 ]; then
    echo "✓ Certificate renewal test successful"
else
    echo "WARNING: Certificate renewal test failed"
fi

echo ""
echo "=========================================="
echo "SSL Setup Complete!"
echo "=========================================="
echo ""
echo "Your POS is now accessible at:"
echo "  https://$DOMAIN"
echo "  https://www.$DOMAIN"
echo ""
echo "Certificate will auto-renew every 90 days"
echo "Check renewal status: sudo certbot certificates"
echo "=========================================="

