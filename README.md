# Log by Voice: Telegram Audio Bot → Obsidian

A Telegram bot that transcribes voice messages locally, automatically classifies
them with fast patterns + a local LLM, and writes structured entries into an
Obsidian daily note. Everything runs **offline and locally** — your data never
leaves the machine.

## Language

This bot is built to process **Portuguese** audio and text. The codebase,
comments, logs, and this documentation are in English, but the bot's actual
runtime behavior — what it transcribes, how it classifies content, what it
writes to the vault, and what it replies on Telegram — is Portuguese-only
today.

- `WHISPER_LANGUAGE` (in `.env`) controls the transcription language
  (default `pt`). This is the language config option.
- Changing `WHISPER_LANGUAGE` alone does **not** make the bot support another
  language end-to-end. The LLM classification prompt (`prompt_classify.txt`)
  and the regex patterns (`patterns.py`) are hardcoded for Portuguese —
  supporting a different language would require translating those too.
- Vault content, Telegram replies, and section headings (e.g. `### 📓
  Anotações`) are Portuguese by design, since they're written into a
  Portuguese-language personal vault.

## Architecture

```
You send audio via Telegram
           ↓
       Bot (polling)
           ↓
    [Transcription] — Whisper (local, GPU)
           ↓
    [Classification] — 2 phases:
        Phase 1: Pattern matching (regex, fast ~0ms)
        Phase 2: Local LLM (Ollama, fallback ~5-8s)
           ↓
    [Formatting] — JSON structure → Markdown
           ↓
    Obsidian daily note (real time)
           ↓
    Bot replies on Telegram: "✅ RESUMO: ..."
```

## Tech stack

- **Bot**: `python-telegram-bot` (async, polling)
- **Transcription**: `faster-whisper` large-v3 (local, GPU-capable)
- **Classification**:
  - Phase 1: structured regexes in `patterns.py` (70-80% of cases)
  - Phase 2: remote LLM (Ollama) with a structured prompt (`prompt_classify.txt`)
- **LLM**: **Ollama** (`gemma4:e2b` on an RTX 2060 GPU, ~86 tok/s)
- **Storage**:
  - Transcripts: `AUDIO_LOGS_DIR` (Windows)
  - Vault: `OBSIDIAN_VAULT_DIR` (Windows, accessed via `/mnt/d`)
- **Platform**: WSL2 Ubuntu (Linux filesystem for Python performance)

## What the bot classifies

Recognized item types:
- **`task`** — "Preciso arrumar o portão" → a task with optional priority/date
- **`habit_log`** — "Corri 30 min" → a habit log (`cardio`, `weight`, `piano`, `lifting`, `food`, `expense`)
- **`comment`** — free text with no structured classification
- **`mark_done`** — "Concluído: aquela tarefa" → marks a previous task as done
- **`correction`** — "Corrige: anterior, coloca X" → edits a previous item
- **`complement`** — "Complementa: e também Y" → adds detail to a previous item
- **`recurring_task`** — "Mensalmente: pagar conta" → a recurring task

