# Google Play Store — DoPOS AI / POS Mobile

## App identity

| Field | Value |
|-------|--------|
| Package ID | `com.pos.mobile` |
| App name | POS Mobile (change in Play Console listing if desired) |
| Default API | `https://api.doposai.com/` |
| Privacy policy | `https://doposai.com/privacy` |
| Play icon (512×512) | `static/img/playstore-icon.png` in web repo |

## 1. One-time: release signing

```bash
cd android-app
keytool -genkeypair -v \
  -keystore doposai-release.jks \
  -alias doposai \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storetype JKS

cp keystore.properties.example keystore.properties
# Edit keystore.properties with your passwords
```

**Back up** `doposai-release.jks` and passwords offline. Losing them prevents app updates.

## 2. Build the upload file

```bash
chmod +x build_release_aab.sh
./build_release_aab.sh
```

Upload: `app/build/outputs/bundle/release/app-release.aab`

Each new release must increase `versionCode` in `app/build.gradle.kts`.

## 3. Play Console checklist

- [ ] Developer account ($25 one-time)
- [ ] Store listing: short + full description, 512 icon, feature graphic, screenshots
- [ ] Privacy policy URL: https://doposai.com/privacy
- [ ] App access: test login for reviewers (or registration instructions)
- [ ] Data safety form (account, sales data, Bluetooth for printers)
- [ ] Content rating questionnaire
- [ ] Target audience: business / 18+
- [ ] Upload `.aab` → Internal testing first → Production

## 4. Suggested store text

**Short (80 chars):** Offline POS for shops — sell, print receipts, sync when online.

**Release notes (example):** Offline checkout, cloud sync within 3 days, Bluetooth receipts, admin tools.

## 5. Reviewer test account

Provide in Play Console → App access:

- Server: `https://api.doposai.com/` (pre-filled in app)
- Test username / password for a demo tenant
- Note: Bluetooth printer optional; core POS works without it

## 6. Permissions (declare in Console)

| Permission | Why |
|------------|-----|
| Internet | Sync sales and catalog with DoPOS AI cloud |
| Bluetooth | Connect to thermal receipt printers (optional) |
| Network state | Detect offline vs online for sync |
