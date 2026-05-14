#!/bin/bash
# Create a desktop entry for the POS system

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_FILE="$HOME/.local/share/applications/pos-system.desktop"
ICON_PATH="$SCRIPT_DIR/pos_icon.png"

# Try to create icon if it doesn't exist
if [ ! -f "$ICON_PATH" ]; then
    echo "Creating icon..."
    python3 "$SCRIPT_DIR/create_icon.py" 2>/dev/null || echo "Icon creation failed, will use default"
fi

# Use SVG if PNG doesn't exist
if [ ! -f "$ICON_PATH" ]; then
    ICON_PATH="$SCRIPT_DIR/pos_icon.svg"
fi

# Try other icon sizes
if [ ! -f "$ICON_PATH" ]; then
    ICON_PATH="$SCRIPT_DIR/pos_icon_256.png"
fi

if [ ! -f "$ICON_PATH" ]; then
    ICON_PATH="$SCRIPT_DIR/pos_icon_128.png"
fi

# If still no icon, use a system icon
if [ ! -f "$ICON_PATH" ]; then
    ICON_PATH="applications-office"
fi

# Determine Python executable
PYTHON_EXE="$SCRIPT_DIR/.venv/bin/python3"
if [ ! -f "$PYTHON_EXE" ]; then
    PYTHON_EXE="python3"
fi

# Get absolute path to launch script
LAUNCH_SCRIPT="$SCRIPT_DIR/launch_pos.py"
if [ ! -f "$LAUNCH_SCRIPT" ]; then
    echo "Error: launch_pos.py not found at $LAUNCH_SCRIPT"
    exit 1
fi

# Make sure launch script is executable
chmod +x "$LAUNCH_SCRIPT"

# Create .desktop file
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=POS System
Name[en]=POS System
GenericName=Point of Sale System
GenericName[en]=Point of Sale System
Comment=Point of Sale System for retail stores
Comment[en]=Point of Sale System for retail stores
Exec=$PYTHON_EXE "$LAUNCH_SCRIPT"
Path=$SCRIPT_DIR
Icon=$ICON_PATH
Terminal=false
NoDisplay=false
Categories=Office;Finance;Business;
StartupNotify=true
Keywords=POS;Point of Sale;Sales;Cash Register;Retail;Inventory;
MimeType=
EOF

# Make it executable
chmod +x "$DESKTOP_FILE"

# Also create/update desktop shortcut
DESKTOP_SHORTCUT="$HOME/Desktop/pos-system.desktop"
cp "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
chmod +x "$DESKTOP_SHORTCUT"

# Mark desktop shortcut as trusted (required for Linux desktop environments)
if command -v gio &> /dev/null; then
    gio set "$DESKTOP_SHORTCUT" metadata::trusted true 2>/dev/null || true
    echo "✓ Marked desktop shortcut as trusted"
fi

# Also try using chmod +x and update desktop database
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Desktop entry created: $DESKTOP_FILE"
echo "Desktop shortcut created: $DESKTOP_SHORTCUT"
echo ""
echo "The POS System application should now appear in your applications menu"
echo "and on your desktop. Double-click the desktop icon to launch!"

