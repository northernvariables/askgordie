#!/usr/bin/env bash
# First-boot provisioning for Gordie Voice on Raspberry Pi 5
set -euo pipefail

echo "=== Gordie Voice - Pi 5 Setup ==="

# Create gordie user if not exists
if ! id -u gordie &>/dev/null; then
    sudo useradd -m -s /bin/bash -G audio,video,input,gpio gordie
    echo "Created user: gordie"
fi

# System dependencies
sudo apt-get update
sudo apt-get install -y \
    python3.11 python3.11-venv python3.11-dev \
    portaudio19-dev libsndfile1 \
    libopencv-dev \
    ffmpeg \
    espeak-ng \
    chromium-browser \
    jq curl git

# Install uv
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Setup project directory
sudo mkdir -p /opt/gordie-voice
sudo chown gordie:gordie /opt/gordie-voice

# Clone or copy repo
if [ -d ".git" ]; then
    sudo -u gordie cp -r . /opt/gordie-voice/
fi

# Create venv and install
cd /opt/gordie-voice
sudo -u gordie uv venv --python python3.11 venv
sudo -u gordie uv pip install -e . --python venv/bin/python

# Copy .env template
if [ ! -f /opt/gordie-voice/.env ]; then
    sudo -u gordie cp .env.example .env
    echo "IMPORTANT: Edit /opt/gordie-voice/.env with your API keys"
fi

# Install systemd services
sudo cp systemd/gordie-voice.service /etc/systemd/system/
sudo cp systemd/gordie-display.service /etc/systemd/system/
sudo cp systemd/gordie-display-secondary.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gordie-voice.service
sudo systemctl enable gordie-display.service

echo ""
echo "=== Setup complete ==="
echo "1. Edit /opt/gordie-voice/.env with your API keys"
echo "2. sudo systemctl start gordie-voice"
echo "3. sudo systemctl start gordie-display"
echo "4. Say 'Hey Gordie' and ask a question!"
echo ""
echo "For dual display: sudo systemctl enable --now gordie-display-secondary"
