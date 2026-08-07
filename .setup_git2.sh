#!/bin/bash
set -euo pipefail
cd ~/telegram_audio_bot

git add -A
git status --short

git commit -m "Migrar setup de venv/pip para uv (pyproject.toml + uv.lock)"

git push

echo "=== done ==="
