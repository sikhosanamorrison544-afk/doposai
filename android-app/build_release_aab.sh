#!/bin/bash
# Build a signed release App Bundle (.aab) for Google Play Store upload.
#
# Prerequisites:
#   1. Copy keystore.properties.example → keystore.properties
#   2. Create doposai-release.jks (see keystore.properties.example)
#   3. JDK 17 + Android SDK (API 34)
#
# Output:
#   app/build/outputs/bundle/release/app-release.aab
#
# On Raspberry Pi / aarch64, prefer building on a PC/Mac or use build_apk_docker.sh
# with bundleRelease instead of assembleDebug.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f keystore.properties ]]; then
  echo "ERROR: keystore.properties not found."
  echo "  cp keystore.properties.example keystore.properties"
  echo "  Then create doposai-release.jks and set passwords."
  exit 1
fi

STORE_FILE=$(grep '^storeFile=' keystore.properties | cut -d= -f2)
if [[ -z "$STORE_FILE" || ! -f "$STORE_FILE" ]]; then
  echo "ERROR: Keystore file '$STORE_FILE' not found (see keystore.properties)."
  exit 1
fi

if [[ -x ./gradlew ]]; then
  ./gradlew --stop 2>/dev/null || true
  sleep 2
  ./gradlew bundleRelease
else
  gradle --stop 2>/dev/null || true
  sleep 2
  gradle bundleRelease
fi

AAB="app/build/outputs/bundle/release/app-release.aab"
echo ""
if [[ -f "$AAB" ]]; then
  echo "Play Store bundle ready:"
  ls -la "$AAB"
  echo ""
  echo "Upload this .aab in Google Play Console → Production → Create release"
else
  echo "Build finished but $AAB was not found. Check Gradle output above."
  exit 1
fi
