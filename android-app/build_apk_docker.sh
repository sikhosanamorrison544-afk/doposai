#!/bin/bash
# Build debug APK using x86_64 Docker (use on aarch64/Pi where native build fails).
# Requires: Docker, project gradlew + gradle-wrapper.jar.
# Output: app/build/outputs/apk/debug/app-debug.apk
set -e
cd "$(dirname "$0")"
echo "Building APK in x86_64 container (may be slow on Pi due to emulation)..."
docker run --rm --platform linux/amd64 \
  -v "$(pwd):/app" \
  -w /app \
  eclipse-temurin:17-jdk-jammy \
  bash -c "./gradlew --no-daemon assembleDebug"
echo ""
echo "APK: app/build/outputs/apk/debug/app-debug.apk"
ls -la app/build/outputs/apk/debug/app-debug.apk 2>/dev/null || true
