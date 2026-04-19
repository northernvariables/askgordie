#!/usr/bin/env bash
# Install Google Coral USB Accelerator support
set -euo pipefail

echo "=== Installing Coral Edge TPU support ==="

# Add Coral apt repo
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | \
    sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -

sudo apt-get update
sudo apt-get install -y libedgetpu1-std  # Standard clock speed (safe thermal)

# Install pycoral in the gordie venv
/opt/gordie-voice/venv/bin/pip install pycoral

echo "=== Coral installed ==="
echo "Plug in the Coral USB Accelerator and run: lsusb | grep Google"
