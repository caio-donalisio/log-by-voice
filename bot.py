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
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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
WHISPER_TIMEOUT_SECONDS = int(os.environ.get("WHISPER_TIMEOUT_SECONDS", "300"))
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "America/Sao_Paulo"))
CLAUDE_CLI_PATH = os.environ.get("CLAUDE_CLI_PATH", "claude")
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR")  # opcional, equivalente a um alias tipo `claude-caio`
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "240"))

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
claude_lock = asyncio.Lock()

# Lido do disco a cada áudio (não carregado uma vez só na memória) — editar
# esse arquivo muda o comportamento do bot no próximo áudio, sem reiniciar.
PROMPT_TEMPLATE_PATH = BASE_DIR / "prompt_template.txt"


def _source_env_file(path: Path, target_env: dict[str, str]) -> None:
    """Parse a shell-style env file (export KEY=VALUE) into *target_env*."""
    import re
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip "export " prefix
        line = re.sub(r"^export\s+", "", line)
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip().strip("'").strip('"')
            target_env[key.strip()] = value
    # Claude CLI uses ANTHROPIC_API_KEY, not ANTHROPIC_AUTH_TOKEN
    if "ANTHROPIC_AUTH_TOKEN" in target_env and "ANTHROPIC_API_KEY" not in target_env:
        target_env["ANTHROPIC_API_KEY"] = target_env["ANTHROPIC_AUTH_TOKEN"]


def transcribe_audio(path: Path) -> str:
    segments, _info = whisper_model.transcribe(str(path), language=WHISPER_LANGUAGE)
    return " ".join(segment.text.strip() for segment in segments).strip()


