#!/bin/bash
# Complete setup for Gradle + box64 on Raspberry Pi

set -e

echo "=========================================="
echo "Setting up Gradle + box64 for Raspberry Pi"
echo "=========================================="
echo ""

# Check box64
if ! command -v box64 &> /dev/null; then
    echo "❌ box64 is not installed!"
    echo "   Installing box64..."
    wget https://ryanfortner.github.io/box64-debs/box64.list -O /tmp/box64.list
    sudo mv /tmp/box64.list /etc/apt/sources.list.d/box64.list
    wget -qO- https://ryanfortner.github.io/box64-debs/KEY.gpg | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/box64-debs-archive-keyring.gpg
    sudo apt-get update
    sudo apt-get install -y box64
    echo "✅ box64 installed"
else
    echo "✅ box64 is installed: $(box64 --version 2>&1 | head -1)"
fi

# Create wrapper directory
WRAPPER_DIR="$HOME/.local/bin"
mkdir -p "$WRAPPER_DIR"
echo "✅ Wrapper directory: $WRAPPER_DIR"

# Add to PATH in bashrc if not already there
if ! grep -q "$WRAPPER_DIR" ~/.bashrc 2>/dev/null; then
    echo "" >> ~/.bashrc
    echo "# Added by POS setup - box64 wrapper path" >> ~/.bashrc
    echo "export PATH=\"$WRAPPER_DIR:\$PATH\"" >> ~/.bashrc
    echo "✅ Added $WRAPPER_DIR to PATH in ~/.bashrc"
fi

# Update gradle.properties
QUOTATIONS_DIR="/home/morrison/Desktop/quotations"
if [ -d "$QUOTATIONS_DIR" ] && [ -f "$QUOTATIONS_DIR/gradle.properties" ]; then
    cd "$QUOTATIONS_DIR"
    
    # Ensure library path is in jvmargs
    if ! grep -q "java.library.path" gradle.properties; then
        sed -i 's|org.gradle.jvmargs=\(.*\)|org.gradle.jvmargs=\1 -Djava.library.path=/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu|' gradle.properties
        echo "✅ Updated gradle.properties with library path"
    fi
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "To build your Android project, run:"
echo "  /home/morrison/Desktop/pos/run_gradle.sh assemble"
echo ""
echo "Or manually:"
echo "  export LD_LIBRARY_PATH=\"/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:\$LD_LIBRARY_PATH\""
echo "  export BOX64_LD_LIBRARY_PATH=\"/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu\""
echo "  cd /home/morrison/Desktop/quotations"
echo "  ./gradlew assemble"
echo ""

