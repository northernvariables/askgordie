#!/usr/bin/env bash
# Launch Gordie Voice on macOS — voice service + kiosk display
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Export GORDIE_ROOT so the app finds its data/recordings/keys here
export GORDIE_ROOT="$PROJECT_DIR"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
else
    echo "ERROR: No .env file found. Run setup_mac.sh first, then edit .env"
    exit 1
fi

# Create data dirs
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/recordings"

echo "=== Starting Gordie Voice ==="
echo "GORDIE_ROOT=$GORDIE_ROOT"

# Start the voice service in the background
"$PROJECT_DIR/venv/bin/python" -m gordie_voice &
VOICE_PID=$!
echo "Voice service started (PID $VOICE_PID)"

# Wait for Flask to come up
echo "Waiting for display server..."
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:8080/ >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Launch Chromium/Chrome in kiosk mode
CHROME_APP=""
if [ -d "/Applications/Google Chrome.app" ]; then
    CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif [ -d "/Applications/Chromium.app" ]; then
    CHROME_APP="/Applications/Chromium.app/Contents/MacOS/Chromium"
fi

if [ -n "$CHROME_APP" ]; then
    echo "Launching kiosk display..."
    "$CHROME_APP" \
        --kiosk \
        --noerrdialogs \
        --disable-translate \
        --no-first-run \
        --disable-features=TranslateUI \
        --touch-events=enabled \
        --disable-pinch \
        --overscroll-history-navigation=disabled \
        --disk-cache-dir=/dev/null \
        http://127.0.0.1:8080/primary &
    CHROME_PID=$!
    echo "Kiosk display started (PID $CHROME_PID)"
else
    echo "WARNING: No Chrome/Chromium found. Open http://127.0.0.1:8080/primary manually."
fi

# Trap Ctrl+C to clean up both processes
cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$VOICE_PID" 2>/dev/null || true
    [ -n "${CHROME_PID:-}" ] && kill "$CHROME_PID" 2>/dev/null || true
    wait
    echo "Done."
}
trap cleanup INT TERM

echo ""
echo "=== Gordie is running ==="
echo "Say 'Hey Gordie' and ask a question!"
echo "Press Ctrl+C to stop."
echo ""

# Wait for the voice service to exit
wait "$VOICE_PID"