def run_claude_cli(prompt: str) -> tuple[bool, str]:
    env = os.environ.copy()
    if CLAUDE_CONFIG_DIR:
        env["CLAUDE_CONFIG_DIR"] = CLAUDE_CONFIG_DIR

    # Load DeepSeek env vars if available
    _deepseek_env = Path(os.environ.get("DEEPSEEK_ENV_FILE", Path.home() / "deepseek.sh"))
    if _deepseek_env.exists():
        _source_env_file(_deepseek_env, env)
        # Use flash model for bot calls (fast + cheap, don't need 1M context)
        env["ANTHROPIC_MODEL"] = env.get(
            "ANTHROPIC_DEFAULT_HAIKU_MODEL", "deepseek-v4-flash"
        )

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
) -> tuple[str | None, str]:
    """Format and write a single validated item to the vault.

    Returns ``(relative_path, undo_id)`` where *relative_path* is the
    path of the modified file (or ``None`` if nothing was written) and
    *undo_id* is a short action ID for ``/undo``.
    """
    from formatter import (
        format_task, format_comment, format_weight, format_cardio,
        format_food, format_expense, format_piano, format_lifting,
        find_and_mark_done, find_and_correct, find_and_complement,
        format_recurring, append_to_section,
        resolve_piece, resolve_exercise,
    )

    item_type = item.type
    data = item.data
    undo_id = _next_undo_id()

    if item_type == "task":
        line = format_task(data, time_str)
        # Read current content for undo
        old_lines = daily_note_path.read_text(encoding="utf-8") if daily_note_path.exists() else ""
        append_to_section(daily_note_path, "### ✅ Tarefas Registradas", [line])
        _register_undo(undo_id, daily_note_path, -1, old_lines)
        return str(_rel_path(daily_note_path, vault_dir)), undo_id

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
            return None, undo_id
        append_to_section(daily_note_path, "### 📓 Anotações", [line])
        _register_undo(undo_id, daily_note_path, -1, "")
        return str(_rel_path(daily_note_path, vault_dir)), undo_id

    elif item_type == "comment":
        line = format_comment(data)
        append_to_section(daily_note_path, "### 📓 Anotações", [line])
        _register_undo(undo_id, daily_note_path, -1, "")
        return str(_rel_path(daily_note_path, vault_dir)), undo_id

    elif item_type == "mark_done":
        result_path, warns = find_and_mark_done(
            data.task_hint, date_str, vault_dir,
            is_recurring=data.is_recurring,
            comment=data.comment,
        )
        warnings_out.extend(warns)
        if result_path:
            _register_undo(undo_id, Path(result_path), -1, "")
        return (str(_rel_path(Path(result_path), vault_dir)) if result_path else None), undo_id

    elif item_type == "correction":
        result_path, warns = find_and_correct(
            data.search_hint, data.new_field, data.new_value,
            vault_dir, data.search_scope,
        )
        warnings_out.extend(warns)
        if result_path:
            _register_undo(undo_id, Path(result_path), -1, "")
        return (str(_rel_path(Path(result_path), vault_dir)) if result_path else None), undo_id

    elif item_type == "complement":
        result_path, warns = find_and_complement(
            data.search_hint, data.detail, vault_dir,
        )
        warnings_out.extend(warns)
        if result_path:
            _register_undo(undo_id, Path(result_path), -1, "")
        return (str(_rel_path(Path(result_path), vault_dir)) if result_path else None), undo_id

    elif item_type == "recurring_task":
        line, warn = format_recurring(data, date_str, vault_dir)
        if line:
            target = vault_dir / "10 Daily" / "Tarefas Recorrentes.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            old = target.read_text(encoding="utf-8") if target.exists() else ""
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n" + line + "\n")
            _register_undo(undo_id, target, -1, old)
            if warn:
                warnings_out.append(warn)
            return str(_rel_path(target, vault_dir)), undo_id
        if warn:
            warnings_out.append(warn)
        return None, undo_id

    elif item_type == "undo":
        import re
        from formatter.edits import _find_match, _read, _write
        hint = getattr(data, 'task_hint', '')
        match = _find_match(hint, vault_dir)
        if match is None:
            warnings_out.append(
                f"Não encontrei a tarefa '{hint}' para desfazer."
            )
            return None, undo_id
        lines = _read(match.path)
        old = lines[match.line_number - 1]
        if '[x]' in old:
            new_line = old.replace('[x]', '[ ]')
            new_line = re.sub(r'\s*✅\s*\S+', '', new_line)
            lines[match.line_number - 1] = new_line
            _write(match.path, lines)
            _register_undo(undo_id, match.path, match.line_number, old)
            return str(_rel_path(match.path, vault_dir)), undo_id
        elif old.strip().startswith('- [ ]'):
            del lines[match.line_number - 1]
            _write(match.path, lines)
            _register_undo(undo_id, match.path, match.line_number, old)
            return str(_rel_path(match.path, vault_dir)), undo_id
        else:
            warnings_out.append(
                f"Encontrei '{hint}' mas não sei como desfazer esse tipo de linha."
            )
            return None, undo_id

    return None, undo_id


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
        logger.info("Áudio %s já processado, ignorando duplicata.", audio_path.name)
        return

    tg_file = await media.get_file()
    await tg_file.download_to_drive(str(audio_path))
    logger.info("Áudio salvo em %s", audio_path)

    async with claude_lock:
        loop = asyncio.get_running_loop()

        try:
            transcript = await asyncio.wait_for(
                loop.run_in_executor(None, transcribe_audio, audio_path),
                timeout=WHISPER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("Transcrição de %s excedeu timeout (%ds)", audio_path, WHISPER_TIMEOUT_SECONDS)
            await message.reply_text(
                "⚠️ A transcrição demorou demais e foi cancelada. "
                "O áudio foi salvo e será reprocessado na próxima tentativa."
            )
            # Delete transcript_path so it gets retried (not skipped as duplicate)
            transcript_path.unlink(missing_ok=True)
            return
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
                        None, estimate_calories, _needs_calories, run_claude_cli
                    )
                    for i, cals in cal_map.items():
                        items[i].data.calories = cals
                        items[i].data.estimated = True
                    if cal_map:
                        logger.info(
                            "Calorias estimadas para %d/%d itens de comida",
                            len(cal_map), len(_needs_calories),
                        )
                except Exception:
                    logger.exception("Falha ao estimar calorias — seguindo sem estimativa")
                    # Don't crash the pipeline — just skip calorie estimation

            # Phase 4 — Format + write each item
            warnings: list[str] = []
            target_files: list[str] = []
            undo_ids: list[str] = []
            for item in items:
                target, uid = _dispatch_item(
                    item, date_str, time_str, OBSIDIAN_VAULT_DIR,
                    daily_note_path, warnings,
                )
                if target:
                    target_files.append(target)
                undo_ids.append(uid)

            # Phase 5 — Generate RESUMO
            resumo = generate_resumo(
                items, target_files, undo_ids, warnings, daily_created,
            )

        except Exception:
            logger.exception("Falha no pipeline de classificação")
            await message.reply_text(
                "⚠️ A transcrição foi salva, mas houve um erro ao processar: "
                f"verifique o log. Transcrição: {transcript_path}"
            )
            return

    await message.reply_text(f"✅ {resumo}")


