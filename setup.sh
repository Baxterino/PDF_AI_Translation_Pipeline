#!/usr/bin/env bash
set -e

echo "=== 1. Updating System & Installing Dependencies ==="
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl wget git build-essential docker.io docker-compose-v2 util-linux-extra zstd

echo "=== 2. Configuring Docker Permissions ==="
sudo usermod -aG docker "$USER"

echo "=== 3. Installing & Configuring Ollama ==="
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << 'OLLAMA_CONF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_ORIGINS=*"
OLLAMA_CONF

if pidof systemd > /dev/null 2>&1; then
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
else
    export OLLAMA_HOST="0.0.0.0:11434"
    export OLLAMA_ORIGINS="*"
    pkill ollama || true
    nohup ollama serve > /dev/null 2>&1 &
fi

echo "Waiting for Ollama service to become responsive..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        echo "✔ Ollama server is active and listening!"
        break
    fi
    sleep 1
done

echo "=== 4. Pulling Default Translation Model ==="
ollama pull translategemma:4b

echo "=== 5. Syncing Repository Code ==="
TARGET_DIR="$HOME/PDF_AI_Translation_Pipeline"

if [ -d "$TARGET_DIR/.git" ]; then
    echo "Updating existing repository in $TARGET_DIR..."
    cd "$TARGET_DIR"
    git pull origin main
else
    echo "Cloning repository from GitHub..."
    git clone https://github.com/Baxterino/PDF_AI_Translation_Pipeline.git "$TARGET_DIR"
    cd "$TARGET_DIR"
fi

# Ensure all scripts have execute permissions
chmod +x "$TARGET_DIR/update.sh" "$TARGET_DIR/setup.sh" 2>/dev/null || true

# Initialize local version file
git rev-parse --short HEAD > "$TARGET_DIR/.version" 2>/dev/null || true

echo "=== 6. Building & Launching Stack ==="
sg docker -c "docker compose up -d --build"

echo "=================================================="
echo "✔ Setup Completed Successfully!"
echo "AI Translator UI: http://localhost:8501"
echo "Stirling PDF:     http://localhost:8080"
echo "For more AI models, visit -> https://ollama.com/library <-, then type 'ollama pull model_name'"
echo "Made by Stefan Axinte - https://github.com/Baxterino/PDF_AI_Translation_Pipeline"
echo "=================================================="
