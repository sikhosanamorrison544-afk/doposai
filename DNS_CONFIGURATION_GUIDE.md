# DNS Configuration Guide for doposai.com

## Your IP Addresses

- **Public IP Address**: `102.128.79.226`
- **Local IP Address**: `10.120.67.204`

## DNS Configuration Steps

### Step 1: Access Your Domain Registrar

1. Log in to your domain registrar's control panel (where you purchased doposai.com)
2. Navigate to DNS Management or DNS Settings
3. Look for "DNS Records", "DNS Zone", or "Manage DNS"

### Step 2: Add A Records

You need to add **TWO A records**:

#### Record 1: Main Domain
- **Type**: A
- **Name/Host**: `@` or `doposai.com` or leave blank (depends on registrar)
- **Value/Points to**: `102.128.79.226`
- **TTL**: `3600` (or default)

#### Record 2: WWW Subdomain
- **Type**: A
- **Name/Host**: `www`
- **Value/Points to**: `102.128.79.226`
- **TTL**: `3600` (or default)

### Step 3: Common Registrar Instructions

#### Namecheap
1. Go to Domain List → Manage → Advanced DNS
2. Add A Record: Host `@`, Value `102.128.79.226`, TTL `Automatic`
3. Add A Record: Host `www`, Value `102.128.79.226`, TTL `Automatic`

#### GoDaddy
1. Go to My Products → DNS
2. Add: Type `A`, Name `@`, Value `102.128.79.226`, TTL `600`
3. Add: Type `A`, Name `www`, Value `102.128.79.226`, TTL `600`

#### Google Domains
1. Go to DNS → Custom records
2. Add: Type `A`, Name `@`, Data `102.128.79.226`
3. Add: Type `A`, Name `www`, Data `102.128.79.226`

#### Cloudflare
1. Go to DNS → Records
2. Add A record: Name `@`, IPv4 address `102.128.79.226`, Proxy status `DNS only` (gray cloud)
3. Add A record: Name `www`, IPv4 address `102.128.79.226`, Proxy status `DNS only`

### Step 4: Verify DNS Configuration

After adding the records, wait 5-60 minutes, then verify:

```bash
# Check DNS propagation
host doposai.com
nslookup doposai.com
dig doposai.com

# Or use online tools:
# https://www.whatsmydns.net/#A/doposai.com
# https://dnschecker.org/#A/doposai.com
```

You should see `102.128.79.226` in the results.

### Step 5: Run SSL Setup

Once DNS is propagated (you can see your IP when checking), run:

```bash
cd /home/morrison/Desktop/pos
sudo ./setup_ssl.sh
```

## Important Notes

1. **DNS Propagation**: Can take 5 minutes to 48 hours, but usually 15-60 minutes
2. **Port Forwarding**: If behind a router, ensure ports 80 and 443 are forwarded to `10.120.67.204`
3. **Firewall**: Already configured on your Pi
4. **Static IP**: If your public IP changes, you'll need to update the DNS records

## Troubleshooting

### DNS Not Propagating
- Wait longer (up to 48 hours)
- Clear DNS cache: `sudo systemd-resolve --flush-caches`
- Check with multiple DNS servers: `dig @8.8.8.8 doposai.com`

### SSL Certificate Fails
- Ensure DNS is fully propagated
- Ensure port 80 is accessible from internet
- Check firewall: `sudo ufw status`
- Check Nginx: `sudo systemctl status nginx`

## Quick Check Script

Run this to check if DNS is ready:

```bash
cd /home/morrison/Desktop/pos
./check_dns.sh
```

Or manually:
```bash
host doposai.com | grep "102.128.79.226" && echo "✓ DNS is configured!" || echo "✗ DNS not ready yet"
```