Recognition examples (input is spoken Portuguese, since that's what the bot processes):
```
Input: "Comprei pão e leite (R$25)"
→ expense: description="pão e leite", amount=25.0, category="Mercado"

Input: "Peso: 82.5"
→ habit_log: habit="weight", weight_kg=82.5

Input: "Muito cansado hoje"
→ comment: "Muito cansado hoje"  [LLM fallback — ambiguous]

Input: "modo IA: é um texto que só a IA vai entender, ignora patterns"
→ [forces the call straight to the LLM, bypassing patterns]
```

## Prerequisites

Machine:
- **WSL2** (Windows Subsystem for Linux 2) with Ubuntu
- **Python 3.12+** with `uv` (package manager)
- **Ollama** (local LLM server) — supports GPU via WSL2 passthrough

External accounts:
- **Telegram Bot Token** — create one via `@BotFather`, copy the token
- **Your Telegram ID** — send a message to `@userinfobot`
- **Obsidian Vault** — a folder with `10 Daily/` where the notes live

## Installation

### 1. Clone / prepare the project

```bash
git clone https://github.com/caio-donalisio/log-by-voice.git
cd log-by-voice
uv sync  # creates .venv + installs dependencies (python-telegram-bot, faster-whisper, ollama)
```

### 2. Configure environment variables

```bash
cp .env.example .env
nano .env  # or your preferred editor
```

Fill in the essential fields:
- `TELEGRAM_BOT_TOKEN` — token from `@BotFather`
- `ALLOWED_TELEGRAM_USER_ID` — your numeric Telegram ID
- `AUDIO_LOGS_DIR` — folder to store `.ogg` + `.txt` (Windows path via `/mnt/`)
- `OBSIDIAN_VAULT_DIR` — Obsidian root (where the notes are)
- `LOCAL_LLM_MODEL` — Ollama model (default: `gemma4:e2b`, ~7.2GB)
- `OLLAMA_HOST` — Ollama URL (default: `http://localhost:11434`)

Optional (sensible defaults provided):
- `WHISPER_MODEL_SIZE` — `large-v3` (recommended) or `medium` (faster)
- `WHISPER_LANGUAGE` — `pt` (Portuguese) — see [Language](#language)
- `LOCAL_TIMEZONE` — local timezone (Brazil: `America/Sao_Paulo`)
- `LOCAL_LLM_TIMEOUT_SECONDS` — timeout for Ollama calls (120s)

### 3. Start Ollama

```bash
# Should already be running as a systemd service, but you can check:
sudo systemctl status ollama

# Or start it manually:
ollama serve

# Pull a model (one time only):
ollama pull gemma4:e2b
# alternatives: qwen2.5:7b, llama3.2:3b (smaller/faster), mistral:7b
```

### 4. Test it

```bash
uv run bot.py
```

You'll see in the log:
- Whisper loading (~1-5min the first time, then cached)
- `Application started polling` — bot ready to receive audio

Send an audio message via Telegram from the authorized account. The bot should:
1. Download the audio to `AUDIO_LOGS_DIR/{timestamp}_{id}.ogg`
2. Transcribe it (a few seconds with GPU, ~1min on CPU)
3. Classify it (pattern matching +/- LLM, ~5-8s)
4. Write it to the Obsidian daily note
5. Reply on Telegram: `✅ RESUMO: [classified items]`

On error, the bot notifies you on Telegram and the `.txt` transcript stays saved (nothing is lost).

**Tip**: run `tail -f bot.log` in another terminal to watch logs in real time.

## Running it 24/7

The bot runs continuous polling — it needs to stay on to receive audio.

### Option A: Windows Task Scheduler (simple)

1. Open **Task Scheduler** (`taskschd.msc`)
2. *Create Basic Task*:
   - Name: `Log by Voice Bot`
   - Trigger: *At log on*
   - Action: *Start a program*
     - Program: `wsl.exe`
     - Arguments: `-d Ubuntu-Personal -- bash -lc "cd ~/log-by-voice && uv run bot.py"`
3. OK. On the next login, the bot starts automatically.

### Option B: systemd on WSL (recommended — restarts on crash)

1. Confirm systemd is active:
   ```bash
   cat /etc/wsl.conf | grep systemd
   # should contain: [boot]\nsystemd=true
   ```
   If not, add it and run `wsl.exe --shutdown` (PowerShell), then reopen WSL.

2. Create `/etc/systemd/system/log-by-voice.service`:
   ```ini
   [Unit]
   Description=Log by Voice Telegram Bot
   After=network-online.target

   [Service]
   Type=simple
   User=$USER
   WorkingDirectory=/home/$USER/log-by-voice
   ExecStart=/home/$USER/.local/bin/uv run bot.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable it:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now log-by-voice.service
   sudo systemctl status log-by-voice.service  # verify
   ```

4. View logs:
   ```bash
   sudo journalctl -u log-by-voice -f  # streaming
   tail -f bot.log  # or the local file
   ```

## Detailed technical flow

### 1. Audio reception (`bot.py`)

```
You: [audio message on Telegram]
        ↓
bot.py polling (long-lived getUpdates)
        ↓
Check: sender ID == ALLOWED_TELEGRAM_USER_ID?
        ↓ yes
Download .ogg using the audio's own timestamp (not receipt time)
        ↓
Save to AUDIO_LOGS_DIR/{YYYYMMDD}_{HHMMSS}_{msg_id}.ogg
```

### 2. Transcription (`bot.py` + `faster-whisper`)

```
.ogg → faster-whisper (local, GPU-accelerated)
        ↓
Model: large-v3 (Portuguese)
        ↓
Transcript .txt saved alongside the audio
        ↓
Example output: "Corri 30 minutos hoje e peso 82 quilos"
```

**Performance**:
- GPU (RTX 2060): 30-60s for a 1-2 min audio
- CPU: 2-5 min
- Model cached after download (~1.6GB in `~/.cache/huggingface`)

### 3. Classification (`classifier.py` + `patterns.py` + Ollama)

#### Phase 1: Pattern Matching (fast, ~0ms)

Structured regexes cover ~70-80% of cases, without touching the LLM:

```python
# examples of patterns in patterns.py:
weight_pattern = r"(?:peso|weight)[:,\s]*(\d+(?:[.,]\d+)?)\s*kg"
  → "Peso: 82.5" → habit_log(weight=82.5)

task_pattern = r"(?:preciso|tenho que|need to)\s+(.+?)(?:\.|$)"
  → "Preciso arrumar o portão" → task(description="arrumar o portão")

cardio_pattern = r"(?:corri|correr|running)\s+(\d+)\s*min"
  → "Corri 30 min" → habit_log(cardio, activity="corri", minutes=30)

# expense patterns recognize R$ alongside a number:
expense_pattern = r"R\$?\s*(\d+(?:[.,]\d+)?)\s*(?:em|para|de)?\s+(.+)"
  → "Comprei pão e leite R$25" → expense(amount=25, desc="pão e leite")
```

**Phase 1 result**: a list of `Item` + unclassified text (`unmatched`)

#### Phase 2: LLM Fallback (smart, ~5-8s)

If `unmatched` is non-empty, it's sent to Ollama:

```
unmatched text → prompt_classify.txt → Ollama (gemma4:e2b)
                                          ↓
                                    structured JSON
                                    [{"type":"comment", "data":{...}},...]
                                          ↓
                                    JSON parser (with fallback if malformed)
```

**Prompt structure** (`prompt_classify.txt`, in Portuguese — see [Language](#language)):
- Defines the schema (types, fields, rules)
- Passes the unclassified text
- Includes already-classified items as context (to avoid duplication)
- Strict rules: never invent numbers, use "comment" when unsure

**LLM example**:
```
Input (unmatched): "Muito cansado hoje"
Ollama response: [{"type":"comment", "data":{"text":"Muito cansado hoje"}}]
```

**Ollama performance**:
- First call (cold start): ~22s (loads the model into VRAM)
- Subsequent calls: ~5-8s (model already in memory)
- Throughput: ~86 tokens/second (RTX 2060 GPU)

### 4. Calorie estimation (optional, for `habit_log/food`)

If classified as food WITHOUT explicit calories:

```
description="pão e leite" → prompt to Ollama
                               ↓
                         "estimate ~250 kcal"
                               ↓
Complete item: {calories: 250, estimated: true}
```

### 5. Formatting and writing (`formatter.py`, `daily_note.py`, `edits.py`)

Each `Item` → Markdown:

```python
# Example: task(description="arrumar portão", priority="alta")
# → "- [ ] **ALTA** Arrumar portão"

# Example: habit_log(cardio, minutes=30)
# → "**🏃 Cardio**: 30 min (correr)"

# Example: mark_done(task_hint="portão")
# → looks up a previous task matching "portão" → marks it as ✅

# Example: expense(amount=25, category="Mercado")
# → "💰 Mercado: R$25"
```

**Deterministic**: pure Python, no LLM — each type has a fixed template.

Writes to:
```
OBSIDIAN_VAULT_DIR/10 Daily/YYYY-MM-DD.md
  (created if it doesn't exist)

Sections (Portuguese headings — see Language section):
  ### 📓 Anotações         [comments]
  ### ✅ Tarefas           [tasks]
  ### 🏃 Hábitos           [habit_logs]
  ...
```

### 6. Telegram reply

The bot replies with a summary (in Portuguese, see [Language](#language)):

```
✅ RESUMO: 1 tarefa + 1 cardio + 1 comment
```

On error in any phase:
```
❌ Erro: [technical description]
```

The `.txt` transcript is ALWAYS kept even if classification fails.

## Main files

| File | Purpose |
|---------|--------|
| `bot.py` | Main entry point: polling, download, coordination |
| `classifier.py` | Classification orchestration (patterns + LLM) |
| `patterns.py` | ~500 lines of regexes + heuristics |
| `formatter.py` | Item → deterministic Markdown |
| `daily_note.py` | Reading/writing the Obsidian daily note file |
| `edits.py` | Edit operations (mark_done, correction, etc.) |
| `calorie_estimator.py` | Minimal prompt to estimate kcal |
| `prompt_classify.txt` | LLM prompt (schema + rules) |

## Performance tuning

### Whisper GPU

If you have an NVIDIA GPU:
```bash
# Check availability
nvidia-smi

# CUDA installed via WSL2 passthrough (automatic on W11+)
# faster-whisper detects it on its own and uses the GPU
```

Whisper on GPU: 30-60s per audio (2-5min on CPU).

### Ollama GPU

WSL2 supports NVIDIA GPU passthrough:
```bash
# Check detection
ollama list  # shows PROCESSOR: CPU/GPU
```

If Ollama shows `100% CPU`: check the NVIDIA WSL driver (it may be outdated).

### Custom Ollama model

Switch the model in `.env`:
```bash
# Fast (CPU + GPU):
LOCAL_LLM_MODEL=llama3.2:3b    # 2GB, ~100 tok/s (CPU)

# Balanced:
LOCAL_LLM_MODEL=qwen2.5:7b     # 4.4GB, recommended for Portuguese

# Powerful:
LOCAL_LLM_MODEL=gemma4:e2b     # 7.2GB, current (GPU recommended)
LOCAL_LLM_MODEL=mistral:7b     # 4GB, good at following patterns
```

Pull a new one: `ollama pull qwen2.5:7b`

## Troubleshooting

### Bot not responding

1. Check the token: `echo $TELEGRAM_BOT_TOKEN` (should not be empty)
2. Check the authorized ID: send `/start` on Telegram, see which ID shows up in the log
3. Check Ollama: `curl http://localhost:11434/api/version` (should return JSON)
4. Logs: `tail -f bot.log` + `journalctl -u ollama -f`

### Slow transcription

1. Is Whisper on CPU? Run `nvidia-smi` to check the GPU
2. Model too large? Try `WHISPER_MODEL_SIZE=medium`

### Slow classification (>15s)

1. Is Ollama on CPU? `ollama ps` should show `100% GPU`
2. Model too small? Try `llama3.2:3b` for a quick test
3. LLM not responding? Check `sudo journalctl -u ollama`

### Obsidian note not updating

1. Correct vault path? `ls -la "$OBSIDIAN_VAULT_DIR/10 Daily/"`
2. Was the `.md` file created? `ls -la "$OBSIDIAN_VAULT_DIR/10 Daily/$(date +%Y-%m-%d).md"`
3. Formatting error? Check `bot.log` for write-related stderr

## Tests

```bash
# Run the test suite (35 tests, ~10s)
uv run pytest -v

# Run a specific test
uv run pytest tests/ -k classify -v

# Coverage
uv run pytest --cov=.
```
