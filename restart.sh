#!/bin/bash
# Restart the Telegram Audio Bot
# Usage: ./restart.sh

set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$BOT_DIR/.bot.pid"

echo "=== Telegram Audio Bot Restart ==="

# Kill existing process via PID file
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping bot (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 2
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Force killing..."
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
        echo "Stopped."
    else
        echo "Stale PID file (process $OLD_PID gone), cleaning up."
    fi
    rm -f "$PID_FILE"
fi

# Kill any remaining bot processes (safety net)
for pid in $(pgrep -f "bot.py" 2>/dev/null || true); do
    echo "Killing leftover bot process $pid..."
    kill "$pid" 2>/dev/null || true
done
sleep 1
# Force kill any survivors
for pid in $(pgrep -f "bot.py" 2>/dev/null || true); do
    kill -9 "$pid" 2>/dev/null || true
done

# Pull latest code
cd "$BOT_DIR"
echo "Pulling latest code..."
git pull

# Check vault accessibility
VAULT_DIR=$(grep OBSIDIAN_VAULT_DIR .env | cut -d= -f2)
if [ -n "$VAULT_DIR" ] && [ ! -d "$VAULT_DIR" ]; then
    echo "WARNING: Vault directory not accessible: $VAULT_DIR"
    echo "Bot will start but may fail on first audio."
fi

# Start bot
echo "Starting bot..."
cd "$BOT_DIR"
nohup uv run bot.py >> bot.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "Bot started (PID $NEW_PID)."
echo "Logs: $BOT_DIR/bot.log"
echo "Check: tail -f $BOT_DIR/bot.log"
