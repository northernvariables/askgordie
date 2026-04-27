#!/usr/bin/env bash
# Setup Gordie Voice on macOS (Mac Mini)
set -euo pipefail

echo "=== Gordie Voice - macOS Setup ==="

# Check Homebrew
if ! command -v brew &>/dev/null; then
    echo "ERROR: Homebrew not found. Install from https://brew.sh"
    exit 1
fi

# System dependencies
echo "Installing system dependencies..."
brew install python@3.11 portaudio ffmpeg espeak-ng

# Install uv if missing
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Determine project root (script lives in scripts/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Project directory: $PROJECT_DIR"

# Create venv and install
cd "$PROJECT_DIR"
echo "Creating virtual environment..."
uv venv --python python3.11 venv
echo "Installing gordie-voice..."
uv pip install -e . --python venv/bin/python

# Copy .env template if needed
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit $PROJECT_DIR/.env with your API keys"
fi

# Create data directories
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/recordings"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $PROJECT_DIR/.env with your API keys"
echo "  2. Run: ./scripts/run_mac.sh"
echo ""
