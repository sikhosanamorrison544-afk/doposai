#!/bin/bash
# Build debug APK for testing. Uses your domain (doposai.com) as default API.
# On Raspberry Pi: stop all Gradle daemons first to avoid "Timeout waiting to lock Artifact transforms cache".
# On aarch64 (e.g. Raspberry Pi): install box64 and disable qemu-x86_64 binfmt so
# box64 runs the x86_64 AAPT2 binary:  echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-x86_64
set -e
cd "$(dirname "$0")"
if [ -x "./gradlew" ]; then
  ./gradlew --stop
  sleep 2
  ./gradlew assembleDebug
else
  gradle --stop 2>/dev/null || true
  sleep 2
  gradle assembleDebug
fi
echo ""
echo "APK: app/build/outputs/apk/debug/app-debug.apk"
ls -la app/build/outputs/apk/debug/app-debug.apk 2>/dev/null || true
