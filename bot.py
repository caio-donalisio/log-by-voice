"""
Bot do Telegram que recebe áudios (só do dono), transcreve localmente com
faster-whisper e aciona o Claude Code CLI para transformar a transcrição
numa entrada na nota diária do Obsidian.

Roda no WSL; o vault e a pasta de áudios ficam no filesystem do Windows,
acessados via /mnt/... (ver .env).
"""

from __future__ import annotations

import asyncio
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
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "America/Sao_Paulo"))
CLAUDE_CLI_PATH = os.environ.get("CLAUDE_CLI_PATH", "claude")
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR")  # opcional, equivalente a um alias tipo `claude-caio`
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "180"))

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

whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="auto", compute_type="auto")
claude_lock = asyncio.Lock()

CLAUDE_PROMPT_TEMPLATE = """\
Você vai registrar a transcrição de um áudio pessoal na nota diária do Obsidian.

Nota de destino: `10 Daily/{date_str}.md` (data local em que o áudio foi gravado).

Passos:
1. Se o arquivo `10 Daily/{date_str}.md` NÃO existir, crie-o seguindo exatamente a
   mesma estrutura das notas diárias existentes nessa pasta (use `10 Daily/2025-10-13.md`
   como referência de formato): frontmatter com `date_created` (formato
   `{date_str}THH:mm` usando a hora atual), `tags: ["daily-task"]`, `aliases` com a
   data por extenso em português, no formato `DD/MM/YYYY` e por extenso com o ano;
   heading `# Nota Diária: <dia da semana por extenso>, <data por extenso em português>`;
   seção `### ✅ Tarefas Registradas` com um item vazio `- [ ]`; seção
   `### 📓 Anotações`; e depois os blocos de query `tasks` de Atrasadas / Para Hoje /
   Próximos 7 Dias, com as datas substituídas corretamente em relação a {date_str}
   (mesma lógica de datas usada no template `_templates/generic_daily_note.md`).
2. Se o arquivo já existir, NÃO mexa no frontmatter nem em nenhuma outra seção.
3. Em ambos os casos, adicione UM bullet novo dentro da seção `### 📓 Anotações`
   com o conteúdo da transcrição abaixo, levemente limpo (remova cacoetes de fala
   tipo "é", "tipo assim", repetições, mas preserve o sentido, o tom e as palavras
   do autor — não resuma, não invente e não adicione informação que não está na
   transcrição).
4. Não edite nenhum outro arquivo ou seção além dessa.
5. Termine sua resposta com uma última linha, sozinha, no formato exato:
   RESUMO: <uma frase curta em português dizendo o que você adicionou>

Transcrição bruta do áudio (gravado em {date_str}, horário local {time_str}):
---
{transcript}
---
"""


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
                "text",
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

    return True, result.stdout.strip()


def extract_resumo(claude_stdout: str) -> str:
    for line in reversed(claude_stdout.splitlines()):
        line = line.strip()
        if line.startswith("RESUMO:"):
            return line[len("RESUMO:"):].strip()
    return claude_stdout[-300:] if claude_stdout else "(sem saída do Claude)"


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

        prompt = CLAUDE_PROMPT_TEMPLATE.format(
            date_str=date_str, time_str=time_str, transcript=transcript
        )

        success, output = await loop.run_in_executor(None, run_claude_cli, prompt)

    if success:
        resumo = extract_resumo(output)
        await message.reply_text(f"✅ {resumo}")
    else:
        logger.error("Falha ao rodar Claude CLI: %s", output)
        await message.reply_text(
            "⚠️ A transcrição foi salva, mas houve um erro ao gerar a nota: "
            f"{output}\n\nTranscrição: {transcript_path}"
        )


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
