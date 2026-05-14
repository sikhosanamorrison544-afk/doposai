#!/bin/bash
# Test script to verify desktop entry works

echo "Testing POS System Desktop Launch..."
echo "===================================="
echo ""

# Check if desktop entry exists
if [ ! -f ~/Desktop/pos-system.desktop ]; then
    echo "❌ Desktop shortcut not found at ~/Desktop/pos-system.desktop"
    exit 1
fi

echo "✓ Desktop shortcut found"

# Check if it's executable
if [ ! -x ~/Desktop/pos-system.desktop ]; then
    echo "⚠ Desktop shortcut is not executable, fixing..."
    chmod +x ~/Desktop/pos-system.desktop
fi

# Check if it's trusted
if command -v gio &> /dev/null; then
    TRUSTED=$(gio info ~/Desktop/pos-system.desktop 2>/dev/null | grep -i "metadata::trusted" | grep -i "true" || echo "")
    if [ -z "$TRUSTED" ]; then
        echo "⚠ Desktop shortcut is not marked as trusted, fixing..."
        gio set ~/Desktop/pos-system.desktop metadata::trusted true
        echo "✓ Marked as trusted"
    else
        echo "✓ Desktop shortcut is trusted"
    fi
fi

# Extract and test the Exec command
EXEC_LINE=$(grep "^Exec=" ~/Desktop/pos-system.desktop | cut -d'=' -f2-)
if [ -z "$EXEC_LINE" ]; then
    echo "❌ Could not find Exec line in desktop entry"
    exit 1
fi

echo "✓ Exec command found: $EXEC_LINE"
echo ""

# Test if the Python script exists and is executable
LAUNCH_SCRIPT="/home/morrison/Desktop/pos/launch_pos.py"
if [ ! -f "$LAUNCH_SCRIPT" ]; then
    echo "❌ Launch script not found at $LAUNCH_SCRIPT"
    exit 1
fi

if [ ! -x "$LAUNCH_SCRIPT" ]; then
    echo "⚠ Launch script is not executable, fixing..."
    chmod +x "$LAUNCH_SCRIPT"
fi

echo "✓ Launch script exists and is executable"
echo ""

# Check Python executable
PYTHON_EXE="/home/morrison/Desktop/pos/.venv/bin/python3"
if [ ! -f "$PYTHON_EXE" ]; then
    echo "⚠ Virtual environment Python not found, will use system python3"
    PYTHON_EXE="python3"
else
    echo "✓ Virtual environment Python found"
fi

# Test Python can run
if ! "$PYTHON_EXE" --version > /dev/null 2>&1; then
    echo "❌ Python executable not working: $PYTHON_EXE"
    exit 1
fi

echo "✓ Python executable works"
echo ""

echo "===================================="
echo "✅ All checks passed!"
echo ""
echo "The desktop entry should work. Try double-clicking the"
echo "POS System icon on your desktop."
echo ""
echo "If it still doesn't work:"
echo "1. Right-click the desktop icon"
echo "2. Select 'Properties' or 'Allow Launching'"
echo "3. Make sure 'Allow executing file as program' is checked"
echo ""

