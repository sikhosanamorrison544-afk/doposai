# Network Access Guide

## Quick Start

Your POS system is now configured to be accessible from devices on the same network.

### Current Server IP Address
Your Raspberry Pi's IP address: **10.248.174.204**

### Access URLs
- **From the Pi itself:** `http://localhost:8000`
- **From other devices on your network:** `http://10.248.174.204:8000`
- **Using hostname (may work on some networks):** `http://raspberrypi.local:8000`

## Starting the Server

### Method 1: Use the startup script (Recommended)
```bash
cd /home/morrison/Desktop/pos
./start_server.sh
```

This script will:
- Show your IP address
- Start the server with network access enabled
- Display connection information

### Method 2: Manual start
```bash
cd /home/morrison/Desktop/pos
source .venv/bin/activate  # If using virtual environment
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Important:** Always use `--host 0.0.0.0` to allow network access!

## Finding Your IP Address

Run this command anytime:
```bash
./get_ip.sh
```

Or manually:
```bash
hostname -I
```

## Accessing from Other Devices

### From a Computer/Laptop
1. Make sure the device is on the same Wi-Fi network
2. Open a web browser
3. Navigate to: `http://10.248.174.204:8000`
4. Log in with your credentials

### From a Phone/Tablet
1. Connect your phone/tablet to the same Wi-Fi network
2. Open a web browser (Chrome, Safari, etc.)
3. Type in the address bar: `http://10.248.174.204:8000`
4. Log in with your credentials

### From Another Device on the Network
Any device connected to the same Wi-Fi network can access the POS system using:
```
http://10.248.174.204:8000
```

## Troubleshooting

### Cannot Connect from Other Devices

1. **Check if the server is running:**
   ```bash
   ps aux | grep uvicorn
   ```
   You should see a process running with `--host 0.0.0.0`

2. **Verify the IP address:**
   ```bash
   ./get_ip.sh
   ```
   Make sure you're using the correct IP address.

3. **Check firewall settings:**
   ```bash
   sudo ufw status
   ```
   If UFW is active, allow port 8000:
   ```bash
   sudo ufw allow 8000/tcp
   ```

4. **Verify network connectivity:**
   - Make sure both devices are on the same Wi-Fi network
   - Try pinging the Pi from another device:
     ```bash
     ping 10.248.174.204
     ```

5. **Check if the server is listening on the correct interface:**
   ```bash
   netstat -tlnp | grep 8000
   ```
   You should see `0.0.0.0:8000` (not `127.0.0.1:8000`)

6. **Restart the server:**
   ```bash
   # Stop the current server (Ctrl+C or kill the process)
   ./start_server.sh
   ```

### IP Address Changed

If your Pi's IP address changes (common with DHCP), you can find the new IP by:
```bash
./get_ip.sh
```

Or check your router's admin panel for connected devices.

### Connection Timeout

If you get a connection timeout:
- The server might not be running
- The IP address might be incorrect
- A firewall might be blocking the connection
- The devices might be on different networks

### Security Note

The POS system is currently accessible to anyone on your local network. For production use:
- Use strong passwords for all accounts
- Consider implementing additional security measures if needed
- The system is designed for local network use only

## Running as a Service (Auto-start)

To make the server start automatically on boot, see the README.md file for systemd service setup instructions.

