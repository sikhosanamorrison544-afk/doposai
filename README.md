## Raspberry Pi Offline-First POS System

This is a small, **offline-first Point of Sale (POS)** system optimized for **Raspberry Pi**.
It runs completely on `localhost` with a **FastAPI** backend, **SQLite** database,
and a lightweight **HTML/CSS/JS** frontend optimized for a 7-inch touchscreen.

### Features
- **User authentication** with roles: Admin, Cashier
- **Product management** (CRUD, categories, barcode, stock, cost & selling price)
- **Fast POS screen** with:
  - USB barcode scanner (HID, acts as keyboard input)
  - Quantity adjustment & discounts
  - Multiple payments: Cash, Mobile Money, Card (manual)
- **Inventory management** with real-time stock updates
- **Receipt printing** via ESC/POS thermal printer
- **Customer management** with credit sales
- **Sales, profit, and inventory reports** with date filters
- **Offline-only**, uses local SQLite file

### Project Structure
- `app/` – FastAPI backend
- `templates/` – HTML templates (Jinja2-compatible)
- `static/` – CSS and JS assets

### Installation (Raspberry Pi OS)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

cd /home/morrison/Desktop/pos
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Initialize the database and create an initial admin user:

```bash
python3 -m app.init_db
```

### Desktop Application Setup

**Quick Setup (Recommended):**
```bash
cd /home/morrison/Desktop/pos
./create_desktop_entry.sh
cp ~/.local/share/applications/pos-system.desktop ~/Desktop/
```

Now you can launch the POS system by:
- **Double-clicking the "POS System" icon on your desktop**
- **Searching for "POS System" in your application menu**

The application will automatically:
- Start the server
- Open your browser to `http://localhost:8000`
- Handle all startup and shutdown operations

For detailed instructions, see [DESKTOP_APP_GUIDE.md](DESKTOP_APP_GUIDE.md).

Run the server:

**Option 1: Using the startup script (recommended)**
```bash
./start_server.sh
```

**Option 2: Direct uvicorn command**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Accessing the POS system:**

- **On the Raspberry Pi:** `http://localhost:8000`
- **From other devices on the same network:** 
  1. Find the Pi's IP address: `./get_ip.sh` or check the output when starting the server
  2. Access at: `http://<PI_IP_ADDRESS>:8000`
  3. Or try: `http://<hostname>.local:8000`

**Network Access Requirements:**
- The server must be started with `--host 0.0.0.0` (already included in scripts)
- If using a firewall, allow port 8000:
  ```bash
  sudo ufw allow 8000/tcp
  ```
- All devices must be on the same Wi-Fi/network

### Systemd Service (Auto-start at Boot)

Create a service file, e.g. `/etc/systemd/system/pos.service`:

```ini
[Unit]
Description=Raspberry Pi Offline POS
After=network.target

[Service]
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/Desktop/pos
Environment="PATH=/home/YOUR_USERNAME/Desktop/pos/.venv/bin"
ExecStart=/home/YOUR_USERNAME/Desktop/pos/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pos.service
sudo systemctl start pos.service
```

### ESC/POS Receipt Printing

The backend includes a minimal helper (`app/escpos_printer.py`) that writes raw
ESC/POS commands to a device file (e.g. `/dev/usb/lp0`).

Configure the printer device path in `app/config.py`. The POS sale endpoint
demonstrates how to print a receipt after a successful sale.


