# DoPOSAI Android 1.4.6 (vc31, API 36)

## Fix
Offline sales now synchronize to the central server after reconnect.

Root cause: username/password cashier login stored an empty refresh token while
access JWTs expire in 8 hours. Background sync then POSTed with a dead JWT
(HTTP 401) and never completed `POST /api/sales`, so server/web stock stayed
unchanged while Android local stock was already reduced.

## Artifacts
- `DoPOSAI-1.4.6-vc31-api36-debug.apk` — installable debug build
- `DoPOSAI-1.4.6-vc31-api36-release-UNSIGNED.apk` — release (unsigned; sign with store keystore)

## Default API
`https://doposai.onrender.com/`

## Deploy note
Server must also deploy the `/api/auth/token` refresh_token change so new
cashier logins receive a refresh token. Existing devices must **log in once**
after install to persist the refresh token.
