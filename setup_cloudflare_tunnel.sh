#!/bin/bash
# Cloudflare Tunnel Setup for Mobile Hotspot Connection
# This bypasses the need for port forwarding

set -e

DOMAIN="doposai.com"
POS_DIR="/home/morrison/Desktop/pos"
SERVICE_USER="morrison"

echo "=========================================="
echo "Cloudflare Tunnel Setup for $DOMAIN"
echo "=========================================="
echo ""
echo "This setup will create a secure tunnel from your Pi"
echo "to Cloudflare, bypassing port forwarding requirements."
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Install cloudflared
echo "Step 1: Installing cloudflared..."
if ! command -v cloudflared >/dev/null 2>&1; then
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        ARCH="arm64"
    elif [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armhf" ]; then
        ARCH="arm"
    else
        ARCH="amd64"
    fi
    
    echo "Downloading cloudflared for $ARCH..."
    cd /tmp
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH.deb
    dpkg -i cloudflared-linux-$ARCH.deb || apt-get install -f -y
    rm -f cloudflared-linux-$ARCH.deb
    echo "✓ cloudflared installed"
else
    echo "✓ cloudflared already installed"
fi

# Check if tunnel already exists
echo ""
echo "Step 2: Setting up Cloudflare Tunnel..."
echo ""
echo "You need to authenticate with Cloudflare."
echo "This will show a URL that you need to visit in a browser."
echo ""
echo "Starting authentication..."
echo ""

# Login to Cloudflare (non-interactive, will show URL)
cloudflared tunnel login 2>&1 | tee /tmp/cloudflare_auth.txt

# Check if login was successful
if [ ! -f "/home/$SERVICE_USER/.cloudflared/cert.pem" ]; then
    echo ""
    echo "⚠️  Authentication may not be complete."
    echo "Please check the URL above and complete authentication."
    echo "Then run this script again, or continue manually."
    echo ""
    echo "To continue manually after authentication:"
    echo "  cloudflared tunnel create pos-tunnel"
    echo "  Then run this script again"
    exit 1
fi

# Create tunnel
TUNNEL_NAME="pos-tunnel"
echo ""
echo "Creating tunnel: $TUNNEL_NAME"
cloudflared tunnel create $TUNNEL_NAME || echo "Tunnel may already exist"

# Get tunnel UUID
TUNNEL_UUID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}' | head -1)
if [ -z "$TUNNEL_UUID" ]; then
    echo "Error: Could not find tunnel UUID"
    exit 1
fi

echo "✓ Tunnel created: $TUNNEL_UUID"

# Create tunnel configuration
echo ""
echo "Step 3: Configuring tunnel..."
TUNNEL_CONFIG_DIR="/etc/cloudflared"
mkdir -p "$TUNNEL_CONFIG_DIR"

cat > "$TUNNEL_CONFIG_DIR/config.yml" << EOF
tunnel: $TUNNEL_UUID
credentials-file: /home/$SERVICE_USER/.cloudflared/$TUNNEL_UUID.json

ingress:
  - hostname: $DOMAIN
    service: http://localhost:8000
  - hostname: www.$DOMAIN
    service: http://localhost:8000
  - service: http_status:404
EOF

# Copy credentials
mkdir -p "/home/$SERVICE_USER/.cloudflared"
if [ -f "/home/$SERVICE_USER/.cloudflared/$TUNNEL_UUID.json" ]; then
    echo "✓ Credentials file exists"
else
    echo "⚠ Credentials file not found. You may need to run:"
    echo "  cloudflared tunnel login"
    echo "  cloudflared tunnel create $TUNNEL_NAME"
fi

# Create DNS route
echo ""
echo "Step 4: Creating DNS routes..."
cloudflared tunnel route dns $TUNNEL_NAME $DOMAIN || echo "DNS route may already exist"
cloudflared tunnel route dns $TUNNEL_NAME www.$DOMAIN || echo "DNS route may already exist"

# Create systemd service
echo ""
echo "Step 5: Creating systemd service..."
cat > /etc/systemd/system/cloudflared.service << EOF
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
ExecStart=/usr/local/bin/cloudflared tunnel --config /etc/cloudflared/config.yml run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cloudflared.service
systemctl start cloudflared.service

echo "✓ Cloudflare Tunnel service created and started"

# Wait a moment and check status
sleep 3
echo ""
echo "Step 6: Checking tunnel status..."
systemctl status cloudflared.service --no-pager | head -15

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Your POS should now be accessible at:"
echo "  https://$DOMAIN"
echo "  https://www.$DOMAIN"
echo ""
echo "The tunnel bypasses port forwarding and works"
echo "with mobile hotspot connections."
echo ""
echo "Service management:"
echo "  sudo systemctl status cloudflared.service"
echo "  sudo systemctl restart cloudflared.service"
echo "  sudo journalctl -u cloudflared.service -f"
echo ""
echo "Note: You may need to update DNS in Cloudflare"
echo "to point to the tunnel. The script attempted this"
echo "automatically, but verify in Cloudflare dashboard."
echo "=========================================="

