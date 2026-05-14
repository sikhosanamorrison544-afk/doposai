# Quick Start: Internet Access Setup

## Fast Setup (5 Steps)

### 1. Configure DNS
Point `doposai.com` and `www.doposai.com` to your Raspberry Pi's public IP:
- A Record: `doposai.com` → `YOUR_PUBLIC_IP`
- A Record: `www.doposai.com` → `YOUR_PUBLIC_IP`

Find your IP: `curl ifconfig.me`

### 2. Forward Ports (If Behind Router)
Forward ports 80 and 443 to your Raspberry Pi's local IP.

### 3. Run Setup Script
```bash
cd /home/morrison/Desktop/pos
sudo ./setup_internet_access.sh
```

### 4. Wait for DNS (5 min - 48 hours)
Check: `nslookup doposai.com`

### 5. Setup SSL
```bash
sudo ./setup_ssl.sh
```

## Done! Access at: https://doposai.com

## Common Commands

```bash
# Check service status
sudo systemctl status pos.service

# View logs
sudo journalctl -u pos.service -f

# Restart service
sudo systemctl restart pos.service

# Check SSL certificate
sudo certbot certificates
```

## Full Documentation
See `INTERNET_SETUP_GUIDE.md` for complete details.

