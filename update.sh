#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

LOCK_FILE="/tmp/pipeline_updating.lock"

# Concurrency check
if [ -f "$LOCK_FILE" ]; then
    echo "[$(date)] Update already in progress. Exiting duplicate process."
    exit 0
fi

touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

exec >> "$REPO_DIR/update.log" 2>&1

echo "[$(date)] === 1. Fetching Latest Changes from GitHub ==="
git config --global --add safe.directory "*" 2>/dev/null || true

if [ -d ".git" ]; then
    git fetch origin main
    git reset --hard origin/main
else
    echo "No .git directory found. Pulling repo archive..."
    curl -fsSL https://github.com/Baxterino/PDF_AI_Translation_Pipeline/archive/refs/heads/main.tar.gz | tar -xz --strip-components=1
fi

git rev-parse --short HEAD > .version 2>/dev/null || true

echo "[$(date)] === 2. Force-Rebuilding Containers (No Cache) ==="
docker compose build --no-cache pdf-translator
docker compose up -d --remove-orphans

echo "[$(date)] === 3. Cleaning up dangling images ==="
docker image prune -f

echo "[$(date)] === Update Completed Successfully! ==="
