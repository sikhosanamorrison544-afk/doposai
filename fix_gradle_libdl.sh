#!/bin/bash
# Fix libdl.so.2 issue for Gradle/Android builds on Raspberry Pi
# Note: AAPT2 is x86-64 only and requires box64 for ARM64 systems

set -e

echo "=========================================="
echo "Fixing Gradle Build for Raspberry Pi"
echo "=========================================="
echo ""

# Check architecture
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo "⚠ This script is designed for ARM64 (Raspberry Pi)"
fi

# Check if box64 is installed (required for x86-64 AAPT2 on ARM64)
if ! command -v box64 &> /dev/null; then
    echo ""
    echo "⚠ box64 is not installed!"
    echo "   AAPT2 is x86-64 only and requires box64 to run on ARM64."
    echo ""
    read -p "Do you want to install box64? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing box64..."
        # Add box64 repository and install
        sudo apt-get update
        sudo apt-get install -y wget
        wget https://ryanfortner.github.io/box64-debs/box64.list -O /tmp/box64.list
        sudo mv /tmp/box64.list /etc/apt/sources.list.d/box64.list
        wget -qO- https://ryanfortner.github.io/box64-debs/KEY.gpg | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/box64-debs-archive-keyring.gpg
        sudo apt-get update
        sudo apt-get install -y box64
        echo "✅ box64 installed"
    else
        echo "⚠ Continuing without box64 - AAPT2 may still fail"
    fi
else
    echo "✅ box64 is installed"
fi

# Check if library exists
if [ ! -f "/lib/aarch64-linux-gnu/libdl.so.2" ] && [ ! -f "/usr/lib/aarch64-linux-gnu/libdl.so.2" ]; then
    echo "❌ libdl.so.2 not found. Installing libc6..."
    sudo apt-get update
    sudo apt-get install -y libc6
    echo "✅ libc6 installed"
else
    echo "✅ libdl.so.2 found"
fi

# Find the actual library location
LIB_PATH=$(find /lib /usr/lib -name "libdl.so.2" 2>/dev/null | head -1)

if [ -z "$LIB_PATH" ]; then
    echo "❌ Could not find libdl.so.2"
    exit 1
fi

echo "Library found at: $LIB_PATH"
echo ""

# Check if we're in the quotations directory
if [ -d "/home/morrison/Desktop/quotations" ]; then
    cd /home/morrison/Desktop/quotations
    
    # Update gradle.properties to include library path in jvmargs
    if [ -f "gradle.properties" ]; then
        # Check if jvmargs already has library path
        if grep -q "org.gradle.jvmargs" gradle.properties && ! grep -q "java.library.path" gradle.properties; then
            echo "Updating gradle.properties to include library path..."
            # Add library path to existing jvmargs
            sed -i 's|org.gradle.jvmargs=\(.*\)|org.gradle.jvmargs=\1 -Djava.library.path=/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu|' gradle.properties
            echo "✅ Updated gradle.properties"
        elif ! grep -q "org.gradle.jvmargs" gradle.properties; then
            echo "Adding org.gradle.jvmargs to gradle.properties..."
            echo "org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8 -Djava.library.path=/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu" >> gradle.properties
            echo "✅ Added library path to gradle.properties"
        else
            echo "✅ gradle.properties already configured"
        fi
    else
        echo "Creating gradle.properties..."
        cat > gradle.properties << EOF
# Project-wide Gradle settings.
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8 -Djava.library.path=/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu
android.useAndroidX=true
android.enableJetifier=true
kotlin.code.style=official

# ARM64 (Raspberry Pi) compatibility
# Note: AAPT2 is x86-64 only, requires box64 for ARM64 systems
EOF
        echo "✅ Created gradle.properties"
    fi
    
    echo ""
    echo "=========================================="
    echo "Fix Applied!"
    echo "=========================================="
    echo ""
    echo "To build your Android project, use the wrapper script:"
    echo "  /home/morrison/Desktop/pos/run_gradle.sh assemble"
    echo ""
    echo "Or manually set the library path:"
    echo "  export LD_LIBRARY_PATH=\"/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:\$LD_LIBRARY_PATH\""
    echo "  cd /home/morrison/Desktop/quotations"
    echo "  ./gradlew assemble"
    echo ""
else
    echo "⚠ /home/morrison/Desktop/quotations directory not found"
    echo "   Run this script from the POS directory or update the path"
fi

