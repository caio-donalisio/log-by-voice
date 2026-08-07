#!/bin/bash
PID=1091822
LOGFILE="$HOME/telegram_audio_bot/bot.log"
STDOUT="/tmp/bot_stdout.log"

for i in $(seq 1 60); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "PROCESSO_MORTO"
        echo "--- stdout/stderr ---"
        cat "$STDOUT" 2>/dev/null
        echo "--- bot.log ---"
        cat "$LOGFILE" 2>/dev/null
        exit 1
    fi
    if [ -s "$LOGFILE" ] && grep -q "Iniciando bot" "$LOGFILE"; then
        echo "BOT_INICIADO"
        cat "$LOGFILE"
        exit 0
    fi
    sleep 2
done

echo "TIMEOUT_AGUARDANDO_STARTUP"
echo "--- stdout/stderr ---"
cat "$STDOUT" 2>/dev/null
exit 2
