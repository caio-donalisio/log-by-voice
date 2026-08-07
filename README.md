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
- `uv` (gerenciador de pacotes/venv) ✓ — instalado em `~/.local/bin/uv`.
- `claude` (Claude Code CLI) — já instalado e autenticado neste WSL,
  independente da instalação do Windows. Confira com `claude --version`.
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
- `CLAUDE_CLI_PATH` / `CLAUDE_CONFIG_DIR`: se você usa um alias tipo
  `claude-caio` no seu shell pra rodar o Claude Code com um perfil/config
  específico (`alias claude-caio='CLAUDE_CONFIG_DIR="$HOME/.claude-caio" claude'`),
  **não** coloque o nome do alias em `CLAUDE_CLI_PATH` — o bot chama o
  processo direto, sem passar por um shell, então aliases não existem pra
  ele. Deixe `CLAUDE_CLI_PATH=claude` e defina `CLAUDE_CONFIG_DIR` com o
  mesmo caminho que o alias usa; o bot reproduz o efeito passando essa
  variável de ambiente pro subprocesso.
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
4. Roda `claude -p "<prompt>" --permission-mode acceptEdits` com o diretório
   de trabalho no vault. O prompt vem de `prompt_template.txt`, lido do disco
   a cada áudio (não fica fixo na memória do processo) — editar esse arquivo
   muda o comportamento do bot a partir do próximo áudio, sem precisar
   reiniciar. O prompt instrui o Claude a criar/atualizar
   `10 Daily/<data-do-áudio>.md` (e, quando for concluir uma tarefa
   recorrente, também `10 Daily/Tarefas Recorrentes.md`), classificando cada
   item da fala em: tarefa nova (checkbox em "Tarefas Registradas", com
   data/prioridade só se foram ditas), log de hábito (peso, piano, musculação,
   cardio, calorias, gastos — formatado com os campos e tags que os gráficos
   do vault esperam, ex: `[weight:: 82] #log/fitness #fitness/weight`; pra
   calorias, se a pessoa só descreveu a comida sem dar um número, o Claude
   estima e marca como "(estimativa)" em vez de inventar que foi um número
   dito — já pra gastos é o oposto, nunca estima valor em dinheiro, só
   registra se um número foi dito), comentário livre (bullet simples, texto
   limpo, sem ligação com nenhuma tarefa) ou conclusão de uma tarefa pendente
   já existente (procura a tarefa em `10 Daily/**`, marca `[x]` e adiciona
   `✅ <data>` sem alterar o resto da linha). Comentários ditos sobre uma
   tarefa (nova ou concluída) entram como sub-bullet indentado abaixo dela,
   em vez de virar uma anotação solta. Antes de escrever um log, o Claude lê
   `10 Daily/_README.md` e a pasta do domínio (`70 Piano/**`,
   `100 Fitness/**`) pra pegar o nome exato de peça/exercício — sem isso o
   link não alimenta o histórico daquela nota. Se não conseguir achar com
   segurança a tarefa que a pessoa diz ter concluído (ou se ela vive fora de
   `10 Daily/**`, como em `30 Projetos/`), o Claude não arrisca
   marcar a errada — só registra um comentário contando o que foi dito e
   avisa no resumo.
5. As permissões do Claude nesse projeto (`Obsidian Vault/.claude/settings.json`)
   permitem leitura do vault inteiro (pra pegar nomes exatos e formato, e pra
   localizar tarefas existentes), mas restringem escrita a `10 Daily/**` e
   bloqueiam Bash/rede — o Claude só pode editar dentro dessa pasta, nada
   fora dela. Na prática isso cobre a nota diária e `Tarefas Recorrentes.md`,
   mas não tarefas em `30 Projetos/` ou `20 Pessoal/`.
6. O bot responde no Telegram com um resumo curto do que foi adicionado.
