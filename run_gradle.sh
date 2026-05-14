#!/bin/bash
# Wrapper script to run Gradle with correct library paths for Raspberry Pi
# Handles box64 for x86-64 AAPT2 on ARM64 systems

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_APP_DIR="$SCRIPT_DIR/android-app"
LEGACY_QUOTATIONS="/home/morrison/Desktop/quotations"

if [ -d "$ANDROID_APP_DIR" ]; then
    PROJECT_DIR="$ANDROID_APP_DIR"
elif [ -d "$LEGACY_QUOTATIONS" ]; then
    PROJECT_DIR="$LEGACY_QUOTATIONS"
else
    echo "❌ Android Gradle project not found."
    echo "   Expected: $ANDROID_APP_DIR or $LEGACY_QUOTATIONS"
    exit 1
fi

# Set library paths for both ARM64 and x86-64 (for box64)
export LD_LIBRARY_PATH="/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH"

# Configure box64 environment variables
if command -v box64 &> /dev/null; then
    export BOX64_LD_LIBRARY_PATH="/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu"
    export BOX64_PATH="/usr/bin/box64"
    export BOX64_LOG=0  # Disable verbose logging
    echo "Using box64 for x86-64 compatibility"
    
    # Create a wrapper in PATH that box64 can use
    WRAPPER_DIR="$HOME/.local/bin"
    mkdir -p "$WRAPPER_DIR"
    
    # Create aapt2 wrapper if it doesn't exist
    if [ ! -f "$WRAPPER_DIR/aapt2" ]; then
        cat > "$WRAPPER_DIR/aapt2" << 'EOF'
#!/bin/bash
# Auto-generated aapt2 wrapper for box64
exec box64 "$(find ~/.gradle/caches -name "aapt2" -type f 2>/dev/null | head -1)" "$@"
EOF
        chmod +x "$WRAPPER_DIR/aapt2"
    fi
    
    # Add wrapper to PATH if not already there
    if [[ ":$PATH:" != *":$WRAPPER_DIR:"* ]]; then
        export PATH="$WRAPPER_DIR:$PATH"
    fi
fi

cd "$PROJECT_DIR"

# Run gradle with all passed arguments
./gradlew "$@"

