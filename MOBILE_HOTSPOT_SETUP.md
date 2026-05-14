# Mobile Hotspot Setup Guide

## The Problem

Your Raspberry Pi is connected via **mobile hotspot** (Econet ISP). This means:

- ❌ **Port forwarding is NOT possible** - Mobile hotspots use Carrier-Grade NAT (CGNAT)
- ❌ You don't have a direct public IP address
- ❌ Traditional port forwarding methods won't work
- ❌ Let's Encrypt verification will fail without port forwarding

## The Solution: Cloudflare Tunnel

**Cloudflare Tunnel** (formerly Argo Tunnel) creates a secure connection from your Pi to Cloudflare, bypassing all port forwarding requirements.

### Benefits:
- ✅ Works with mobile hotspot
- ✅ No port forwarding needed
- ✅ Free SSL certificate (automatic)
- ✅ Secure connection
- ✅ Works behind any NAT/firewall
- ✅ Free to use

## Setup Instructions

### Step 1: Run the Setup Script

```bash
cd /home/morrison/Desktop/pos
sudo ./setup_cloudflare_tunnel.sh
```

This script will:
1. Install cloudflared (Cloudflare Tunnel client)
2. Authenticate with Cloudflare
3. Create a tunnel
4. Configure DNS routes
5. Set up systemd service

### Step 2: Authenticate with Cloudflare

When prompted, you'll need to:
1. Log into your Cloudflare account
2. Authorize the tunnel
3. The script will continue automatically

### Step 3: Verify Setup

```bash
# Check tunnel status
sudo systemctl status cloudflared.service

# View tunnel logs
sudo journalctl -u cloudflared.service -f

# Test access
curl https://doposai.com
```

## Manual Setup (Alternative)

If the automated script doesn't work, follow these steps:

### 1. Install cloudflared

```bash
# For ARM64 (Raspberry Pi 4/5)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared-linux-arm64.deb

# For ARM (older Pi)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm.deb
sudo dpkg -i cloudflared-linux-arm.deb
```

### 2. Login to Cloudflare

```bash
cloudflared tunnel login
```

This will open a browser or show a URL. Log in and authorize.

### 3. Create Tunnel

```bash
cloudflared tunnel create pos-tunnel
```

### 4. Configure Tunnel

Create `/etc/cloudflared/config.yml`:

```yaml
tunnel: <tunnel-uuid>
credentials-file: /home/morrison/.cloudflared/<tunnel-uuid>.json

ingress:
  - hostname: doposai.com
    service: http://localhost:8000
  - hostname: www.doposai.com
    service: http://localhost:8000
  - service: http_status:404
```

Replace `<tunnel-uuid>` with the UUID from step 3.

### 5. Create DNS Route

```bash
cloudflared tunnel route dns pos-tunnel doposai.com
cloudflared tunnel route dns pos-tunnel www.doposai.com
```

### 6. Create Systemd Service

Create `/etc/systemd/system/cloudflared.service`:

```ini
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=morrison
ExecStart=/usr/local/bin/cloudflared tunnel --config /etc/cloudflared/config.yml run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cloudflared.service
sudo systemctl start cloudflared.service
```

## Verify Everything Works

1. **Check tunnel is running:**
   ```bash
   sudo systemctl status cloudflared.service
   ```

2. **Check DNS:**
   ```bash
   host doposai.com
   ```
   Should show Cloudflare IPs (this is normal with tunnel)

3. **Test HTTPS access:**
   ```bash
   curl https://doposai.com
   ```
   Should return your POS login page

4. **Access in browser:**
   - Visit: https://doposai.com
   - Should see your POS system with SSL certificate

## Troubleshooting

### Tunnel Not Starting

```bash
# Check logs
sudo journalctl -u cloudflared.service -n 50

# Common issues:
# - Credentials file not found: Run `cloudflared tunnel login`
# - DNS route not created: Run DNS route commands
# - Config file error: Check /etc/cloudflared/config.yml
```

### DNS Not Working

1. Check Cloudflare dashboard:
   - Go to DNS → Records
   - Verify `doposai.com` and `www.doposai.com` exist
   - They should be CNAME records pointing to the tunnel

2. If records don't exist, create them:
   ```bash
   cloudflared tunnel route dns pos-tunnel doposai.com
   cloudflared tunnel route dns pos-tunnel www.doposai.com
   ```

### SSL Certificate Issues

Cloudflare Tunnel automatically provides SSL certificates. If you see certificate errors:

1. Check tunnel is running
2. Verify DNS is pointing to Cloudflare
3. Wait a few minutes for certificate propagation
4. Check Cloudflare SSL/TLS settings (should be "Full" or "Full (strict)")

### Connection Timeout

If you can't access the site:

1. **Check POS is running:**
   ```bash
   sudo systemctl status pos.service
   curl http://localhost:8000
   ```

2. **Check tunnel is running:**
   ```bash
   sudo systemctl status cloudflared.service
   ```

3. **Check tunnel logs:**
   ```bash
   sudo journalctl -u cloudflared.service -f
   ```

## Service Management

```bash
# Start tunnel
sudo systemctl start cloudflared.service

# Stop tunnel
sudo systemctl stop cloudflared.service

# Restart tunnel
sudo systemctl restart cloudflared.service

# View logs
sudo journalctl -u cloudflared.service -f

# Check status
sudo systemctl status cloudflared.service
```

## Advantages Over Port Forwarding

1. **Works with mobile hotspot** - No need for router access
2. **No port forwarding** - Works behind any NAT
3. **Automatic SSL** - Cloudflare provides certificates
4. **More secure** - Traffic is encrypted end-to-end
5. **Free** - No additional costs
6. **Easy setup** - One script does everything

## Next Steps

After setting up the tunnel:

1. ✅ Tunnel is running
2. ✅ DNS is configured
3. ✅ SSL is automatic (via Cloudflare)
4. ✅ Access your POS at https://doposai.com

**No port forwarding needed!** The tunnel handles everything.

