# Log by Voice: Telegram Audio Bot → Obsidian

Um bot do Telegram que transcreve áudios localmente, classifica-os automaticamente
com padrões rápidos + LLM inteligente, e escreve entradas estruturadas numa nota
diária do Obsidian. Tudo roda **offline e localmente** — seus dados nunca saem da máquina.

## Arquitetura

```
Você envia áudio via Telegram
           ↓
       Bot (polling)
           ↓
    [Transcrição] — Whisper (local, GPU)
           ↓
    [Classificação] — 2 fases:
        Phase 1: Pattern matching (regex, rápido ~0ms)
        Phase 2: LLM local (Ollama, fallback ~5-8s)
           ↓
    [Formatação] — Estrutura JSON → Markdown
           ↓
    Nota diária do Obsidian (em tempo real)
           ↓
    Bot responde no Telegram: "✅ RESUMO: ..."
```

## Stack técnico

- **Bot**: `python-telegram-bot` (async, polling)
- **Transcrição**: `faster-whisper` large-v3 (local, suporta GPU)
- **Classificação**: 
  - Phase 1: regexes estruturadas em `patterns.py` (70-80% dos casos)
  - Phase 2: LLM remoto (Ollama) com prompt estruturado (`prompt_classify.txt`)
- **LLM**: **Ollama** (`gemma4:e2b` em GPU RTX 2060, ~86 tok/s)
- **Armazenamento**: 
  - Transcrições: `AUDIO_LOGS_DIR` (Windows)
  - Vault: `OBSIDIAN_VAULT_DIR` (Windows, acessado via `/mnt/d`)
- **Plataforma**: WSL2 Ubuntu (Linux filesystem pra performance Python)

## O que o bot classifica

Tipos de itens reconhecidos:
- **`task`** — "Preciso arrumar o portão" → tarefa com prioridade/data opcional
- **`habit_log`** — "Corri 30 min" → log de hábito (`cardio`, `weight`, `piano`, `lifting`, `food`, `expense`)
- **`comment`** — texto livre sem classificação estruturada
- **`mark_done`** — "Concluído: aquela tarefa" → marca tarefa anterior como feita
- **`correction`** — "Corrige: anterior, coloca X" → edita item anterior
- **`complement`** — "Complementa: e também Y" → adiciona detalhe a item anterior
- **`recurring_task`** — "Mensalmente: pagar conta" → tarefa recorrente

Exemplos de reconhecimento:
```
Entrada: "Comprei pão e leite (R$25)"
→ expense: description="pão e leite", amount=25.0, category="Mercado"

Entrada: "Peso: 82.5"
→ habit_log: habit="weight", weight_kg=82.5

Entrada: "Muito cansado hoje"
→ comment: "Muito cansado hoje"  [LLM fallback — ambiguidade]

Entrada: "modo IA: é um texto que só a IA vai entender, ignora patterns"
→ [força chamada direto pro LLM, bypassa patterns]
```

## Pré-requisitos

Máquina:
- **WSL2** (Windows Subsystem for Linux 2) com Ubuntu
- **Python 3.12+** com `uv` (gerenciador de pacotes)
- **Ollama** (servidor LLM local) — suporta GPU via passthrough do WSL2

Contas externas:
- **Telegram Bot Token** — crie em `@BotFather`, copie o token
- **Seu ID do Telegram** — mande uma mensagem para `@userinfobot`
- **Obsidian Vault** — pasta com `10 Daily/` onde as notas ficam

## Instalação

### 1. Clonar / preparar o projeto

```bash
git clone https://github.com/caio-donalisio/log-by-voice.git
cd log-by-voice
uv sync  # cria .venv + instala dependências (py-telegram-bot, faster-whisper, ollama)
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
nano .env  # ou seu editor preferido
```

