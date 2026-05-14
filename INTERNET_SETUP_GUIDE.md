# Complete Internet Setup Guide for doposai.com

This guide will help you set up your POS system to be accessible securely over the internet via the domain **doposai.com**.

## Prerequisites

- Raspberry Pi with your POS system installed
- Domain name: **doposai.com** (already purchased)
- Static public IP address OR dynamic DNS service
- SSH access to your Raspberry Pi
- Root/sudo access on the Raspberry Pi

## Overview

The setup includes:
1. **Nginx** as a reverse proxy
2. **Let's Encrypt** for free SSL certificates
3. **Systemd services** for automatic startup
4. **Firewall configuration** (UFW)
5. **Secure authentication** (already implemented)

## Step-by-Step Setup

### Step 1: Prepare Your Raspberry Pi

1. **Update your system:**
   ```bash
   sudo apt-get update
   sudo apt-get upgrade -y
   ```

2. **Ensure your POS is working locally:**
   ```bash
   cd /home/morrison/Desktop/pos
   source .venv/bin/activate
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Test it at `http://localhost:8000`

### Step 2: Configure DNS

You need to point your domain to your Raspberry Pi's public IP address.

1. **Find your public IP address:**
   ```bash
   curl ifconfig.me
   ```
   Or visit: https://whatismyipaddress.com/

2. **Configure DNS records** in your domain registrar's control panel:
   - **A Record**: `doposai.com` → Your public IP address
   - **A Record**: `www.doposai.com` → Your public IP address

3. **Wait for DNS propagation** (can take 5 minutes to 48 hours):
   ```bash
   nslookup doposai.com
   ```
   When it shows your IP address, DNS is ready.

### Step 3: Run the Setup Script

1. **Make the setup script executable:**
   ```bash
   cd /home/morrison/Desktop/pos
   chmod +x setup_internet_access.sh
   ```

2. **Run the setup script:**
   ```bash
   sudo ./setup_internet_access.sh
   ```

   This script will:
   - Install Nginx, Certbot, and UFW
   - Generate a secure JWT secret key
   - Create systemd service files
   - Configure Nginx reverse proxy
   - Set up firewall rules

### Step 4: Configure Port Forwarding (If Behind Router)

If your Raspberry Pi is behind a router, you need to forward ports:

1. **Access your router's admin panel** (usually `192.168.1.1` or `192.168.0.1`)

2. **Forward these ports:**
   - **Port 80** (HTTP) → Your Raspberry Pi's local IP
   - **Port 443** (HTTPS) → Your Raspberry Pi's local IP
   - **Port 22** (SSH) → Your Raspberry Pi's local IP (optional, for remote access)

3. **Find your Raspberry Pi's local IP:**
   ```bash
   hostname -I
   ```

### Step 5: Set Up SSL Certificate

**Wait until DNS is fully propagated** (check with `nslookup doposai.com`), then:

1. **Make the SSL setup script executable:**
   ```bash
   chmod +x setup_ssl.sh
   ```

2. **Run the SSL setup:**
   ```bash
   sudo ./setup_ssl.sh
   ```

   This will:
   - Obtain SSL certificate from Let's Encrypt
   - Configure automatic renewal
   - Set up HTTPS redirect

### Step 6: Start the Services

1. **Start the POS service:**
   ```bash
   sudo systemctl start pos.service
   sudo systemctl enable pos.service
   ```

2. **Check service status:**
   ```bash
   sudo systemctl status pos.service
   ```

### Step 7: Verify Everything Works

1. **Test locally:**
   ```bash
   curl http://localhost:8000
   ```

2. **Test via domain (HTTP):**
   ```bash
   curl http://doposai.com
   ```

3. **Test via domain (HTTPS):**
   ```bash
   curl https://doposai.com
   ```

4. **Open in browser:**
   - Visit: `https://doposai.com`
   - You should see the POS login page
   - The connection should be secure (green padlock)

## Manual Setup (Alternative)

If you prefer to set up manually instead of using the script:

### 1. Install Required Packages

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx ufw
```

### 2. Generate JWT Secret Key

```bash
cd /home/morrison/Desktop/pos
python3 generate_secret_key.py
```

Copy the output and add it to `.env` file:
```bash
echo "JWT_SECRET_KEY=your-generated-key-here" >> .env
chmod 600 .env
```

### 3. Configure Firewall

```bash
sudo ufw enable
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
```

### 4. Install Systemd Services

```bash
sudo cp systemd/pos.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pos.service
sudo systemctl start pos.service
```

### 5. Configure Nginx

```bash
sudo cp nginx/pos.conf /etc/nginx/sites-available/pos
sudo ln -s /etc/nginx/sites-available/pos /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### 6. Obtain SSL Certificate

```bash
sudo certbot --nginx -d doposai.com -d www.doposai.com
```

## Security Considerations

### 1. Strong Passwords

