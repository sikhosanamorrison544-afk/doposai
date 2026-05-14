# Port Forwarding Guide

## Current Status

✅ DNS: Configured correctly (points to 102.128.79.226)  
✅ Firewall: Ports 80 and 443 are open  
✅ Nginx: Running and listening on port 80  
✅ POS Service: Running  
⚠️  Port Forwarding: **REQUIRED** - Router needs to forward ports

## Why Port Forwarding is Needed

Your Raspberry Pi is behind a router. The router needs to forward incoming traffic on ports 80 and 443 to your Pi's local IP address.

## Your Network Information

- **Public IP**: 102.128.79.226 (what the internet sees)
- **Local IP**: 10.120.67.204 (your Pi's IP on your network)
- **Router**: Usually at 192.168.1.1 or 192.168.0.1 or 10.0.0.1

## Step-by-Step Port Forwarding

### Step 1: Access Your Router

1. Open a web browser
2. Go to your router's admin panel:
   - Try: http://192.168.1.1
   - Or: http://192.168.0.1
   - Or: http://10.0.0.1
   - Or check your router's manual

3. Log in with admin credentials
   - Default username/password is often on a sticker on the router
   - Common defaults: admin/admin, admin/password, admin/(blank)

### Step 2: Find Port Forwarding Settings

Look for one of these sections:
- **Port Forwarding**
- **Virtual Server**
- **NAT Forwarding**
- **Firewall Rules**
- **Applications & Gaming** (some routers)

### Step 3: Add Port Forwarding Rules

Add **TWO** port forwarding rules:

#### Rule 1: HTTP (Port 80)
- **Service Name**: POS HTTP (or any name)
- **External Port**: 80
- **Internal Port**: 80
- **Protocol**: TCP (or Both)
- **Internal IP**: 10.120.67.204
- **Enable**: Yes

#### Rule 2: HTTPS (Port 443)
- **Service Name**: POS HTTPS (or any name)
- **External Port**: 443
- **Internal Port**: 443
- **Protocol**: TCP (or Both)
- **Internal IP**: 10.120.67.204
- **Enable**: Yes

### Step 4: Save and Apply

1. Click **Save** or **Apply**
2. Wait 1-2 minutes for changes to take effect

### Step 5: Verify Port Forwarding

Test if ports are accessible:

```bash
cd /home/morrison/Desktop/pos

# Test HTTP
curl -s -o /dev/null -w "%{http_code}" http://doposai.com
# Should return: 200

# If accessible, run SSL setup
sudo ./AUTO_SSL_SETUP.sh
```

## Common Router Brands

### TP-Link
1. Go to: **Advanced** → **NAT Forwarding** → **Virtual Servers**
2. Click **Add**
3. Fill in the port forwarding details

### Netgear
1. Go to: **Advanced** → **Port Forwarding / Port Triggering**
2. Click **Add Custom Service**
3. Fill in the details

### ASUS
1. Go to: **WAN** → **Virtual Server / Port Forwarding**
2. Click **Add Profile**
3. Fill in the details

### Linksys
1. Go to: **Connectivity** → **Router Settings** → **Port Forwarding**
2. Click **Add**
3. Fill in the details

### D-Link
1. Go to: **Advanced** → **Port Forwarding**
2. Click **Add Rule**
3. Fill in the details

## Troubleshooting

### Port Forwarding Not Working?

1. **Check Pi's IP hasn't changed:**
   ```bash
   hostname -I
   ```
   If it changed, update the port forwarding rule

2. **Check firewall on router:**
   - Some routers have a firewall that blocks forwarded ports
   - Look for "Firewall" settings and allow ports 80/443

3. **Check if Pi has static IP:**
   - Your Pi's IP might change if using DHCP
   - Consider setting a static IP for your Pi

4. **Test from outside your network:**
   - Use your phone's mobile data (not WiFi)
   - Visit: http://doposai.com
   - Should see your POS login page

### Still Can't Access?

1. **Check router logs** for blocked connections
2. **Disable router firewall temporarily** to test
3. **Check ISP restrictions** - some ISPs block port 80/443
4. **Try different external ports** (e.g., 8080, 8443) if ISP blocks standard ports

## Alternative: Use Different Ports

If your ISP blocks ports 80/443, you can use alternative ports:

1. Forward port 8080 → 10.120.67.204:80
2. Forward port 8443 → 10.120.67.204:443
3. Access via: http://doposai.com:8080

However, Let's Encrypt requires port 80 for verification, so you'd need to:
- Temporarily forward port 80 for SSL setup
- Or use a different SSL provider

## After Port Forwarding Works

Once port forwarding is configured and working:

```bash
cd /home/morrison/Desktop/pos
sudo ./AUTO_SSL_SETUP.sh
```

This will:
1. Verify DNS is correct ✓
2. Obtain SSL certificate from Let's Encrypt
3. Configure Nginx with HTTPS
4. Set up automatic renewal

Then access your POS at: **https://doposai.com**

