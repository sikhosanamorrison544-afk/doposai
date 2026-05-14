# Build Test APK – POS Mobile (doposai.com / Raspberry Pi)

The app is configured to use **your domain** as the API base URL so it talks to your backend on the Raspberry Pi. Ollama runs on the Pi; the **backend** uses it for Business Sage. The Android app only talks to the POS API (auth, products, sales). When you move the backend to the cloud, change the server URL (see below).

## Default configuration

- **API base URL:** `https://doposai.com/` (set in `app/build.gradle.kts` → `BuildConfig.DEFAULT_API_BASE_URL`).
- On first launch the app stores this in SharedPreferences as `base_url`. Sync and API calls use it.
- **Network:** Cleartext (HTTP) is allowed only for `doposai.com`, `www.doposai.com`, and `localhost` (see `res/xml/network_security_config.xml`). Use HTTPS in production.

## When you move backend to the cloud

1. **Option A – Same domain:** Point doposai.com to your cloud server. No app change.
2. **Option B – New URL:** Change default in `app/build.gradle.kts`:  
   `buildConfigField("String", "DEFAULT_API_BASE_URL", "\"https://your-cloud-url.com/\"")`  
   and rebuild. Or add an in-app “Server URL” setting that writes to SharedPreferences `base_url` so users can switch without a new build.

## Build test (debug) APK

From the **android-app** directory:

```bash
cd /home/morrison/Desktop/pos/android-app
./gradlew --stop
sleep 2
./gradlew assembleDebug
```

**On Raspberry Pi:** Use `--stop` and a short sleep so only one Gradle instance runs and the Artifact transforms cache is not locked. Otherwise you may see: *"Timeout waiting to lock Artifact transforms cache ... It is currently in use by another Gradle instance."*

Or run the script (does the same):

```bash
./build_test_apk.sh
```

If `./gradlew` is missing or fails, use Gradle directly:

```bash
gradle --stop
sleep 2
gradle assembleDebug
```

Or open the **android-app** folder in Android Studio and use **Build → Build Bundle(s) / APK(s) → Build APK(s)**.

**Output:**  
`app/build/outputs/apk/debug/app-debug.apk`

Install on a device:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Or copy `app-debug.apk` to your phone and open it (allow “Install from unknown sources” if prompted).

## Requirements

- **JDK 17**
- **Android SDK** (API 34); `ANDROID_HOME` or `sdk.dir` in `android-app/local.properties`, e.g.  
  `sdk.dir=/path/to/Android/sdk`
- **Gradle** (or use Android Studio, which includes it)

**Layout / AAPT:** If you add layouts, never use `android:minHeight="match_parent"` — AAPT requires a dimension (e.g. `0dp`). Use `android:minHeight="0dp"` instead. The current `activity_main.xml` does not use `minHeight`.

**Raspberry Pi / aarch64:** The Android SDK ships AAPT2 only for x86_64. On-Pi options:

1. **box64 (on Pi):** Install box64 (`sudo apt install box64`). Disable qemu-x86_64 so box64 handles x86_64: `echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-x86_64`. Then run `./build_test_apk.sh`. First run may show AAPT2/box64 warnings; run again and the build usually completes. Output: `app/build/outputs/apk/debug/app-debug.apk`.
2. **Docker (on Pi):** From `android-app` run `./build_apk_docker.sh` (x86_64 container; first run slow).
3. **PC or Mac:** Open `android-app` in Android Studio → **Build → Build Bundle(s) / APK(s) → Build APK(s)**.

## Summary

| What              | Where / How |
|-------------------|-------------|
| Default server    | `https://doposai.com/` (Pi backend) |
| Change for cloud | BuildConfig or in-app Server URL → `base_url` |
| Build test APK   | `./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk` |
| Ollama            | Used by the **backend** on the Pi (Business Sage). App does not call Ollama directly. |
