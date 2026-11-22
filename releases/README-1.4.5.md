# DoPOSAI Android 1.4.5 (API 36)

Built from `main` including sync fix commit `9e21e57321e02b08f6de72044791254d76e3f89c`.

## Artifacts

| File | Purpose | Installable? |
|------|---------|--------------|
| `DoPOSAI-1.4.5-vc30-api36-debug.apk` | Debug-signed test build (Android Debug keystore) | Yes (sideload / `adb install -r`) |
| `DoPOSAI-1.4.5-vc30-api36-release-UNSIGNED.apk` | Minified release package **without** production signing | **No** — must be signed with `doposai-release.jks` first |

## Identity

- Application ID: `com.pos.mobile`
- versionName: `1.4.5`
- versionCode: `30`
- minSdk: `24`
- targetSdk / compileSdk: `36` (Android 16)

## Signing blocker (release)

`android-app/keystore.properties` and `doposai-release.jks` were **not present** on this machine.
A production-compatible update APK cannot be produced without the existing release keystore.
Do **not** install the UNSIGNED release APK as-is.

To finish a Play/production release on a machine that has the keystore:

```bash
cd android-app
# ensure keystore.properties + doposai-release.jks exist
./gradlew :app:assembleRelease
# output: app/build/outputs/apk/release/app-release.apk
```

## Sync fixes included

- Immediate online sale push (`tryImmediateSalePush`)
- Catalog pull deferred while uploads pending/syncing
- Orphaned `STATUS_SYNCING` requeue
- Post-push stock refresh when queue empty
- `create_sale` rollback on stock failure (backend, already on `main`)
