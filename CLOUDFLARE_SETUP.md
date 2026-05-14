# Cloudflare Configuration for doposai.com

## Current Situation

Your domain is pointing to Cloudflare IPs:
- `104.21.20.128` (Cloudflare)
- `172.67.192.230` (Cloudflare)

This means your domain is using Cloudflare's proxy service.

## Option 1: Disable Cloudflare Proxy (Recommended for Direct Access)

If you want direct access to your Raspberry Pi:

1. **Log into Cloudflare Dashboard**
   - Go to https://dash.cloudflare.com
   - Select your domain `doposai.com`

2. **Go to DNS → Records**

3. **For each A record, click the orange cloud icon to turn it gray**
   - This disables the proxy and points directly to your IP
   - The cloud should be **gray** (DNS only), not **orange** (proxied)

4. **Update A Records:**
   - Record 1: Name `@`, Content `102.128.79.226`, Proxy **OFF** (gray cloud)
   - Record 2: Name `www`, Content `102.128.79.226`, Proxy **OFF** (gray cloud)

5. **Wait 5-15 minutes for changes to propagate**

6. **Verify:**
   ```bash
   cd /home/morrison/Desktop/pos
   ./check_dns.sh
   ```

7. **Run SSL setup:**
   ```bash
   sudo ./AUTO_SSL_SETUP.sh
   ```

## Option 2: Use Cloudflare Proxy (Keep Orange Cloud)

If you want to keep Cloudflare's proxy enabled:

1. **Update A Records in Cloudflare:**
   - Record 1: Name `@`, Content `102.128.79.226`, Proxy **ON** (orange cloud)
   - Record 2: Name `www`, Content `102.128.79.226`, Proxy **ON** (orange cloud)

2. **Configure SSL/TLS:**
   - Go to SSL/TLS → Overview
   - Set encryption mode to **Full** or **Full (strict)**
   - This allows Cloudflare to handle SSL

3. **Note:** With Cloudflare proxy, you'll access via Cloudflare's SSL, not Let's Encrypt directly

## Option 3: Direct DNS (Not Using Cloudflare)

If you're not using Cloudflare and want to point directly:

1. **In your domain registrar's DNS settings:**
   - Remove any Cloudflare nameservers
   - Add A records pointing directly to `102.128.79.226`

2. **Wait for DNS propagation**

3. **Run SSL setup:**
   ```bash
   sudo ./AUTO_SSL_SETUP.sh
   ```

## Recommended: Option 1 (Disable Proxy)

For a simple setup with Let's Encrypt SSL:
- Disable Cloudflare proxy (gray cloud)
- Point directly to your Pi IP
- Use Let's Encrypt for SSL

This gives you:
- Direct connection to your Pi
- Free SSL from Let's Encrypt
- Full control over SSL certificates

## Quick Check

After making changes, verify DNS:
```bash
cd /home/morrison/Desktop/pos
./check_dns.sh
```

You should see: `✓ DNS is configured! Found: 102.128.79.226`

