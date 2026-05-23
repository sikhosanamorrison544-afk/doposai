#!/bin/sh
# Quick helper on a fresh Contabo GPU VPS (run as root after copying ai-service to /opt/doposai/ai-service).
# Does NOT install Docker/NVIDIA — do that first (see docs/QWEN3_VLLM_CONTABO_SETUP.md).

set -e
AI_DIR="${1:-/opt/doposai/ai-service}"
PROFILE="${2:-14b}"

if [ ! -f "$AI_DIR/docker-compose.yml" ]; then
  echo "Missing $AI_DIR/docker-compose.yml — copy ai-service folder first."
  exit 1
fi

cd "$AI_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
  sed -i "s/change-me-long-random-string/$KEY/" .env
  echo "Created .env with random AI_SERVICE_API_KEY — copy this to Render:"
  grep '^AI_SERVICE_API_KEY=' .env
fi

case "$PROFILE" in
  8b|8)
    echo "Starting Qwen3-8B AWQ..."
    docker compose up -d --build
    ;;
  32b|32)
    echo "Starting Qwen3-32B AWQ..."
    docker compose -f docker-compose.yml -f docker-compose.qwen3-32b.yml up -d --build
    ;;
  *)
    echo "Starting Qwen3-14B AWQ (recommended large model)..."
    docker compose -f docker-compose.yml -f docker-compose.qwen3-14b.yml up -d --build
    ;;
esac

echo "Follow logs: docker compose logs -f vllm"
echo "Health:    curl -s http://127.0.0.1:8080/ai/health | python3 -m json.tool"
