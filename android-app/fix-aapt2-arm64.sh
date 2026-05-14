#!/bin/bash
# On ARM64 (e.g. Raspberry Pi), Gradle's AAPT2 is x86_64. This script wraps it with box64
# so the build works. Run once after a clean or if assembleDebug fails with libdl.so.2.
set -e
CACHE="$HOME/.gradle/caches/transforms-3"
DIR=$(find "$CACHE" -name "aapt2-*-linux" -type d 2>/dev/null | head -1)
if [ -z "$DIR" ]; then
  echo "Run ./gradlew assembleDebug once (it will fail), then run this script and try again."
  exit 1
fi
if [ ! -f "$DIR/aapt2.real" ]; then
  cp "$DIR/aapt2" "$DIR/aapt2.real"
fi
echo '#!/bin/bash
exec /usr/bin/box64 "$(dirname "$0")/aapt2.real" "$@"' > "$DIR/aapt2"
chmod +x "$DIR/aapt2"
echo "Fixed: $DIR/aapt2 now runs via box64. Try ./gradlew assembleDebug again."
