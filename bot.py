"""
Bot do Telegram que recebe áudios (só do dono), transcreve localmente com
faster-whisper e aciona o Claude Code CLI para transformar a transcrição
numa entrada na nota diária do Obsidian.

Roda no WSL; o vault e a pasta de áudios ficam no filesystem do Windows,
acessados via /mnt/... (ver .env).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from faster_whisper import WhisperModel
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_TELEGRAM_USER_ID = int(os.environ["ALLOWED_TELEGRAM_USER_ID"])
AUDIO_LOGS_DIR = Path(os.environ["AUDIO_LOGS_DIR"])
OBSIDIAN_VAULT_DIR = Path(os.environ["OBSIDIAN_VAULT_DIR"])
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "medium")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "pt")
# "auto" tenta CUDA se detectar GPU, mas no WSL isso costuma achar o driver
# sem as libs cuBLAS/cuDNN instaladas e quebrar na hora de transcrever.
# CPU é o default seguro; troque via WHISPER_DEVICE=cuda se instalar o
# toolkit CUDA completo no WSL.
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get(
    "WHISPER_COMPUTE_TYPE", "int8" if WHISPER_DEVICE == "cpu" else "auto"
)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "America/Sao_Paulo"))
CLAUDE_CLI_PATH = os.environ.get("CLAUDE_CLI_PATH", "claude")
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR")  # opcional, equivalente a um alias tipo `claude-caio`
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "240"))

AUDIO_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("telegram_audio_bot")
logger.setLevel(logging.INFO)
_console_handler = logging.StreamHandler()
_file_handler = RotatingFileHandler(
    BASE_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
)
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
for _h in (_console_handler, _file_handler):
    _h.setFormatter(_formatter)
    logger.addHandler(_h)

whisper_model = WhisperModel(
    WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
)
claude_lock = asyncio.Lock()

# Lido do disco a cada áudio (não carregado uma vez só na memória) — editar
# esse arquivo muda o comportamento do bot no próximo áudio, sem reiniciar.
PROMPT_TEMPLATE_PATH = BASE_DIR / "prompt_template.txt"


def transcribe_audio(path: Path) -> str:
    segments, _info = whisper_model.transcribe(str(path), language=WHISPER_LANGUAGE)
    return " ".join(segment.text.strip() for segment in segments).strip()


def run_claude_cli(prompt: str) -> tuple[bool, str]:
    env = os.environ.copy()
    if CLAUDE_CONFIG_DIR:
        env["CLAUDE_CONFIG_DIR"] = CLAUDE_CONFIG_DIR

    try:
        result = subprocess.run(
            [
                CLAUDE_CLI_PATH,
                "-p",
                prompt,
                "--permission-mode",
                "acceptEdits",
                "--output-format",
                "json",
            ],
            cwd=str(OBSIDIAN_VAULT_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"Claude CLI excedeu o timeout de {CLAUDE_TIMEOUT_SECONDS}s."
    except FileNotFoundError:
        return False, (
            f"Não encontrei o executável '{CLAUDE_CLI_PATH}'. Confira o "
            "CLAUDE_CLI_PATH no .env."
        )

    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-500:]
        return False, f"Claude CLI retornou erro (code {result.returncode}): {stderr_tail}"

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Saída do Claude CLI não era JSON válido, usando texto bruto.")
        return True, result.stdout.strip()

    cost_usd = payload.get("total_cost_usd")
    usage = payload.get("usage") or {}
    if cost_usd is not None:
        logger.info(
            "Custo Claude: $%.4f (tokens entrada=%s cache_leitura=%s saída=%s)",
            cost_usd,
            usage.get("input_tokens"),
            usage.get("cache_read_input_tokens"),
            usage.get("output_tokens"),
        )

    if payload.get("is_error"):
        return False, f"Claude CLI retornou erro: {payload.get('result', '(sem detalhe)')}"

    return True, (payload.get("result") or "").strip()


def extract_resumo(claude_stdout: str) -> str:
    """Deprecated — kept for reference.  New pipeline uses formatter.resumo."""
    for line in reversed(claude_stdout.splitlines()):
        line = line.strip()
        if line.startswith("RESUMO:"):
            return line[len("RESUMO:"):].strip()
    return claude_stdout[-300:] if claude_stdout else "(sem saída do Claude)"


def _dispatch_item(
    item,
    date_str: str,
    time_str: str,
    vault_dir: Path,
    daily_note_path: Path,
    warnings_out: list[str],
) -> None:
    """Format and write a single validated item to the vault."""
    from formatter import (
        format_task, format_comment, format_weight, format_cardio,
        format_food, format_expense, format_piano, format_lifting,
        find_and_mark_done, find_and_correct, find_and_complement,
        format_recurring, append_to_section,
        resolve_piece, resolve_exercise,
    )

    item_type = item.type
    data = item.data

    if item_type == "task":
        line = format_task(data)
        append_to_section(daily_note_path, "### ✅ Tarefas Registradas", [line])

    elif item_type == "habit_log":
        habit = item.habit
        if habit == "weight":
            line = format_weight(data)
        elif habit == "cardio":
            line = format_cardio(data, date_str)
        elif habit == "food":
            line = format_food(data)
        elif habit == "expense":
            line = format_expense(data)
        elif habit == "piano":
            piece, score = resolve_piece(data.piece_hint, vault_dir)
            line = format_piano(data, piece)
            if score < 1.0:
                warnings_out.append(
                    f"Não encontrei nota existente para '{data.piece_hint}', "
                    f"usei [[{piece}]]"
                )
        elif habit == "lifting":
            exercise, score = resolve_exercise(data.exercise_hint, vault_dir)
            line = format_lifting(data, exercise)
            if score < 1.0 and score > 0.0:
                warnings_out.append(
                    f"Não encontrei nota existente para "
                    f"'{data.exercise_hint}', usei [[{exercise}]]"
                )
        else:
            return
        append_to_section(daily_note_path, "### 📓 Anotações", [line])

    elif item_type == "comment":
        line = format_comment(data)
        append_to_section(daily_note_path, "### 📓 Anotações", [line])

    elif item_type == "mark_done":
        result_path, warns = find_and_mark_done(
            data.task_hint, date_str, vault_dir,
            is_recurring=data.is_recurring,
            comment=data.comment,
        )
        warnings_out.extend(warns)

    elif item_type == "correction":
        result_path, warns = find_and_correct(
            data.search_hint, data.new_field, data.new_value,
            vault_dir, data.search_scope,
        )
        warnings_out.extend(warns)

    elif item_type == "complement":
        result_path, warns = find_and_complement(
            data.search_hint, data.detail, vault_dir,
        )
        warnings_out.extend(warns)

    elif item_type == "recurring_task":
        line, warn = format_recurring(data, date_str, vault_dir)
        if line:
            target = vault_dir / "10 Daily" / "Tarefas Recorrentes.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n" + line + "\n")
        if warn:
            warnings_out.append(warn)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    media = message.voice or message.audio
    if media is None:
        return

    local_dt = message.date.astimezone(LOCAL_TIMEZONE)
    date_str = local_dt.strftime("%Y-%m-%d")
    time_str = local_dt.strftime("%H:%M")
    stamp = local_dt.strftime("%Y%m%d_%H%M%S")

    audio_path = AUDIO_LOGS_DIR / f"{stamp}_{message.message_id}.ogg"
    transcript_path = audio_path.with_suffix(".txt")

    if audio_path.exists():
        logger.info("Áudio %s já processado, ignorando duplicata.", audio_path.name)
        return

    tg_file = await media.get_file()
    await tg_file.download_to_drive(str(audio_path))
    logger.info("Áudio salvo em %s", audio_path)

    async with claude_lock:
        loop = asyncio.get_running_loop()

        try:
            transcript = await loop.run_in_executor(None, transcribe_audio, audio_path)
        except Exception:
            logger.exception("Falha ao transcrever %s", audio_path)
            await message.reply_text(
                "Não consegui transcrever esse áudio. Ele ficou salvo em "
                f"{audio_path}, mas nada foi escrito no Obsidian."
            )
            return

        transcript_path.write_text(transcript, encoding="utf-8")
        logger.info("Transcrição salva em %s", transcript_path)

        if not transcript:
            await message.reply_text(
                "A transcrição saiu vazia (áudio sem fala reconhecível?). "
                f"Arquivo mantido em {audio_path}."
            )
            return

        try:
            from classifier import classify_transcript
            from formatter import ensure_daily_note, generate_resumo

            # Phase 1 — Classify (pattern matching + optional LLM fallback)
            items, _unmatched = await loop.run_in_executor(
                None, classify_transcript, transcript, run_claude_cli
            )

            # Phase 2 — Ensure daily note exists
            daily_note_path, daily_created = ensure_daily_note(
                OBSIDIAN_VAULT_DIR, date_str, time_str
            )

            # Phase 3 — Format + write each item
            warnings: list[str] = []
            for item in items:
                _dispatch_item(
                    item, date_str, time_str, OBSIDIAN_VAULT_DIR,
                    daily_note_path, warnings,
                )

            # Phase 4 — Generate RESUMO
            resumo = generate_resumo(items, warnings, daily_created)

        except Exception:
            logger.exception("Falha no pipeline de classificação")
            await message.reply_text(
                "⚠️ A transcrição foi salva, mas houve um erro ao processar: "
                f"verifique o log. Transcrição: {transcript_path}"
            )
            return

    await message.reply_text(f"✅ {resumo}")


def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    audio_filter = (filters.VOICE | filters.AUDIO) & filters.User(
        user_id=ALLOWED_TELEGRAM_USER_ID
    )
    application.add_handler(MessageHandler(audio_filter, handle_audio))
    return application


def main() -> None:
    logger.info(
        "Iniciando bot (modelo Whisper=%s, vault=%s)", WHISPER_MODEL_SIZE, OBSIDIAN_VAULT_DIR
    )
    backoff_seconds = 5
    while True:
        try:
            application = build_application()
            application.run_polling(allowed_updates=Update.ALL_TYPES)
            break
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception(
                "Bot caiu de forma inesperada, reiniciando em %ss", backoff_seconds
            )
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 300)


if __name__ == "__main__":
    main()
