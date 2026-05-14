#!/bin/bash
# Fix desktop entry launch issues

echo "Fixing POS System Desktop Launch..."
echo "==================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_SHORTCUT="$HOME/Desktop/pos-system.desktop"

# Make sure desktop shortcut exists
if [ ! -f "$DESKTOP_SHORTCUT" ]; then
    echo "Creating desktop shortcut..."
    bash "$SCRIPT_DIR/create_desktop_entry.sh"
fi

# Make executable
chmod +x "$DESKTOP_SHORTCUT"
echo "✓ Made desktop shortcut executable"

# Mark as trusted
if command -v gio &> /dev/null; then
    gio set "$DESKTOP_SHORTCUT" metadata::trusted true 2>/dev/null
    echo "✓ Marked desktop shortcut as trusted"
fi

# Make launch script executable
chmod +x "$SCRIPT_DIR/launch_pos.py"
echo "✓ Made launch script executable"

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
    echo "✓ Updated desktop database"
fi

echo ""
echo "==================================="
echo "✅ Fix complete!"
echo ""
echo "The desktop entry has been fixed. Try double-clicking"
echo "the POS System icon on your desktop now."
echo ""
echo "If it still doesn't work, try:"
echo "1. Right-click the desktop icon"
echo "2. Look for 'Properties', 'Allow Launching', or 'Make Executable'"
echo "3. Enable execution permissions"
echo ""
echo "Or run the POS system from terminal:"
echo "  cd $SCRIPT_DIR"
echo "  python3 launch_pos.py"
echo ""