Ensure all user accounts have strong passwords:
- Use the admin panel to manage users
- Require complex passwords (mix of letters, numbers, symbols)

### 2. Regular Updates

Keep your system updated:
```bash
sudo apt-get update && sudo apt-get upgrade -y
```

### 3. Monitor Logs

Check for suspicious activity:
```bash
# POS application logs
sudo journalctl -u pos.service -f

# Nginx access logs
sudo tail -f /var/log/nginx/pos_access.log

# Nginx error logs
sudo tail -f /var/log/nginx/pos_error.log
```

### 4. Backup Regularly

Your database is at `/home/morrison/Desktop/pos/pos.db`. Back it up regularly:
```bash
# Create backup script
cat > /home/morrison/Desktop/pos/backup_db.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/morrison/Desktop/pos/backups"
mkdir -p "$BACKUP_DIR"
cp /home/morrison/Desktop/pos/pos.db "$BACKUP_DIR/pos_$(date +%Y%m%d_%H%M%S).db"
# Keep only last 30 days
find "$BACKUP_DIR" -name "pos_*.db" -mtime +30 -delete
EOF

chmod +x /home/morrison/Desktop/pos/backup_db.sh

# Add to crontab (daily at 2 AM)
(crontab -l 2>/dev/null; echo "0 2 * * * /home/morrison/Desktop/pos/backup_db.sh") | crontab -
```

## Troubleshooting

### Issue: "Connection refused" when accessing domain

**Solutions:**
1. Check if DNS is propagated: `nslookup doposai.com`
2. Check if port forwarding is configured on your router
3. Check firewall: `sudo ufw status`
4. Check if POS service is running: `sudo systemctl status pos.service`
5. Check Nginx: `sudo systemctl status nginx`

### Issue: SSL certificate fails to obtain

**Solutions:**
1. Ensure DNS is fully propagated
2. Ensure port 80 is accessible from internet
3. Check Nginx is running: `sudo systemctl status nginx`
4. Check Let's Encrypt rate limits: https://letsencrypt.org/docs/rate-limits/

### Issue: "502 Bad Gateway"

**Solutions:**
1. Check if POS service is running: `sudo systemctl status pos.service`
2. Check POS logs: `sudo journalctl -u pos.service -n 50`
3. Verify POS is listening on port 8000: `sudo netstat -tlnp | grep 8000`
4. Check Nginx error log: `sudo tail -f /var/log/nginx/pos_error.log`

### Issue: Can't login / Authentication fails

**Solutions:**
1. Check JWT_SECRET_KEY is set in `.env` file
2. Restart POS service: `sudo systemctl restart pos.service`
3. Check if user exists in database
4. Clear browser cache and cookies

### Issue: Service won't start

**Solutions:**
1. Check service logs: `sudo journalctl -u pos.service -n 100`
2. Verify virtual environment exists: `ls -la .venv`
3. Check file permissions: `ls -la /home/morrison/Desktop/pos`
4. Verify Python dependencies: `source .venv/bin/activate && pip list`

## Maintenance

### Update SSL Certificate (Automatic)

Certbot automatically renews certificates. Check status:
```bash
sudo certbot certificates
```

Manual renewal test:
```bash
sudo certbot renew --dry-run
```

### Restart Services

```bash
# Restart POS
sudo systemctl restart pos.service

# Restart Nginx
sudo systemctl restart nginx
```

### View Service Logs

```bash
# POS service
sudo journalctl -u pos.service -f

# Nginx
sudo tail -f /var/log/nginx/pos_access.log
sudo tail -f /var/log/nginx/pos_error.log
```

## Dynamic IP Address (Optional)

If you don't have a static IP, use a dynamic DNS service:

1. **Sign up for a service** like:
   - DuckDNS (free): https://www.duckdns.org/
   - No-IP (free tier): https://www.noip.com/
   - Dynu (free): https://www.dynu.com/

2. **Install update client:**
   ```bash
   # Example for DuckDNS
   sudo apt-get install -y curl
   ```

3. **Create update script:**
   ```bash
   cat > /home/morrison/update_dns.sh << 'EOF'
   #!/bin/bash
   # Update DuckDNS (replace with your token and domain)
   curl "https://www.duckdns.org/update?domains=yourdomain&token=your-token&ip="
   EOF
   chmod +x /home/morrison/Desktop/pos/update_dns.sh
   ```

4. **Add to crontab (every 5 minutes):**
   ```bash
   (crontab -l 2>/dev/null; echo "*/5 * * * * /home/morrison/Desktop/pos/update_dns.sh") | crontab -
   ```

## Access Your POS

Once everything is set up:

- **URL**: https://doposai.com
- **Login**: Use your existing POS credentials
- **All features**: Sales, inventory, admin, etc. work as before

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review service logs
3. Verify DNS and network configuration
4. Ensure all services are running

---

**Setup Complete!** Your POS is now accessible securely over the internet at **https://doposai.com**

