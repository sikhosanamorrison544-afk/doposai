# Authentication & administrator security

This document describes production requirements introduced in the Phase 1 security hardening.

## JWT (`JWT_SECRET_KEY`)

| Requirement | Detail |
|-------------|--------|
| Variable | `JWT_SECRET_KEY` |
| Minimum length | 32 characters |
| Placeholders rejected | Values such as `secret`, `change-me`, `change-me-in-production`, `your-secret-key`, and the former source-code default |
| Algorithm | HS256 only (encode and decode) |
| Failure mode | Application **will not start** if the secret is missing, empty, too short, or a known placeholder |

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put it in `.env` (local) or the host environment (Render/Docker). **Never commit real secrets.**

Docker Compose requires the variable to be set in the shell; there is no insecure default:

```bash
export JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose up --build
```

## Administrator repair is not remotely exposed

The former unauthenticated HTTP endpoint `POST /api/repair-admin` has been **removed**.

It previously allowed anyone to create or reset an `admin` account to a known default password. That route must not exist in any environment.

### Local recovery (server shell only)

```bash
cd /path/to/pos
source .venv/bin/activate
python scripts/repair_admin_account.py --username admin --reset-existing
# or create if missing:
python scripts/repair_admin_account.py --username admin --create-if-missing
```

- Prompts for a new password via `getpass` (password is not printed)
- Rejects weak/default passwords (min 12 chars, letter + digit, not in common list)
- Does not overwrite an existing user unless `--reset-existing` is passed
- Uses the same password hashing as the application (`pbkdf2_sha256`)

Initial install without any admin:

```bash
python -m app.init_db
```

This prompts interactively and will not overwrite an existing administrator.

### Factory reset

Authenticated admins may still factory-reset (SQLite deployments). The API requires:

- Current admin password confirmation
- A **new** strong administrator password (`new_admin_password`) — never a hard-coded default

## Deploy verification checklist

1. Confirm `JWT_SECRET_KEY` is set in the production environment (Render dashboard / secrets).
2. Confirm the API process starts; a missing/weak JWT secret must prevent boot.
3. Confirm `POST /api/repair-admin` returns **404** (route not registered).
4. Confirm anonymous `GET /api/auth/me` returns **401**.
5. Confirm a cashier cannot call admin-only APIs (**403**).
6. Confirm login still works for legitimate administrators.

## Related files

- `app/security_config.py` — JWT and bootstrap password validation
- `app/auth.py` — token create/decode (centralized secret)
- `scripts/repair_admin_account.py` — local recovery CLI
- `tests/test_auth_security.py` — regression tests
