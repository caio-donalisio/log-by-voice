"""
Telegram bot that receives audio messages (owner only), transcribes them
locally with faster-whisper, and uses a local LLM (Ollama) to classify the
transcript and generate entries in the Obsidian daily note.

Runs on WSL; the vault and the audio folder live on the Windows filesystem,
accessed via /mnt/... (see .env).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from faster_whisper import WhisperModel
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_TELEGRAM_USER_ID = int(os.environ["ALLOWED_TELEGRAM_USER_ID"])
AUDIO_LOGS_DIR = Path(os.environ["AUDIO_LOGS_DIR"])
OBSIDIAN_VAULT_DIR = Path(os.environ["OBSIDIAN_VAULT_DIR"])
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "medium")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "pt")
# "auto" tries CUDA if it detects a GPU, but on WSL this usually finds the
# driver without the cuBLAS/cuDNN libs installed and breaks at transcription
# time. CPU is the safe default; switch via WHISPER_DEVICE=cuda if you
# install the full CUDA toolkit on WSL.
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get(
    "WHISPER_COMPUTE_TYPE", "int8" if WHISPER_DEVICE == "cpu" else "auto"
)
WHISPER_TIMEOUT_SECONDS = int(os.environ.get("WHISPER_TIMEOUT_SECONDS", "300"))
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "America/Sao_Paulo"))
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "llama3.1:8b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOCAL_LLM_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "120"))

AUDIO_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("telegram_audio_bot")
logger.setLevel(logging.INFO)

# Avoid duplicate handlers on hot-reload
if not logger.handlers:
    _console_handler = logging.StreamHandler()
    _file_handler = RotatingFileHandler(
        BASE_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    _formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    for _h in (_console_handler, _file_handler):
        _h.setFormatter(_formatter)
        logger.addHandler(_h)

# Ensure submodule logs are visible: configure each and set propagation
_pkg_loggers = ["patterns", "classifier", "calorie_estimator", "formatter"]
for _name in _pkg_loggers:
    _pkg = logging.getLogger(_name)
    _pkg.setLevel(logging.INFO)
    _pkg.propagate = True

# Add our handlers to root so propagated messages are captured
_root = logging.getLogger()
_root.setLevel(logging.INFO)
if _console_handler not in _root.handlers:
    _root.addHandler(_console_handler)
if _file_handler not in _root.handlers:
    _root.addHandler(_file_handler)

whisper_model = WhisperModel(
    WHISPER_MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
)
llm_lock = asyncio.Lock()

# Read from disk on every audio (not loaded once into memory) — editing
# this file changes the bot's behavior on the next audio, without a restart.


def transcribe_audio(path: Path) -> str:
    segments, _info = whisper_model.transcribe(str(path), language=WHISPER_LANGUAGE)
    return " ".join(segment.text.strip() for segment in segments).strip()


def run_local_llm(prompt: str, system_prompt: str = "") -> tuple[bool, str]:
    """Run a prompt against the local Ollama model.

    Returns ``(success, output_text)`` — same signature the classifier and
    calorie estimator expect.
    """
    import ollama

    client = ollama.Client(host=OLLAMA_HOST)

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        response = client.chat(
            model=LOCAL_LLM_MODEL,
            messages=messages,
            options={
                "temperature": 0.1,   # low temp for structured output
                "num_predict": 1024,  # max tokens — classification outputs are small
            },
        )
    except Exception as exc:
        logger.error("Error calling Ollama (%s): %s", LOCAL_LLM_MODEL, exc)
        return False, f"Ollama failed: {exc}"

    output = response["message"]["content"].strip()
    tokens = response.get("eval_count") or response.get("done_count") or 0
    logger.info(
        "Local LLM (%s): %d tokens generated (load=%s ms, eval=%s ms)",
        LOCAL_LLM_MODEL,
        tokens,
        response.get("load_duration", "?"),
        response.get("eval_duration", "?"),
    )
    return True, output


def extract_resumo(llm_output: str) -> str:
    """Deprecated — kept for reference.  New pipeline uses formatter.resumo."""
    for line in reversed(llm_output.splitlines()):
        line = line.strip()
        if line.startswith("RESUMO:"):
            return line[len("RESUMO:"):].strip()
    return llm_output[-300:] if llm_output else "(sem saída do LLM)"


def _dispatch_item(
    item,
    date_str: str,
    time_str: str,
    vault_dir: Path,
    daily_note_path: Path,
    warnings_out: list[str],
) -> tuple[str | None, str, str | None]:
    """Format and write a single validated item to the vault.

    Returns ``(relative_path, undo_id, formatted_line)`` where *relative_path* is the
    path of the modified file (or ``None`` if nothing was written), *undo_id* is a short
    action ID for ``/undo``, and *formatted_line* is the exact content written.
    """
    from formatter import (
        format_task, format_comment, format_weight, format_cardio,
        format_food, format_expense, format_piano, format_lifting,
        resolve_piece, resolve_exercise, MarkDoneData,
    )
    from daily_note import append_to_section
    from edits import find_and_mark_done, find_and_correct, find_and_complement, format_recurring

    item_type = item.type
    data = item.data
    undo_id = _next_undo_id()

    if item_type == "task":
        line = format_task(data, time_str)
        _snapshot_for_undo(undo_id, daily_note_path)
        append_to_section(daily_note_path, "### ✅ Tarefas Registradas", [line])
        return str(_rel_path(daily_note_path, vault_dir)), undo_id, line

    elif item_type == "habit_log":
        habit = item.habit
        if habit == "weight":
            line = format_weight(data, time_str)
        elif habit == "cardio":
            line = format_cardio(data, date_str, time_str)
        elif habit == "food":
            line = format_food(data, time_str)
        elif habit == "expense":
            line = format_expense(data, time_str)
        elif habit == "piano":
            piece, score = resolve_piece(data.piece_hint, vault_dir)
            line = format_piano(data, piece, time_str)
            if score < 1.0:
                warnings_out.append(
                    f"Não encontrei nota existente para '{data.piece_hint}', "
                    f"usei [[{piece}]]"
                )
        elif habit == "lifting":
            exercise, score = resolve_exercise(data.exercise_hint, vault_dir)
            line = format_lifting(data, exercise, time_str)
            if score < 1.0 and score > 0.0:
                warnings_out.append(
                    f"Não encontrei nota existente para "
                    f"'{data.exercise_hint}', usei [[{exercise}]]"
                )
        else:
            return None, undo_id, None
        append_to_section(daily_note_path, "### 📓 Anotações", [line])
        _snapshot_for_undo(undo_id, daily_note_path)
        return str(_rel_path(daily_note_path, vault_dir)), undo_id, line

    elif item_type == "comment":
        line = format_comment(data)
        append_to_section(daily_note_path, "### 📓 Anotações", [line])
        _snapshot_for_undo(undo_id, daily_note_path)
        return str(_rel_path(daily_note_path, vault_dir)), undo_id, line

    elif item_type == "mark_done":
        result_path, warns, old_line, new_line = find_and_mark_done(
            data.task_hint, date_str, vault_dir,
            is_recurring=data.is_recurring,
            comment=data.comment,
        )
        warnings_out.extend(warns)
        if result_path and old_line:
            _snapshot_for_undo(undo_id, Path(result_path))
        return (str(_rel_path(Path(result_path), vault_dir)) if result_path else None), undo_id, new_line if result_path else None

    elif item_type == "correction":
        result_path, warns, old_line, new_line = find_and_correct(
            data.search_hint, data.new_field, data.new_value,
            vault_dir, data.search_scope,
        )
        warnings_out.extend(warns)
        if result_path:
            _snapshot_for_undo(undo_id, Path(result_path))
        return (str(_rel_path(Path(result_path), vault_dir)) if result_path else None), undo_id, new_line if result_path else None

    elif item_type == "complement":
        result_path, warns, line_num, inserted = find_and_complement(
            data.search_hint, data.detail, vault_dir,
        )
        warnings_out.extend(warns)
        if result_path:
            _snapshot_for_undo(undo_id, Path(result_path))
        return (str(_rel_path(Path(result_path), vault_dir)) if result_path else None), undo_id, inserted if result_path else None

    elif item_type == "recurring_task":
        line, warn = format_recurring(data, date_str, vault_dir)
        if line:
            target = vault_dir / "10 Daily" / "Tarefas Recorrentes.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            _snapshot_for_undo(undo_id, target)
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n" + line + "\n")
            if warn:
                warnings_out.append(warn)
            return str(_rel_path(target, vault_dir)), undo_id, line
        if warn:
            warnings_out.append(warn)
        return None, undo_id, None

    elif item_type == "undo":
        import re
        from edits import _find_match, _read, _write
        hint = getattr(data, 'task_hint', '')
        match = _find_match(hint, vault_dir)
        if match is None:
            warnings_out.append(
                f"Não encontrei a tarefa '{hint}' para desfazer."
            )
            return None, undo_id, None
        lines = _read(match.path)
        old = lines[match.line_number - 1]
        if '[x]' in old:
            new_line = old.replace('[x]', '[ ]')
            new_line = re.sub(r'\s*✅\s*\S+', '', new_line)
            lines[match.line_number - 1] = new_line
            _write(match.path, lines)
            _snapshot_for_undo(undo_id, match.path)
            return str(_rel_path(match.path, vault_dir)), undo_id, new_line
        elif old.strip().startswith('- [ ]'):
            _snapshot_for_undo(undo_id, match.path)
            del lines[match.line_number - 1]
            _write(match.path, lines)
            return str(_rel_path(match.path, vault_dir)), undo_id, f"[linha removida: {old.strip()}]"
        else:
            warnings_out.append(
                f"Encontrei '{hint}' mas não sei como desfazer esse tipo de linha."
            )
            return None, undo_id, None

    return None, undo_id, None


def _generate_exact_response(
    formatted_lines: list[tuple[str, str | None]],
    warnings: list[str],
    daily_created: bool,
) -> str:
    """Generate a response showing exactly what was persisted in Obsidian.

    Returns the exact formatted content with file paths, grouped by file.
    """
    if not formatted_lines and not warnings and not daily_created:
        return "✅ Nenhum item foi processado."

    # Group lines by file
    by_file: dict[str, list[str]] = {}
    for target_file, formatted_line in formatted_lines:
        if formatted_line:
            if target_file not in by_file:
                by_file[target_file] = []
            by_file[target_file].append(formatted_line)

    parts = []

    if daily_created:
        parts.append("📝 Nota diária criada")

    # Show each file's content
    for target_file in sorted(by_file.keys()):
        lines = by_file[target_file]
        file_section = [f"{target_file}:"]
        for line in lines:
            file_section.append(line)
        parts.append("\n".join(file_section))

    for warning in warnings:
        parts.append(f"⚠️ {warning}")

    return "✅\n" + "\n\n".join(parts)


def _rel_path(abs_path: Path, vault_dir: Path) -> Path:
    """Return path relative to vault root."""
    try:
        return abs_path.relative_to(vault_dir)
    except ValueError:
        return abs_path


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

    # Only skip if BOTH audio AND transcript exist (crashes leave orphan .ogg)
    if audio_path.exists() and transcript_path.exists():
        logger.info("Audio %s already processed, skipping duplicate.", audio_path.name)
        return

    tg_file = await media.get_file()
    await tg_file.download_to_drive(str(audio_path))
    logger.info("Audio saved to %s", audio_path)

    async with llm_lock:
        loop = asyncio.get_running_loop()

        try:
            transcript = await asyncio.wait_for(
                loop.run_in_executor(None, transcribe_audio, audio_path),
                timeout=WHISPER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("Transcription of %s exceeded timeout (%ds)", audio_path, WHISPER_TIMEOUT_SECONDS)
            await message.reply_text(
                "⚠️ A transcrição demorou demais e foi cancelada. "
                "O áudio foi salvo e será reprocessado na próxima tentativa."
            )
            # Delete transcript_path so it gets retried (not skipped as duplicate)
            transcript_path.unlink(missing_ok=True)
            return
        except Exception:
            logger.exception("Failed to transcribe %s", audio_path)
            await message.reply_text(
                "Não consegui transcrever esse áudio. Ele ficou salvo em "
                f"{audio_path}, mas nada foi escrito no Obsidian."
            )
            return

        transcript_path.write_text(transcript, encoding="utf-8")
        logger.info("Transcript saved to %s", transcript_path)

        if not transcript:
            await message.reply_text(
                "A transcrição saiu vazia (áudio sem fala reconhecível?). "
                f"Arquivo mantido em {audio_path}."
            )
            return

        try:
            from classifier import classify_transcript
            from daily_note import ensure_daily_note

            # Phase 1 — Classify (pattern matching + optional LLM fallback)
            items, _unmatched = await loop.run_in_executor(
                None, classify_transcript, transcript, run_local_llm
            )

            # Phase 2 — Ensure daily note exists
            daily_note_path, daily_created = ensure_daily_note(
                OBSIDIAN_VAULT_DIR, date_str, time_str
            )

            # Phase 3 — Calorie estimation for food items without explicit numbers
            _needs_calories = [
                (i, item.data.description)
                for i, item in enumerate(items)
                if (
                    item.type == "habit_log"
                    and item.habit == "food"
                    and item.data.estimated
                    and item.data.calories is None
                )
            ]
            if _needs_calories:
                from calorie_estimator import estimate_calories
                try:
                    cal_map = await loop.run_in_executor(
                        None, estimate_calories, _needs_calories, run_local_llm
                    )
                    for i, cals in cal_map.items():
                        items[i].data.calories = cals
                        items[i].data.estimated = True
                    if cal_map:
                        logger.info(
                            "Estimated calories for %d/%d food items",
                            len(cal_map), len(_needs_calories),
                        )
                except Exception:
                    logger.exception("Failed to estimate calories — continuing without estimate")
                    # Don't crash the pipeline — just skip calorie estimation

            # Phase 4 — Format + write each item
            warnings: list[str] = []
            target_files: list[str] = []
            undo_ids: list[str] = []
            formatted_lines: list[tuple[str, str | None]] = []
            for item in items:
                target, uid, formatted_line = _dispatch_item(
                    item, date_str, time_str, OBSIDIAN_VAULT_DIR,
                    daily_note_path, warnings,
                )
                if target:
                    target_files.append(target)
                    formatted_lines.append((target, formatted_line))
                undo_ids.append(uid)

            # Phase 5 — Generate exact response
            response = _generate_exact_response(formatted_lines, warnings, daily_created)

        except Exception:
            logger.exception("Classification pipeline failed")
            await message.reply_text(
                "⚠️ A transcrição foi salva, mas houve um erro ao processar: "
                f"verifique o log. Transcrição: {transcript_path}"
            )
            return

    await message.reply_text(response)


# Undo stack — stores the last 5 file snapshots for /undo
_undo_stack: list[tuple[str, Path, str]] = []  # [(undo_id, path, file_content_before)]
_undo_counter = 0


def _next_undo_id() -> str:
    global _undo_counter
    _undo_counter += 1
    return str(_undo_counter)


def _snapshot_for_undo(undo_id: str, file_path: Path) -> None:
    """Snapshot a file before modification for undo. Keeps last 5."""
    content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    _undo_stack.append((undo_id, file_path, content))
    if len(_undo_stack) > 5:
        _undo_stack.pop(0)


async def handle_undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /undo — revert the most recent bot action."""
    message = update.message
    if not message: return

    if not _undo_stack:
        await message.reply_text("Nada para desfazer.")
        return

    undo_id, file_path, old_content = _undo_stack.pop()
    target = str(_rel_path(file_path, OBSIDIAN_VAULT_DIR))

    if old_content:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(old_content, encoding="utf-8")
        await message.reply_text(f"↩️ [{undo_id}] Desfeito: {target} restaurado.")
    else:
        file_path.unlink(missing_ok=True)
        await message.reply_text(f"↩️ [{undo_id}] Desfeito: {target} removido.")