# Undo registry — maps action IDs to file+line snapshots for /undo
_undo_registry: dict[str, tuple[Path, int, str]] = {}  # id → (path, line_num, old_content)
_undo_counter = 0


def _next_undo_id() -> str:
    """Generate a short action ID: 1, 2, 3, ..."""
    global _undo_counter
    _undo_counter += 1
    return str(_undo_counter)


def _register_undo(undo_id: str, file_path: Path, line_number: int, old_content: str) -> None:
    """Remember a modification for potential undo. Max 50 entries."""
    _undo_registry[undo_id] = (file_path, line_number, old_content)
    # Prune old entries if too many
    while len(_undo_registry) > 50:
        oldest = next(iter(_undo_registry))
        del _undo_registry[oldest]


async def handle_undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /undo [id] — revert a bot action by ID, or the last one."""
    message = update.message
    if not message:
        return

    text = message.text.strip()
    import re as _re
    text = _re.sub(r"^/undo@\S+\s*", "", text)
    text = text.removeprefix("/undo").strip()

    if not _undo_registry:
        await message.reply_text("Nada para desfazer.")
        return

    # If no ID given, undo the most recent (last inserted)
    if not text:
        undo_id = next(reversed(_undo_registry))
    else:
        undo_id = text.upper()
        if undo_id not in _undo_registry:
            await message.reply_text(
                f"❌ ID \"{undo_id}\" não encontrado. IDs disponíveis: {', '.join(_undo_registry)}"
            )
            return

    file_path, line_num, old_content = _undo_registry.pop(undo_id)
    target = str(_rel_path(file_path, OBSIDIAN_VAULT_DIR))

    if not file_path.exists():
        await message.reply_text(f"❌ Arquivo {target} não existe mais.")
        return

    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if line_num > len(lines):
        await message.reply_text(f"❌ Linha {line_num} não existe mais em {target}.")
        return

    current = lines[line_num - 1]
    lines[line_num - 1] = old_content
    file_path.write_text("".join(lines), encoding="utf-8")

    await message.reply_text(
        f"↩️ [{undo_id}] Desfeito em {target}:\n"
        f"  Era: {current.strip()[:80]}\n"
        f"  Voltou: {old_content.strip()[:80]}"
    )


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
        "Iniciando bot (modelo Whisper=%s, vault=%s)", WHISPER_MODEL_SIZE, OBSIDIAN_VAULT_DIR
    )
    if not OBSIDIAN_VAULT_DIR.is_dir():
        logger.error(
            "VAULT INACESSÍVEL: %s — o bot vai iniciar mas falhará ao processar áudios.",
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
        logger.exception("Não foi possível enviar notificação de crash")


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
            "Encontrados %d áudio(s) órfão(s) (sem transcrição): %s",
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
                "Bot caiu de forma inesperada, reiniciando em %ss", backoff_seconds
            )
            # Notify user on Telegram
            _notify_crash(backoff_seconds)
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 300)


if __name__ == "__main__":
    main()