Preencha os campos essenciais:
- `TELEGRAM_BOT_TOKEN` — token do `@BotFather`
- `ALLOWED_TELEGRAM_USER_ID` — seu ID numérico do Telegram
- `AUDIO_LOGS_DIR` — pasta onde gravar `.ogg` + `.txt` (Windows path via `/mnt/`)
- `OBSIDIAN_VAULT_DIR` — raiz do Obsidian (onde estão as notes)
- `LOCAL_LLM_MODEL` — modelo Ollama (padrão: `gemma4:e2b`, ~7.2GB)
- `OLLAMA_HOST` — URL do Ollama (padrão: `http://localhost:11434`)

Opcionais (vêm com defaults sensatos):
- `WHISPER_MODEL_SIZE` — `large-v3` (recomendado) ou `medium` (mais rápido)
- `WHISPER_LANGUAGE` — `pt` (português)
- `LOCAL_TIMEZONE` — fuso horário local (PT Brasil: `America/Sao_Paulo`)
- `LOCAL_LLM_TIMEOUT_SECONDS` — timeout pra chamadas Ollama (120s)

### 3. Iniciar Ollama

```bash
# Já deve estar rodando como systemd, mas pode conferir:
sudo systemctl status ollama

# Ou iniciar manualmente:
ollama serve

# Puxar modelo (uma única vez):
ollama pull gemma4:e2b
# alternativas: qwen2.5:7b, llama3.2:3b (menor/mais rápido), mistral:7b
```

### 4. Testar

```bash
uv run bot.py
```

Você verá no log:
- Carregamento do Whisper (~1-5min primeira vez, depois está em cache)
- `Application started polling` — bot pronto pra receber áudios

Envie um áudio via Telegram na conta autorizada. O bot deve:
1. Baixar o áudio em `AUDIO_LOGS_DIR/{timestamp}_{id}.ogg`
2. Transcrever (alguns segundos com GPU, ou ~1min em CPU)
3. Classificar (pattern matching +/- LLM, ~5-8s)
4. Escrever na nota diária do Obsidian
5. Responder no Telegram: `✅ RESUMO: [items classificados]`

Se errar, o bot avisa no Telegram e a transcrição `.txt` fica salva (nada se perde).

**Dica**: rode `tail -f bot.log` em outro terminal pra ver os logs em tempo real.

## Deixar rodando 24/7

O bot roda em polling contínuo — precisa estar sempre ligado pra receber áudios.

### Opção A: Tarefa Agendada do Windows (simples)

1. Abra **Agendador de Tarefas** (`taskschd.msc`)
2. *Criar Tarefa Básica*:
   - Nome: `Log by Voice Bot`
   - Gatilho: *Ao fazer logon*
   - Ação: *Iniciar um programa*
     - Programa: `wsl.exe`
     - Argumentos: `-d Ubuntu-Personal -- bash -lc "cd ~/log-by-voice && uv run bot.py"`
3. OK. Próximo logon, o bot inicia automaticamente.

### Opção B: systemd no WSL (recomendado — reinicia se cair)

1. Confirme que systemd está ativo:
   ```bash
   cat /etc/wsl.conf | grep systemd
   # deve conter: [boot]\nsystemd=true
   ```
   Se não tiver, rode `wsl.exe --shutdown` (PowerShell) e reinicie.

2. Crie `/etc/systemd/system/log-by-voice.service`:
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

3. Ativar:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now log-by-voice.service
   sudo systemctl status log-by-voice.service  # verificar
   ```

4. Visualizar logs:
   ```bash
   sudo journalctl -u log-by-voice -f  # streaming
   tail -f bot.log  # ou o arquivo local
   ```

## Fluxo técnico detalhado

### 1. Recepção do áudio (`bot.py`)

```
Você: [áudio no Telegram]
        ↓
bot.py polling (long-lived getUpdates)
        ↓
Verifica: sender ID == ALLOWED_TELEGRAM_USER_ID?
        ↓ sim
Baixa .ogg com timestamp do áudio (não do recebimento)
        ↓
