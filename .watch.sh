#!/bin/bash
# NOTE: this script is stale/orphaned — PID and LOGFILE point at the old
# pre-migration project path (telegram_audio_bot), not the current
# log-by-voice layout. Left untouched functionally; only translated the
# terminal-facing text. Update PID/LOGFILE before relying on it again.
PID=1091822
LOGFILE="$HOME/telegram_audio_bot/bot.log"
STDOUT="/tmp/bot_stdout.log"

for i in $(seq 1 60); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "PROCESS_DEAD"
        echo "--- stdout/stderr ---"
        cat "$STDOUT" 2>/dev/null
        echo "--- bot.log ---"
        cat "$LOGFILE" 2>/dev/null
        exit 1
    fi
    if [ -s "$LOGFILE" ] && grep -q "Starting bot" "$LOGFILE"; then
        echo "BOT_STARTED"
        cat "$LOGFILE"
        exit 0
    fi
    sleep 2
done

echo "TIMEOUT_WAITING_FOR_STARTUP"
echo "--- stdout/stderr ---"
cat "$STDOUT" 2>/dev/null
exit 2
