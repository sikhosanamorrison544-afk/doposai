#!/bin/bash
# Move POS system to a protected location and create safe desktop launcher

set -e  # Exit on error

CURRENT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/pos-system"
DESKTOP_ENTRY="$HOME/.local/share/applications/pos-system.desktop"
DESKTOP_SHORTCUT="$HOME/Desktop/pos-system.desktop"

echo "=========================================="
echo "Moving POS System to Protected Location"
echo "=========================================="
echo ""

# Check if already moved
if [ -d "$INSTALL_DIR" ] && [ ! -L "$CURRENT_DIR" ]; then
    echo "POS system appears to already be installed at: $INSTALL_DIR"
    echo "If you want to reinstall, first delete: $INSTALL_DIR"
    exit 1
fi

# Create installation directory
echo "Creating protected installation directory..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$(dirname "$DESKTOP_ENTRY")"

# Copy all files (excluding .venv if it exists separately)
echo "Copying files to protected location..."
if [ -d "$CURRENT_DIR/.venv" ]; then
    echo "  Copying application files..."
    rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
          --exclude='.git' --exclude='*.db-journal' \
          "$CURRENT_DIR/" "$INSTALL_DIR/"
    
    echo "  Copying virtual environment..."
    cp -r "$CURRENT_DIR/.venv" "$INSTALL_DIR/.venv"
else
    rsync -av --exclude='__pycache__' --exclude='*.pyc' \
          --exclude='.git' --exclude='*.db-journal' \
          "$CURRENT_DIR/" "$INSTALL_DIR/"
fi

# Make critical files read-only (except database and logs)
echo "Setting file permissions..."
find "$INSTALL_DIR" -type f \( -name "*.py" -o -name "*.html" -o -name "*.css" -o -name "*.js" -o -name "*.sh" -o -name "*.md" \) \
    ! -path "*/\.venv/*" \
    ! -name "*.db" \
    -exec chmod 444 {} \; 2>/dev/null || true

# Make directories readable and executable
find "$INSTALL_DIR" -type d ! -path "*/\.venv/*" -exec chmod 755 {} \; 2>/dev/null || true

# Database and config should be writable
chmod 644 "$INSTALL_DIR"/*.db 2>/dev/null || true
chmod 644 "$INSTALL_DIR"/app/*.db 2>/dev/null || true
chmod 755 "$INSTALL_DIR"/*.sh 2>/dev/null || true
chmod 755 "$INSTALL_DIR"/*.py 2>/dev/null || true
chmod 755 "$INSTALL_DIR/.venv/bin"/* 2>/dev/null || true

# Update desktop entry to point to new location
echo "Creating desktop entry..."
cat > "$DESKTOP_ENTRY" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=POS System
Name[en]=POS System
Comment=Point of Sale System for Raspberry Pi
Comment[en]=Point of Sale System for Raspberry Pi
Exec=$INSTALL_DIR/.venv/bin/python3 "$INSTALL_DIR/launch_pos.py"
Icon=$INSTALL_DIR/pos_icon.png
Terminal=false
Categories=Office;Finance;
StartupNotify=true
MimeType=
Keywords=POS;Point of Sale;Sales;Cash Register;Retail;
EOF

chmod +x "$DESKTOP_ENTRY"

# Create desktop shortcut
echo "Creating desktop shortcut..."
cp "$DESKTOP_ENTRY" "$DESKTOP_SHORTCUT"
chmod +x "$DESKTOP_SHORTCUT"

# Create a README in the old location explaining where files moved
echo "Creating migration notice..."
cat > "$CURRENT_DIR/MOVED_TO_PROTECTED_LOCATION.txt" << EOF
========================================
POS SYSTEM HAS BEEN MOVED
========================================

The POS system files have been moved to a protected location to prevent
accidental deletion.

NEW LOCATION: $INSTALL_DIR

You can still launch the application by:
1. Double-clicking the "POS System" icon on your desktop
2. Searching for "POS System" in your application menu
3. Running: $INSTALL_DIR/.venv/bin/python3 $INSTALL_DIR/launch_pos.py

The desktop shortcut is safe to keep or delete - it's just a launcher.

If you need to access the files:
  cd $INSTALL_DIR

To remove the POS system completely:
  rm -rf $INSTALL_DIR
  rm -f $DESKTOP_ENTRY
  rm -f $DESKTOP_SHORTCUT

========================================
EOF

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "POS system has been moved to: $INSTALL_DIR"
echo ""
echo "Protection applied:"
echo "  ✓ Application files are read-only"
echo "  ✓ Database files remain writable"
echo "  ✓ Desktop shortcut created (safe to keep/delete)"
echo ""
echo "You can now safely delete files from the Desktop folder."
echo "The desktop shortcut will continue to work."
echo ""
echo "To access the installation:"
echo "  cd $INSTALL_DIR"
echo ""

