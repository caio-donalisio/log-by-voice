#!/bin/bash
# Restart the Telegram Audio Bot
# Usage: ./restart.sh

set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$BOT_DIR/.bot.pid"

echo "=== Telegram Audio Bot Restart ==="

# Kill existing process if running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping bot (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 2
        # Force kill if still alive
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Force killing..."
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
        echo "Stopped."
    else
        echo "Stale PID file (process $OLD_PID not running), cleaning up."
    fi
    rm -f "$PID_FILE"
else
    # Fallback: kill any existing bot processes
    PIDS=$(pgrep -f "bot.py" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "Found running bot processes, stopping: $PIDS"
        echo "$PIDS" | xargs kill 2>/dev/null || true
        sleep 2
    fi
fi

# Pull latest code
cd "$BOT_DIR"
echo "Pulling latest code..."
git pull

# Start bot
echo "Starting bot..."
cd "$BOT_DIR"
nohup uv run bot.py > /dev/null 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "Bot started (PID $NEW_PID)."
echo "Logs: $BOT_DIR/bot.log"
echo "Check: tail -f $BOT_DIR/bot.log"
