# Desktop Application Setup Guide

Your POS system has been packaged as a professional desktop application that can be launched with a single click!

## What's Been Created

### 1. Desktop Launcher
- **Location**: `~/Desktop/pos-system.desktop` (on your desktop)
- **Icon**: Custom POS system icon
- **Function**: Launches the server and opens your browser automatically

### 2. Application Menu Entry
- The application appears in your system's application menu
- Search for "POS System" in the menu

### 3. Launch Script
- **File**: `launch_pos.py`
- Handles server startup, browser opening, and cleanup

## How to Use

### Method 1: Double-Click the Desktop Icon
1. Look for the "POS System" icon on your desktop
2. Double-click it
3. The server will start automatically
4. Your browser will open to `http://localhost:8000`
5. The server runs in the background

### Method 2: From Application Menu
1. Open your application menu (usually the menu button or Super key)
2. Search for "POS System"
3. Click the application
4. The server starts and browser opens automatically

### Method 3: Command Line
```bash
cd /home/morrison/Desktop/pos
python3 launch_pos.py
```

## Features

### Automatic Server Management
- ✅ Checks if server is already running
- ✅ Starts server if not running
- ✅ Waits for server to be ready
- ✅ Opens browser automatically
- ✅ Handles cleanup on exit

### Clean Shutdown
- Press `Ctrl+C` in the terminal (if launched from terminal)
- Or close the browser and stop the process from system monitor

## Customization

### Change the Icon
1. Replace `pos_icon.png` with your own icon (512x512 PNG recommended)
2. Or run: `python3 create_icon.py` to regenerate

### Update Desktop Entry
Run the setup script again:
```bash
./create_desktop_entry.sh
```

### Change Server Port
Edit `launch_pos.py` and change:
```python
SERVER_URL = "http://localhost:8000"
```

And update the uvicorn command to use a different port.

## Recreating Desktop Shortcut

If you need to recreate the desktop shortcut:

```bash
cd /home/morrison/Desktop/pos
./create_desktop_entry.sh
cp ~/.local/share/applications/pos-system.desktop ~/Desktop/
chmod +x ~/Desktop/pos-system.desktop
```

## Building a Standalone Executable (Advanced)

For a completely standalone application (includes Python and all dependencies):

```bash
./build_standalone.sh
```

This creates a single executable file in the `dist/` directory. Note: This is optional and may take some time to build.

## Troubleshooting

### Icon Doesn't Appear
- Make sure `pos_icon.png` exists in the pos directory
- Try regenerating: `python3 create_icon.py`

### Application Doesn't Launch
- Check that Python is installed: `python3 --version`
- Verify virtual environment exists: `ls .venv/bin/python3`
- Try running manually: `python3 launch_pos.py`

### Server Doesn't Start
- Check if port 8000 is already in use: `lsof -i :8000`
- Make sure all dependencies are installed: `pip install -r requirements.txt`
- Check for errors in the terminal output

### Browser Doesn't Open
- The script tries to open your default browser
- If it fails, manually navigate to: `http://localhost:8000`
- Check that a default browser is set: `xdg-settings get default-web-browser`

## Professional Features

### What Makes This Professional?
1. **Single-Click Launch**: No command line needed
2. **Custom Icon**: Branded application icon
3. **Automatic Startup**: Server starts automatically
4. **Browser Integration**: Opens automatically
5. **Error Handling**: Checks server status before opening browser
6. **Clean Shutdown**: Proper cleanup on exit
7. **System Integration**: Appears in application menu

### Security Note
The desktop application runs on `localhost` (127.0.0.1) for security. This means:
- Only accessible from the local machine
- More secure than network-accessible server
- Perfect for single-user setups

If you need network access, use `start_server.sh` instead, which runs on `0.0.0.0`.

## Files Created

- `launch_pos.py` - Main launcher script
- `create_icon.py` - Icon generator
- `create_desktop_entry.sh` - Desktop entry creator
- `pos_icon.png` - Application icon (multiple sizes)
- `~/Desktop/pos-system.desktop` - Desktop shortcut
- `~/.local/share/applications/pos-system.desktop` - System menu entry

## Next Steps

1. **Test the Desktop Icon**: Double-click it to ensure it works
2. **Pin to Taskbar/Dock**: Right-click the icon and pin it for quick access
3. **Set as Startup Application**: If you want it to start automatically on boot

## Protecting Files from Accidental Deletion

**Important:** Files on the Desktop can be accidentally deleted. To protect your POS system:

**Recommended:** Move to a protected location:
```bash
./move_to_protected_location.sh
```

This will:
- Move files to `~/.local/share/pos-system` (protected location)
- Create a safe desktop launcher
- Make application files read-only
- Allow you to safely delete the original desktop folder

See [PROTECT_FILES.md](PROTECT_FILES.md) for detailed protection options.

Enjoy your professional POS desktop application! 🎉

