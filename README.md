# Telegram Audio Bot → Obsidian

Recebe áudios seus no Telegram, salva em `audio_logs/`, transcreve localmente
com faster-whisper e usa o Claude Code CLI para transformar a transcrição
numa entrada na nota diária do vault (`10 Daily/YYYY-MM-DD.md`).

Roda dentro do **WSL** (Ubuntu). O código fica no filesystem nativo do Linux
(`~/telegram_audio_bot`, mais rápido e sem os problemas do alias fantasma do
Python no Windows); o vault e a pasta de áudios continuam no disco Windows,
acessados via `/mnt/d/...`.

## 1. Pré-requisitos (já conferidos nesta máquina)

- `python3` 3.12 ✓
- `git` ✓
- `claude` (Claude Code CLI) — já instalado e autenticado neste WSL,
  independente da instalação do Windows. Confira com `claude --version`.
- Não precisa instalar ffmpeg — o faster-whisper decodifica o `.ogg` sozinho.

## 2. Instalar o projeto

```bash
cd ~/telegram_audio_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A primeira transcrição baixa o modelo `medium` do faster-whisper (alguns GB)
— só acontece uma vez, fica em cache em `~/.cache/huggingface`.

## 3. Configurar

```bash
cp .env.example .env
nano .env   # ou seu editor preferido
```

Preencha:

- `TELEGRAM_BOT_TOKEN`: o token do seu bot (@BotFather).
- `ALLOWED_TELEGRAM_USER_ID`: seu ID numérico do Telegram (mande uma
  mensagem para `@userinfobot` pra descobrir).
- Os demais campos já vêm com os valores certos pra essa máquina.

## 4. Testar manualmente

```bash
source .venv/bin/activate
python bot.py
```

Confira no terminal (e em `bot.log`) que o modelo Whisper carregou e o bot
entrou em polling. Do seu Telegram, mande um áudio de teste — o bot deve
responder com `✅ RESUMO: ...` depois de alguns segundos/minutos.

Confira também:
- `/mnt/d/Coisas/Outros/Variados/audio_logs/` — deve ter o `.ogg` e o `.txt`.
- `.../Obsidian Vault/10 Daily/<data>.md` — deve ter um bullet novo em
  `### 📓 Anotações`.

Se algo der errado, o bot avisa o erro no próprio Telegram e o `.txt` da
transcrição continua salvo (nada se perde). Mensagens de qualquer outra
conta do Telegram são ignoradas silenciosamente.

## 5. Deixar rodando sozinho

O WSL2 não usa o Agendador de Tarefas do Windows diretamente. Duas opções:

**A) Tarefa Agendada do Windows chamando `wsl.exe` (mais simples)**

1. Abra o Agendador de Tarefas → *Criar Tarefa Básica*.
2. Gatilho: **Ao fazer logon**.
3. Ação: **Iniciar um programa**.
   - Programa: `wsl.exe`
   - Argumentos: `-d Ubuntu -- bash -lc "cd ~/telegram_audio_bot && source .venv/bin/activate && python bot.py"`
4. Isso sobe a VM do WSL sozinho se ela não estiver rodando.

**B) systemd dentro do WSL (mais robusto, reinicia sozinho se cair)**

1. Confirme que o systemd está ativo: `cat /etc/wsl.conf` deve ter
   `[boot]\nsystemd=true` (se não tiver, adicione e rode
   `wsl.exe --shutdown` no PowerShell pra reiniciar a VM).
2. Crie `/etc/systemd/system/telegram-audio-bot.service`:

   ```ini
   [Unit]
   Description=Telegram Audio Bot
   After=network-online.target

   [Service]
   Type=simple
   User=caiod
   WorkingDirectory=/home/caiod/telegram_audio_bot
   ExecStart=/home/caiod/telegram_audio_bot/.venv/bin/python bot.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. `sudo systemctl daemon-reload && sudo systemctl enable --now telegram-audio-bot`
4. Configure também uma Tarefa Agendada "ao fazer logon" rodando
   `wsl.exe -d Ubuntu -- true` só pra garantir que a VM (e portanto o
   systemd) sobe junto com o Windows.

## Como funciona por baixo dos panos

1. `bot.py` fica em polling long-lived escutando só mensagens de voz/áudio
   da conta autorizada.
2. Ao receber um áudio, baixa para `audio_logs/{timestamp}_{id}.ogg` usando o
   horário do próprio áudio (não o horário de processamento).
3. Transcreve localmente com faster-whisper (`medium`, português) e salva um
   `.txt` ao lado do áudio.
4. Roda `claude -p "<prompt>" --permission-mode acceptEdits` com o diretório
   de trabalho no vault. O prompt instrui o Claude a criar/atualizar
   `10 Daily/<data-do-áudio>.md` com um bullet novo na seção "Anotações".
5. As permissões do Claude nesse projeto (`Obsidian Vault/.claude/settings.json`)
   restringem escrita a `10 Daily/**` e bloqueiam Bash/rede — o Claude só
   pode editar a nota diária, nada mais.
6. O bot responde no Telegram com um resumo curto do que foi adicionado.