Salva em AUDIO_LOGS_DIR/{YYYYMMDD}_{HHMMSS}_{msg_id}.ogg
```

### 2. Transcrição (`bot.py` + `faster-whisper`)

```
.ogg → faster-whisper (local, GPU-accelerated)
        ↓
Modelo: large-v3 (português)
        ↓
Transcrição .txt salvo ao lado do áudio
        ↓
Exemplo output: "Corri 30 minutos hoje e peso 82 quilos"
```

**Performance**:
- GPU (RTX 2060): 30-60s para áudio de 1-2 min
- CPU: 2-5 min
- Modelo baixado em cache (~1.6GB em `~/.cache/huggingface`)

### 3. Classificação (`classifier.py` + `patterns.py` + Ollama)

#### Phase 1: Pattern Matching (rápido, ~0ms)

Regexes estruturadas cobrem ~70-80% dos casos, sem tocar no LLM:

```python
# exemplos de padrões em patterns.py:
weight_pattern = r"(?:peso|weight)[:,\s]*(\d+(?:[.,]\d+)?)\s*kg"
  → "Peso: 82.5" → habit_log(weight=82.5)

task_pattern = r"(?:preciso|tenho que|need to)\s+(.+?)(?:\.|$)"
  → "Preciso arrumar o portão" → task(description="arrumar o portão")

cardio_pattern = r"(?:corri|correr|running)\s+(\d+)\s*min"
  → "Corri 30 min" → habit_log(cardio, activity="corri", minutes=30)

# expense patterns reconhecem R$ junto com número:
expense_pattern = r"R\$?\s*(\d+(?:[.,]\d+)?)\s*(?:em|para|de)?\s+(.+)"
  → "Comprei pão e leite R$25" → expense(amount=25, desc="pão e leite")
```

**Resultado Phase 1**: lista de `Item` + texto não-classificado (`unmatched`)

#### Phase 2: LLM Fallback (inteligente, ~5-8s)

Se `unmatched` não vazio, envia ao Ollama:

```
unmatched text → prompt_classify.txt → Ollama (gemma4:e2b)
                                          ↓
                                    JSON estruturado
                                    [{"type":"comment", "data":{...}},...]
                                          ↓
                                    Parser JSON (com fallback se malformado)
```

**Prompt structure** (`prompt_classify.txt`):
- Define schema (tipos, campos, regras)
- Passa texto não-classificado
- Inclui já-classificados como contexto (pra evitar duplicação)
- Regras rígidas: nunca inventar números, usar "comment" na dúvida

**Exemplo LLM**:
```
Input (unmatched): "Muito cansado hoje"
Ollama response: [{"type":"comment", "data":{"text":"Muito cansado hoje"}}]
```

**Performance Ollama**:
- Primeira chamada (cold start): ~22s (carrega modelo em VRAM)
- Chamadas subsequentes: ~5-8s (modelo já em memória)
- Throughput: ~86 tokens/segundo (GPU RTX 2060)

### 4. Calorie estimation (opcional, para `habit_log/food`)

Se classificação = food SEM calorias explícitas:

```
description="pão e leite" → prompt ao Ollama
                               ↓
                         "estima ~250 kcal"
                               ↓
Item completo: {calories: 250, estimated: true}
```

### 5. Formatação e escrita (`formatter.py`, `daily_note.py`, `edits.py`)

Cada `Item` → Markdown:

```python
# Exemplo: task(description="arrumar portão", priority="alta")
# → "- [ ] **ALTA** Arrumar portão"

# Exemplo: habit_log(cardio, minutes=30)
# → "**🏃 Cardio**: 30 min (correr)"

# Exemplo: mark_done(task_hint="portão")
# → busca tarefa anterior matching "portão" → marca como ✅

# Exemplo: expense(amount=25, category="Mercado")
# → "💰 Mercado: R$25"
```

**Determinístico**: Python puro, sem LLM — cada tipo tem template fixo.

Escreve em:
```
OBSIDIAN_VAULT_DIR/10 Daily/YYYY-MM-DD.md
  (cria se não existe)
  