def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    audio_filter = (filters.VOICE | filters.AUDIO) & filters.User(
        user_id=ALLOWED_TELEGRAM_USER_ID
    )
    application.add_handler(MessageHandler(audio_filter, handle_audio))
    # /undo command (text, same owner restriction)
    application.add_handler(
        CommandHandler("undo", handle_undo_command, filters=filters.User(user_id=ALLOWED_TELEGRAM_USER_ID))
    )
    return application


def main() -> None:
    # PID file — prevent double instances
    _pid_file = BASE_DIR / ".bot.pid"
    _pid_file.write_text(str(os.getpid()))

    logger.info(
        "Starting bot (Whisper model=%s, vault=%s)", WHISPER_MODEL_SIZE, OBSIDIAN_VAULT_DIR
    )
    if not OBSIDIAN_VAULT_DIR.is_dir():
        logger.error(
            "VAULT UNREACHABLE: %s — the bot will start but will fail to process audio.",
            OBSIDIAN_VAULT_DIR,
        )

    # Recover orphaned audio files (crashed before transcription completed)
    _recover_orphans()


def _notify_crash(delay: int) -> None:
    """Send a Telegram message to the owner notifying of a crash."""
    try:
        import httpx
        url = (
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
            f"/sendMessage"
        )
        payload = {
            "chat_id": ALLOWED_TELEGRAM_USER_ID,
            "text": (
                f"⚠️ O bot crashou e está reiniciando em {delay}s.\n"
                f"Verifique o log para detalhes."
            ),
        }
        httpx.post(url, json=payload, timeout=10)
    except Exception:
        logger.exception("Could not send crash notification")


def _recover_orphans() -> None:
    """Delete .ogg files that have no matching .txt (crashed before transcription).

    The Telegram update was already acknowledged, so these can't be re-fetched
    via polling.  Deleting the .ogg allows the user to re-send the audio.
    """
    orphans = []
    for ogg in AUDIO_LOGS_DIR.glob("*.ogg"):
        txt = ogg.with_suffix(".txt")
        if not txt.exists():
            orphans.append(ogg)
    if orphans:
        logger.warning(
            "Found %d orphaned audio file(s) (no transcript): %s",
            len(orphans),
            [o.name for o in orphans],
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
                "Bot crashed unexpectedly, restarting in %ss", backoff_seconds
            )
            # Notify user on Telegram
            _notify_crash(backoff_seconds)
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 300)


if __name__ == "__main__":
    main()
