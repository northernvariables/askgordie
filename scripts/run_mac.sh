#!/usr/bin/env bash
# Launch Gordie Voice on macOS — voice service + dual kiosk displays
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

# Enable dual display mode
export DISPLAY__DUAL_DISPLAY=true

# Create data dirs
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/recordings"

echo "=== Starting Gordie Voice (dual display) ==="
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

# Find Chrome/Chromium
CHROME_APP=""
if [ -d "/Applications/Google Chrome.app" ]; then
    CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif [ -d "/Applications/Chromium.app" ]; then
    CHROME_APP="/Applications/Chromium.app/Contents/MacOS/Chromium"
fi

CHROME_PIDS=()

if [ -n "$CHROME_APP" ]; then
    COMMON_FLAGS=(
        --kiosk
        --noerrdialogs
        --disable-translate
        --no-first-run
        --disable-features=TranslateUI
        --touch-events=enabled
        --disable-pinch
        --overscroll-history-navigation=disabled
        --disk-cache-dir=/dev/null
    )

    # Primary display (voice persona) — opens on the default/main screen
    echo "Launching primary display (voice)..."
    "$CHROME_APP" \
        "${COMMON_FLAGS[@]}" \
        --user-data-dir="/tmp/gordie-chrome-primary" \
        http://127.0.0.1:8080/primary &
    CHROME_PIDS+=($!)

    # Brief pause so macOS doesn't merge the windows
    sleep 2

    # Secondary display (prompt/text) — positioned on second monitor
    # Uses --window-position to push it to the second screen.
    # Adjust 1920 if your displays have different resolution/arrangement.
    echo "Launching secondary display (prompt)..."
    "$CHROME_APP" \
        "${COMMON_FLAGS[@]}" \
        --user-data-dir="/tmp/gordie-chrome-secondary" \
        --window-position=1920,0 \
        http://127.0.0.1:8080/secondary &
    CHROME_PIDS+=($!)

    echo "Both displays started"
else
    echo "WARNING: No Chrome/Chromium found."
    echo "  Primary:   http://127.0.0.1:8080/primary"
    echo "  Secondary: http://127.0.0.1:8080/secondary"
fi

# Trap Ctrl+C to clean up all processes
cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$VOICE_PID" 2>/dev/null || true
    for pid in "${CHROME_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait
    echo "Done."
}
trap cleanup INT TERM

echo ""
echo "=== Gordie is running (dual display) ==="
echo "  Primary:   voice persona"
echo "  Secondary: prompt/text overlay"
echo "Say 'Hey Gordie' and ask a question!"
echo "Press Ctrl+C to stop."
echo ""

# Wait for the voice service to exit
wait "$VOICE_PID"
