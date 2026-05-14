# Android POS Mobile – Offline-First APK Build

This document covers: **required dependencies**, **database schema**, **sync service**, and **commands to build a signed release APK**.

---

## 1. Required Dependencies

From `android-app/app/build.gradle.kts`:

| Purpose | Dependency |
|--------|------------|
| **SQLite (offline-first)** | `androidx.room:room-runtime`, `room-ktx`, `room-compiler` (2.6.1) |
| **Background sync** | `androidx.work:work-runtime-ktx` (2.9.0) |
| **Networking (cloud API)** | `retrofit2:retrofit`, `converter-gson`, `okhttp3` (2.9.0 / 4.12.0) |
| **Coroutines** | `kotlinx-coroutines-android`, `lifecycle-runtime-ktx`, `lifecycle-viewmodel-ktx` |
| **UI** | `core-ktx`, `appcompat`, `material`, `constraintlayout` |

**Min SDK:** 24  
**Target SDK:** 34  
**Kotlin:** 1.9.20  
**AGP:** 8.2.0  

---

## 2. Database Schema (SQLite via Room)

**Local DB name:** `pos_offline.db`

### Tables

| Table | Purpose |
|-------|--------|
| **products** | Cached products from API; UI reads here first. |
| **categories** | Cached categories. |
| **customers** | Cached customers. |
| **sales** | All sales (local + synced). `localId` (PK), `serverId` (set after sync), `syncedAt`. |
| **sale_items** | Line items; `saleLocalId` → `sales.localId`. |
| **payments** | Payments; `saleLocalId` → `sales.localId`. |
| **sync_queue** | Queue of unsynced transactions. One row per sale `localId`; status: `pending` / `syncing` / `synced` / `failed`. |
| **sync_metadata** | `last_synced_at` per entity: `key` (e.g. `products`, `customers`, `sales_push`), `lastSyncedAt`, `lastSyncSuccess`. |

**Offline operation:** App can run fully offline for **up to 3 days**; all writes go to SQLite. When a sale is created offline, it is inserted into `sales`, `sale_items`, `payments`, and a row is added to `sync_queue`. The UI **always reads from the local database first** for instant performance.

---

## 3. Sync Service

- **SyncRepository** (`data/sync/SyncRepository.kt`):  
  - **Pull:** Fetch products/customers from cloud API, write to local DB, update `sync_metadata.lastSyncedAt`.  
  - **Push:** For each `sync_queue` row with status `pending`, build payload from `sales` + `sale_items` + `payments`, POST to `POST /api/sales`, then mark sale as synced and update queue status and `sync_metadata`.

- **SyncWorker** (`data/sync/SyncWorker.kt`):  
  - WorkManager `CoroutineWorker` run with **constraint** `NetworkType.CONNECTED`.  
  - On run: optional pull of products/customers; then push all pending sales from `sync_queue` via `SyncRepository.pushSale()`.  
  - Scheduled in `PosApplication` as a **periodic work** (every 15 min).  
  - Base URL and auth token: from `WorkManager` input data, or from `SharedPreferences` ("pos") keys `base_url` and `token`.

**Flow:**  
1. User creates sale offline → insert into `sales`, `sale_items`, `payments`, insert into `sync_queue` (status `pending`).  
2. When network is available, WorkManager runs `SyncWorker`.  
3. Worker pulls latest products/customers (optional), then pushes each pending sale to `POST /api/sales`.  
4. On success: update `sales.serverId` and `sales.syncedAt`, set queue row to `synced`, update `sync_metadata` for `sales_push`.

---

## 4. Build Signed Release APK – Commands

### 4.1 One-off: create a keystore

```bash
cd /home/morrison/Desktop/pos/android-app

keytool -genkey -v -keystore pos-release.keystore -alias pos -keyalg RSA -keysize 2048 -validity 10000
```

Use a strong password and store it safely. You will need the alias and both keystore and key passwords for the next step.

### 4.2 Configure signing in the app module

Create or edit `android-app/keystore.properties` (do **not** commit this file):

```properties
storePassword=YOUR_KEYSTORE_PASSWORD
keyPassword=YOUR_KEY_PASSWORD
keyAlias=pos
storeFile=pos-release.keystore
```

Then in `app/build.gradle.kts` add before `android { ... }`:

```kotlin
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = java.util.Properties()
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(keystorePropertiesFile.inputStream())
}

android {
    ...
    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = rootProject.file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            ...
        }
    }
}
```

### 4.3 Build the release APK

From the **project root** (where `android-app/` lives):

```bash
cd /home/morrison/Desktop/pos/android-app
./gradlew assembleRelease
```

Output APK:

```
android-app/app/build/outputs/apk/release/app-release.apk
```

### 4.4 Build a release AAB (for Play Store)

```bash
cd /home/morrison/Desktop/pos/android-app
./gradlew bundleRelease
```

Output AAB:

```
android-app/app/build/outputs/bundle/release/app-release.aab
```

### 4.5 Requirements

- **JDK 17** (or as required by the Android Gradle Plugin).
- **Android SDK** with `build-tools` and `platforms` for `compileSdk`/`targetSdk` (34).
- Environment variable **ANDROID_HOME** (or `sdk.dir` in `local.properties`) pointing to the SDK.

Example `local.properties` (create under `android-app/` if needed):

```properties
sdk.dir=/path/to/Android/sdk
```

---

## 5. Summary

| Item | Location / Command |
|------|--------------------|
| Dependencies | `android-app/app/build.gradle.kts` |
| DB schema | Room entities in `android-app/app/src/main/java/com/pos/mobile/data/local/entity/` |
| Sync service | `SyncWorker` + `SyncRepository` in `data/sync/` |
| Signed release APK | `cd android-app && ./gradlew assembleRelease` → `app/build/outputs/apk/release/app-release.apk` |
| Signed AAB | `cd android-app && ./gradlew bundleRelease` → `app/build/outputs/bundle/release/app-release.aab` |

After building, install the APK on a device (or emulator) with:

```bash
adb install -r android-app/app/build/outputs/apk/release/app-release.apk
```
