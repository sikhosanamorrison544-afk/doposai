#!/bin/bash
# Patch AAPT2 binaries in Gradle cache to use box64 wrapper

set -e

echo "=========================================="
echo "Patching AAPT2 for box64"
echo "=========================================="
echo ""

GRADLE_CACHE="$HOME/.gradle/caches/transforms-3"

if [ ! -d "$GRADLE_CACHE" ]; then
    echo "❌ Gradle cache not found: $GRADLE_CACHE"
    exit 1
fi

# Find all aapt2 binaries
AAPT2_BINARIES=$(find "$GRADLE_CACHE" -name "aapt2" -type f 2>/dev/null)

if [ -z "$AAPT2_BINARIES" ]; then
    echo "⚠ No AAPT2 binaries found in cache. Run a Gradle build first to download them."
    exit 0
fi

echo "Found AAPT2 binaries:"
echo "$AAPT2_BINARIES" | while read -r aapt2_path; do
    echo "  - $aapt2_path"
done
echo ""

# Create backup and wrapper for each aapt2
echo "$AAPT2_BINARIES" | while read -r aapt2_path; do
    aapt2_dir=$(dirname "$aapt2_path")
    aapt2_backup="${aapt2_path}.original"
    
    # Backup original if not already backed up
    if [ ! -f "$aapt2_backup" ]; then
        echo "Backing up: $aapt2_path"
        cp "$aapt2_path" "$aapt2_backup"
    fi
    
    # Create wrapper script
    cat > "$aapt2_path" << 'AAPT2WRAPPER'
#!/bin/bash
# box64 wrapper for AAPT2
# This script replaces the x86-64 AAPT2 binary to run through box64

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ORIGINAL_AAPT2="${SCRIPT_DIR}/aapt2.original"

# Set library paths for box64
export BOX64_LD_LIBRARY_PATH="/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu"
export LD_LIBRARY_PATH="/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH"

# Run original aapt2 through box64
exec box64 "$ORIGINAL_AAPT2" "$@"
AAPT2WRAPPER
    
    chmod +x "$aapt2_path"
    echo "✅ Wrapped: $aapt2_path"
done

echo ""
echo "=========================================="
echo "Patch Complete!"
echo "=========================================="
echo ""
echo "AAPT2 binaries have been wrapped to use box64."
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "You can now run: $SCRIPT_ROOT/run_gradle.sh assembleDebug"
echo ""

