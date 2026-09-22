#!/bin/bash
set -e

echo "🚀 Deploying Zalo Bot..."

TARGET_DIR="/home/zalo-bot"

# Create target dir if needed
mkdir -p "$TARGET_DIR"

# Copy files
cp -r config database handlers services scripts main.py requirements.txt "$TARGET_DIR/"

# Setup venv if needed
if [ ! -d "$TARGET_DIR/.venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$TARGET_DIR/.venv"
fi

# Install dependencies
echo "📦 Installing requirements..."
"$TARGET_DIR/.venv/bin/pip" install -q -r "$TARGET_DIR/requirements.txt"

# Restart systemd service
echo "🔄 Restarting zalo-bot service..."
sudo systemctl restart zalo-bot

# Health check
sleep 2
curl -s http://127.0.0.1:8080/health

echo -e "\n✅ Deployment complete!"
