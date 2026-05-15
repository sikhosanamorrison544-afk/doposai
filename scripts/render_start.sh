#!/bin/sh
set -e
# Migrations (Postgres). Safe no-op if Alembic not configured; placeholder revision exists.
if [ -n "${DATABASE_URL:-}" ] && echo "$DATABASE_URL" | grep -q '^postgresql'; then
  alembic upgrade head || echo "alembic warning (non-fatal)"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
