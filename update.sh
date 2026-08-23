#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Avoid git dubious ownership errors inside Docker containers
git config --global --add safe.directory "*" 2>/dev/null || true

echo "=== 1. Fetching Latest Changes from GitHub ==="
if [ -d ".git" ]; then
    git fetch origin main
    git reset --hard origin/main
else
    echo "No .git found. Pulling repo via curl/tarball..."
    curl -fsSL https://github.com/Baxterino/PDF_AI_Translation_Pipeline/archive/refs/heads/main.tar.gz | tar -xz --strip-components=1
fi

# Update local version tracker
git rev-parse --short HEAD > .version 2>/dev/null || true

echo "=== 2. Rebuilding and Restarting Container Stack ==="
docker compose up -d --build --remove-orphans

echo "=== 3. Clean up dangling images ==="
docker image prune -f

echo "=== Update Completed Successfully! ==="
