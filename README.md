# Telegram Audio Bot → Obsidian

Recebe áudios seus no Telegram, salva em `audio_logs/`, transcreve localmente
com faster-whisper e usa um LLM local (Ollama) para classificar a transcrição
e gerar entradas na nota diária do vault (`10 Daily/YYYY-MM-DD.md`).

Roda dentro do **WSL** (Ubuntu). O código fica no filesystem nativo do Linux
(`~/telegram_audio_bot`, mais rápido e sem os problemas do alias fantasma do
Python no Windows); o vault e a pasta de áudios continuam no disco Windows,
acessados via `/mnt/d/...`.

## 1. Pré-requisitos (já conferidos nesta máquina)

- `python3` 3.12 ✓
- `git` ✓
- `uv` (gerenciador de pacotes/venv) ✓ — instalado em `~/.local/bin/uv`.
- `ollama` — servidor de LLM local. Instale com:
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```
  Depois puxe um modelo pequeno (recomendado: `llama3.1:8b` ou `qwen2.5:7b`):
  ```bash
  ollama pull llama3.1:8b
  ```
- Não precisa instalar ffmpeg — o faster-whisper decodifica o `.ogg` sozinho.

## 2. Instalar o projeto

```bash
cd ~/telegram_audio_bot
uv sync
```

Isso cria o `.venv` sozinho e instala tudo que está no `pyproject.toml`
(travado em `uv.lock`, já commitado, pra reprodutibilidade). Não precisa
ativar o venv manualmente — o passo 4 usa `uv run`, que já resolve isso.

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
- `LOCAL_LLM_MODEL`: modelo Ollama a usar. O default é `llama3.1:8b`.
  Alternativas boas: `qwen2.5:7b` (melhor em português), `mistral:7b`.
  Modelos menores (3b) são mais rápidos mas menos precisos na classificação.
- `OLLAMA_HOST`: endereço do servidor Ollama (default: `http://localhost:11434`).
- Os demais campos já vêm com os valores certos pra essa máquina.

## 4. Testar manualmente

```bash
uv run bot.py
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
   - Argumentos: `-d Ubuntu -- bash -lc "cd ~/telegram_audio_bot && uv run bot.py"`
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
   ExecStart=/home/caiod/.local/bin/uv run bot.py
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
4. Classifica a transcrição em duas fases:
   - **Pattern matching** (regex): cobre ~70% dos casos (tarefas, hábitos,
     correções, etc.) sem tocar no LLM.
   - **LLM local** (fallback): segmentos que os patterns não cobrem são enviados
     ao Ollama (`LOCAL_LLM_MODEL`) com um prompt de classificação curto
     (`prompt_classify.txt`). O modelo retorna JSON estruturado.
5. Cada item classificado é formatado e escrito no vault pelo Python
   (`formatter.py`, `daily_note.py`, `edits.py`) — a formatação é
   determinística, não depende do LLM. O LLM só classifica; o Python escreve.
6. Se o item for de comida sem calorias explícitas, uma segunda chamada ao LLM
   (`calorie_estimator.py`) estima as calorias com um prompt mínimo.
7. O bot responde no Telegram com um resumo curto do que foi adicionado.
