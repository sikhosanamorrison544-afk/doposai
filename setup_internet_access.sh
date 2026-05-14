#!/bin/bash
# Complete setup script for making POS accessible via doposai.com
# Run this script as root or with sudo

set -e

DOMAIN="doposai.com"
POS_DIR="/home/morrison/Desktop/pos"
SERVICE_USER="morrison"

echo "=========================================="
echo "POS Internet Access Setup for $DOMAIN"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Update system
echo "Step 1: Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo ""
echo "Step 2: Installing required packages..."
apt-get install -y nginx certbot python3-certbot-nginx ufw

# Generate secure JWT secret key
echo ""
echo "Step 3: Generating secure JWT secret key..."
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "Generated JWT secret key"

# Create environment file
echo ""
echo "Step 4: Creating environment configuration..."
ENV_FILE="$POS_DIR/.env"
cat > "$ENV_FILE" << EOF
# JWT Secret Key for authentication
JWT_SECRET_KEY=$JWT_SECRET

# Domain configuration
DOMAIN=$DOMAIN
EOF
chown $SERVICE_USER:$SERVICE_USER "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "Created $ENV_FILE"

# Configure firewall
echo ""
echo "Step 5: Configuring firewall..."
ufw --force enable
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (for Let's Encrypt)
ufw allow 443/tcp   # HTTPS
echo "Firewall configured"

# Create systemd service for POS
echo ""
echo "Step 6: Creating systemd service for POS..."
cat > /etc/systemd/system/pos.service << EOF
[Unit]
Description=POS System FastAPI Application
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$POS_DIR
Environment="PATH=$POS_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$POS_DIR/.env
ExecStart=$POS_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable POS service
systemctl daemon-reload
systemctl enable pos.service
echo "POS service created and enabled"

# Create Nginx configuration
echo ""
echo "Step 8: Creating Nginx configuration..."
cat > /etc/nginx/sites-available/pos << 'NGINX_CONFIG'
# POS System - Nginx Reverse Proxy Configuration
# This file will be updated by certbot after SSL setup

upstream pos_backend {
    server 127.0.0.1:8000;
    keepalive 64;
}

server {
    listen 80;
    listen [::]:80;
    server_name doposai.com www.doposai.com;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Logging
    access_log /var/log/nginx/pos_access.log;
    error_log /var/log/nginx/pos_error.log;

    # Increase client body size for file uploads
    client_max_body_size 10M;

    # AI chat can take a long time (Ollama on Pi); use 5 min so app gets response
    location /api/ai/chat {
        proxy_pass http://pos_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }

    # Proxy settings
    location / {
        proxy_pass http://pos_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Buffering
        proxy_buffering off;
    }

    # Static files (if served directly by Nginx)
    location /static/ {
        alias /home/morrison/Desktop/pos/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
NGINX_CONFIG

# Enable the site
ln -sf /etc/nginx/sites-available/pos /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default  # Remove default site

# Test Nginx configuration
nginx -t
if [ $? -eq 0 ]; then
    systemctl restart nginx
    echo "Nginx configuration created and enabled"
else
    echo "ERROR: Nginx configuration test failed!"
    exit 1
fi

echo ""
echo "=========================================="
echo "Setup Complete - Next Steps:"
echo "=========================================="
echo ""
echo "1. Configure DNS for $DOMAIN:"
echo "   - Point A record to your Raspberry Pi's public IP address"
echo "   - Point www.$DOMAIN A record to the same IP"
echo ""
echo "2. Wait for DNS propagation (can take up to 48 hours)"
echo "   - Check with: nslookup $DOMAIN"
echo ""
echo "3. Once DNS is propagated, run SSL setup:"
echo "   sudo ./setup_ssl.sh"
echo ""
echo "4. Start the POS service:"
echo "   sudo systemctl start pos.service"
echo "   sudo systemctl status pos.service"
echo ""
echo "5. Check logs:"
echo "   sudo journalctl -u pos.service -f"
echo ""
echo "=========================================="
echo "Your POS will be accessible at:"
echo "  http://$DOMAIN (after DNS setup)"
echo "  https://$DOMAIN (after SSL setup)"
echo "=========================================="

