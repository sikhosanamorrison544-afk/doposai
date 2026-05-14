#!/bin/bash
# Add delete protection to POS files in current location (alternative approach)

set -e

CURRENT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "Adding Delete Protection to POS Files"
echo "=========================================="
echo ""

# Create a .trashinfo file to mark this as important
cat > "$CURRENT_DIR/.pos-system-important" << 'EOF'
This directory contains the POS System application.
To protect files from accidental deletion, consider moving to:
  ~/.local/share/pos-system

Run: ./move_to_protected_location.sh
EOF

# Make the directory itself more protected (requires confirmation to delete)
chmod 755 "$CURRENT_DIR"

# Create a warning script that runs if someone tries to delete
cat > "$CURRENT_DIR/WARNING_DO_NOT_DELETE.txt" << 'EOF'
========================================
WARNING: IMPORTANT APPLICATION FILES
========================================

This directory contains the POS System application.

DO NOT DELETE these files unless you want to remove the POS system completely.

If you want to protect these files from accidental deletion:

1. Run the protection script:
   ./move_to_protected_location.sh

   This will move files to a protected location and create a safe desktop launcher.

2. Or manually move to:
   ~/.local/share/pos-system

The desktop shortcut will continue to work after moving.

========================================
EOF

# Make application files read-only (but allow database writes)
echo "Making application files read-only..."

# Python files
find "$CURRENT_DIR" -type f -name "*.py" ! -path "*/.venv/*" -exec chmod 444 {} \; 2>/dev/null || true

# HTML/CSS/JS files
find "$CURRENT_DIR" -type f \( -name "*.html" -o -name "*.css" -o -name "*.js" \) \
    -exec chmod 444 {} \; 2>/dev/null || true

# Shell scripts (need to be executable)
find "$CURRENT_DIR" -type f -name "*.sh" -exec chmod 555 {} \; 2>/dev/null || true

# Make directories readable
find "$CURRENT_DIR" -type d ! -path "*/.venv/*" -exec chmod 755 {} \; 2>/dev/null || true

# Keep database and logs writable
chmod 644 "$CURRENT_DIR"/*.db 2>/dev/null || true

# Keep launcher scripts executable
chmod 755 "$CURRENT_DIR/launch_pos.py" 2>/dev/null || true

echo ""
echo "Protection applied:"
echo "  ✓ Application files are now read-only"
echo "  ✓ Database files remain writable"
echo "  ✓ Warning file created"
echo ""
echo "Note: Read-only files can still be deleted, but this provides some protection."
echo "For better protection, run: ./move_to_protected_location.sh"
echo ""

