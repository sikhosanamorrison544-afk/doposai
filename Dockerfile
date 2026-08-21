# Production API image (Render, ECS, or docker-compose)
FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY static ./static
COPY templates ./templates
COPY scripts ./scripts
# Startup migrations (see scripts/render_start.sh) — must be present in the image.
COPY migrate_*.py ./

RUN chmod +x scripts/render_start.sh
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Prefer render_start.sh so background migrations run before workers bind.
CMD ["sh", "scripts/render_start.sh"]
