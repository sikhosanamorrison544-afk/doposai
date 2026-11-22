# DoPOSAI Android 1.4.7 (vc32, API 36)

Offline-first sales sync hardening (3-day offline window).

## Behavior
- Local sale + stock deduct + sync queue immediately offline
- Pending sales retained indefinitely until server ACK (not deleted at 3 days)
- Automatic drain on reconnect via ConnectivitySyncMonitor + WorkManager
- Manual Sync uses the same SaleSyncPipeline: auth → upload all → catalog
- Access JWT refresh after expiry; HTTP 401 never drops queued sales
- client_sale_id idempotency unchanged on server

## Default API
`https://doposai.onrender.com/`

## Deploy
Push/deploy backend commit that issues `refresh_token` from `/api/auth/token`.
Cashiers must log in once on this APK after server deploy.