Seções:
  ### 📓 Anotações         [comments]
  ### ✅ Tarefas           [tasks]
  ### 🏃 Hábitos           [habit_logs]
  ...
```

### 6. Resposta ao Telegram

Bot responde com resumo:

```
✅ RESUMO: 1 tarefa + 1 cardio + 1 comment
```

Se erro em qualquer fase:
```
❌ Erro: [descrição técnica]
```

Transcrição `.txt` SEMPRE fica salva mesmo se classificação falhar.

## Arquivos principais

| Arquivo | Função |
|---------|--------|
| `bot.py` | Entrada principal: polling, download, coordenação |
| `classifier.py` | Orquestração classification (patterns + LLM) |
| `patterns.py` | ~500 linhas de regexes + heurísticas |
| `formatter.py` | Item → Markdown determinístico |
| `daily_note.py` | Leitura/escrita do arquivo diário Obsidian |
| `edits.py` | Operações de edição (mark_done, correction, etc.) |
| `calorie_estimator.py` | Prompt mínimo pra estimar kcal |
| `prompt_classify.txt` | Prompt do LLM (schema + regras) |

## Configuração de performance

### GPU Whisper

Se você tiver GPU NVIDIA:
```bash
# Checar disponibilidade
nvidia-smi

# Installer CUDA via WSL2 passthrough (automático em W11+)
# faster-whisper detecta sozinho e usa GPU
```

Whisper GPU: 30-60s por áudio (2-5min em CPU).

### GPU Ollama

WSL2 suporta GPU passthrough para NVIDIA:
```bash
# Verificar detecção
ollama list  # mostra PROCESSOR: CPU/GPU
```

Se `100% CPU` no Ollama: verifique NVIDIA driver WSL (pode estar desatualizado).

### Modelo Ollama customizado

Trocar modelo em `.env`:
```bash
# Rápido (CPU + GPU):
LOCAL_LLM_MODEL=llama3.2:3b    # 2GB, ~100 tok/s (CPU)

# Equilibrado:
LOCAL_LLM_MODEL=qwen2.5:7b     # 4.4GB, recomendado português

# Poderoso:
LOCAL_LLM_MODEL=gemma4:e2b     # 7.2GB, atual (recomendado GPU)
LOCAL_LLM_MODEL=mistral:7b     # 4GB, bom em patterns
```

Puxar novo: `ollama pull qwen2.5:7b`

## Troubleshooting

### Bot não responde

1. Confira token: `echo $TELEGRAM_BOT_TOKEN` (não deve estar vazio)
2. Confira ID autorizado: envie `/start` no Telegram, veja qual ID aparece no log
3. Confira Ollama: `curl http://localhost:11434/api/version` (deve retornar JSON)
4. Logs: `tail -f bot.log` + `journalctl -u ollama -f`

### Transcrição lenta

1. Whisper em CPU? `nvidia-smi` pra verificar GPU
2. Modelo muito grande? Tente `WHISPER_MODEL_SIZE=medium`

### Classificação lenta (>15s)

1. Ollama em CPU? `ollama ps` deve mostrar `100% GPU`
2. Modelo pequeno demais? Tente `llama3.2:3b` pra testar rápido
3. LLM não responde? Confira `sudo journalctl -u ollama`

### Nota Obsidian não atualiza

1. Caminho vault correto? `ls -la "$OBSIDIAN_VAULT_DIR/10 Daily/"`
2. Arquivo `.md` criado? `ls -la "$OBSIDIAN_VAULT_DIR/10 Daily/$(date +%Y-%m-%d).md"`
3. Erro de formatação? Confira `bot.log` pra stderr da escrita

## Testes

```bash
# Rodar suite de testes (35 testes, ~10s)
uv run pytest -v

# Teste específico
uv run pytest tests/ -k classify -v

# Coverage
uv run pytest --cov=.
```
