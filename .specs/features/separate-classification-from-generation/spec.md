# Separate Classification from Content Generation

**Status:** draft
**Scope:** Large
**Date:** 2026-08-10

## Problem

Today the bot delegates **everything** to Claude CLI: classification, formatting, vault
reading, and writing. The prompt is 210 lines of mostly deterministic rules. This means:

- High cost (~$0.05–0.35/audio, largely from vault reads + huge prompt)
- High latency (30–120s waiting for Claude to read files + write)
- Fragile output (Claude can forget a field, invent a date, misformat a wiki-link)
- Hard to evolve (editing a 210-line prompt vs editing a Python function)

## Goal

**Pattern matching first. LLM only as fallback.**

Majority of voice notes follow predictable patterns ("me pesei X quilos", "fiz Y séries de Z",
"comprei X por Y reais"). Python regex + keyword matching catches these. Only ambiguous or
unrecognized segments go to Claude. Both paths produce the same structured JSON. Python
formats + writes everything.

```
Áudio → Whisper → Transcrição
                     │
                     ├── Pattern Matcher (regex + keywords)
                     │   ├── High confidence → structured items
                     │   └── Low confidence / unmatched segments
                     │       └── Claude CLI (classifica, JSON)
                     │              └── structured items
                     │
                     └── Python: merge items → format → write vault → RESUMO
```

## Requirements

### R1 — Pipeline Overview

```
1. Transcribe (Whisper, unchanged)
2. Segment transcript into sentences
3. For each sentence, try pattern matching:
   a. Run ALL patterns, collect matches with confidence scores
   b. Non-overlapping best matches → structured items (high confidence)
   c. Remaining text → concatenate into "unmatched" bucket
4. If unmatched bucket is non-empty → send to Claude (R4), get structured items
5. Merge pattern items + LLM items → single ordered list
6. Python: format each item → write to vault → generate RESUMO
```

**LLM is skipped entirely if all sentences are matched with high confidence.**

### R2 — Pattern Definition Format

Each pattern lives in a Python dataclass or a declarative dict (YAML/JSON
eventualmente, mas Python por enquanto). Um padrão tem:

```python
@dataclass
class Pattern:
    name: str           # e.g. "weight_log", "lifting_log"
    category: str       # e.g. "habit_log"
    habit: str | None   # e.g. "weight", "lifting", "expense" — só pra habit_log
    triggers: list[str] # palavras/expressões que ativam este padrão
    regex: str          # regex com named groups pra extrair dados
    confidence: float   # 0.0 a 1.0 — vai subindo conforme refinamos
    build_item: Callable[[re.Match, str], dict]  # match → item dict
```

**Exemplo concreto — peso:**

```python
Pattern(
    name="weight_log",
    category="habit_log",
    habit="weight",
    triggers=[
        # Grupo 1: "me pesei" e variações
        r"\b(?:me\s+)?pesei\b", r"\b(?:me\s+)?pesar\b",
        # Grupo 2: "o peso deu/tá/marcou"
        r"\bo\s+peso\s+(?:deu|t[áa]|est[áa]|marcou|estava)\b",
        # Grupo 3: "tô/estou pesando"
        r"\b(?:t[ôo]|estou)\s+pesando\b",
        # Grupo 4: "balança marcou/deu"
        r"\bbalan[çc]a\s+(?:marcou|deu|mostrou)\b",
        # Grupo 5: formato direto: "<número> quilos" (mais frágil, confiança menor)
        r"\b(\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos|quilo)\b",
    ],
    regex=r"(?P<weight>\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos|quilo)?",
    confidence=0.95,
    build_item=lambda m, text: {
        "type": "habit_log",
        "habit": "weight",
        "data": {"weight_kg": float(m.group("weight").replace(",", "."))}
    }
)
```

**Por que triggers + regex separados?** Triggers identificam que ESTE padrão se
aplica a esta frase (classificação). O regex extrai os dados (extração). Separar
permite ter múltiplos triggers pra mesma regex, e triggers mais flexíveis
(palavras soltas, não precisam de grupos de captura).

### R3 — Pattern Matching Engine

Algoritmo por frase:

```
1. Limpa a frase: remove cacoetes de fala ("é", "tipo assim", "então", "né",
   "assim", "sabe"), pontuação excessiva, normaliza whitespace
2. Pra cada padrão registrado:
   a. Testa cada trigger contra a frase (case-insensitive, accent-insensitive)
   b. Se trigger match → tenta o regex de extração contra a frase
   c. Se regex match E todos os named groups obrigatórios capturaram → match!
   d. Score = pattern.confidence * (1.0 se regex capturou tudo, 0.7 se parcial)
3. Se EXATAMENTE 1 padrão deu match com score ≥ threshold:
   → item estruturado, frase consumida
4. Se MÚLTIPLOS padrões deram match:
   → maior score vence. Se gap < 0.2 → ambíguo → manda pro LLM
5. Se NENHUM padrão deu match:
   → frase vai pro bucket "unmatched"
```

**Threshold de confiança:** ≥ 0.80 usa o item direto. Abaixo disso → LLM.

**Tratamento de variações nos triggers:** cada trigger é uma regex simples.
Variações de conjugação (pesei/pesou/pesamos/pese) são cobertas por múltiplos
triggers OU por um trigger mais flexível (`\bpese[ioy]\b`). A ideia não é
esgotar todas as variações possíveis de uma vez — é começar com as observadas e
ir adicionando conforme aparecem.

### R4 — LLM Fallback

Só é chamado se o bucket "unmatched" não estiver vazio.

Prompt enxuto (~30 linhas):
- Recebe APENAS o texto não-classificado (não a transcrição inteira)
- Mesmo schema JSON da spec original
- Instruído a NÃO ler arquivos, NÃO escrever, só classificar
- Pode receber como contexto os itens já classificados por pattern (pra evitar
  duplicar — ex: se o pattern já pegou o peso, o LLM não precisa reclassificar
  essa parte)

**Fallback do fallback:** se Claude falhar (timeout, JSON inválido, erro),
todo o unmatched vira `comment` — a transcrição não se perde.

### R5 — Pattern Catalog (versão inicial)

Cada padrão listado com seus triggers e a regex de extração. A lista completa
vai crescer com o uso; começamos com os de maior volume.

#### P1 — Peso corporal
- **Triggers:** `pesei`, `me pesei`, `me pesar`, `peso deu`, `peso tá`, `peso marcou`, `tô pesando`, `balança deu`, `balança marcou`
- **Regex:** `(?P<weight>\d+(?:[.,]\d+)?)\s*(quilos|kg|kilos|quilo)?`
- **Confiança:** 0.95
- **Variações cobertas:** "me pesei 82 quilos", "o peso deu 82", "tô pesando 82", "a balança marcou 82.5", "pesei 82"
- **Variações NÃO cobertas (vai pro LLM):** "deu 82 na balança hoje", "82 foi o que marcou", "hoje eu vi que tô com 82"

#### P2 — Musculação
- **Triggers:** `séries? de`, `repetiç`, `supino`, `agachamento`, `levantamento`, `rosca`, `tríceps`, `bíceps`, `puxada`, `remada`, `desenvolvimento`, `leg press`, `stiff`
- **Regex:** `(?:(?P<sets>\d+)\s*(?:séries?|sets?|x)\s*(?:de\s*)?)?(?:(?P<reps>\d+)\s*(?:repetiç|reps?|repeticoes))?\s*(?:de\s*)?(?:(?P<weight_kg>\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos))?\s*(?:de\s*)?(?P<exercise>[A-Za-zÀ-ÿ\s]+?)(?:\s*\.|$)` (simplificada — a real vai ser refinada)
- **Confiança:** 0.90
- **Variações:** "3 séries de 10 de 15 quilos de supino reto", "fiz supino", "3x10 supino", "15kg supino reto 3x10"

#### P3 — Piano
- **Triggers:** `pratiquei`, `praticar`, `estudei`, `estudar`, `toquei`, `tocar`, `piano`, `teclado`
- **Regex:** `(?:(?P<minutes>\d+)\s*(?:min|minutos?))?\s*(?:de\s*)?(?P<piece_hint>.+?)(?:\s*\.|$)`
- **Confiança:** 0.85 (precisa de verificação de nome de peça no vault)
- **Nota:** o `piece_hint` vai pro R11 (wiki-link resolution) depois

#### P4 — Cardio
- **Triggers:** `cardio`, `bicicleta`, `esteira`, `corri`, `corrida`, `caminhada`, `bike`, `eliptico`, `elíptico`
- **Regex:** `(?:(?P<minutes>\d+)\s*(?:min|minutos?))?\s*(?:de\s*)?(?P<activity>bicicleta|esteira|corrida|caminhada|bike|eliptico|elíptico|cardio)`
- **Confiança:** 0.90

#### P5 — Gasto (com valor)
- **Triggers:** `paguei`, `comprei`, `gastei`, `pagar`, `comprar`, `gastar` + `reais`, `R\$`, `\$`
- **Regex:** `(?P<description>.+?)\s+(?:por|—|–|-)\s*(?:R\$?\s*)?(?P<amount>\d+(?:[.,]\d+)?)\s*(?:reais|real|conto|pila)?`
- **Confiança:** 0.90 (amount presente) / 0.60 (amount ausente → LLM decide se é expense ou comment)
- **Regra:** se amount não for capturado → NÃO classifica como expense → LLM decide

#### P6 — Comida
- **Triggers:** `comi`, `almocei`, `jantei`, `lanchei`, `tomei café`, `café da manhã`, `almoço`, `jantar`, `lanche`
- **Regex:** `(?P<description>.+)$` (o resto da frase é a descrição)
- **Confiança:** 0.80 (sempre precisa de estimativa de calorias, que pode ir pro LLM se for complexo)
- **Nota:** se a descrição for muito curta ("comi pão") e não tiver número explícito de calorias, o LLM estima. Se tiver número ("comi 500 calorias"), pattern extrai direto.

#### P7 — Tarefa explícita
- **Triggers:** `registra tarefa`, `cria tarefa`, `anota tarefa`, `lembrete`, `não esquecer`, `tenho que`, `preciso`, `lembrar de`
- **Regex:** `(?:(?:registra|cria|anota)\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|tenho que|preciso|não esquecer de|lembrete:?\s*)(?P<description>.+)$`
- **Confiança:** 0.85
- **Variações:** "registra tarefa de ir no meu pai domingo", "tenho que comprar conduíte", "preciso ligar pro médico"

#### P8 — Correção explícita
- **Triggers:** `corrige`, `corrija`, `corrigir`, `na verdade`, `errei`, `tá errado`
- **Regex:** `(?:(?:corrige|corrija|corrigir)\s*(?:o|a|meu|minha)?\s*)?(?P<search_hint>.+?)(?:pra|para|—|–|-|\.|$)\s*(?P<new_value>.+)?`
- **Confiança:** 0.80 (match parcial) / 0.90 (new_value capturado)
- **Nota:** esse é o padrão mais frágil. Correções são muito variáveis. Espera-se que ~50% vá pro LLM.

### R6 — Merge Strategy

Itens dos dois caminhos (pattern + LLM) são combinados:

```
1. Pattern items: preservados na ordem original das frases
2. LLM items: inseridos nas posições onde o texto unmatched aparecia
3. LLM é instruído a NÃO reclassificar o que já foi classificado
4. Se houver conflito (LLM classifica algo que o pattern já pegou):
   vence o pattern (mais confiável, determinístico)
```

### R7 — LLM Fallback Prompt

~30 linhas, bem mais enxuto que o atual:

```
You are classifying segments of a voice transcript that a rule-based system
could not match. Return ONLY valid JSON — no markdown, no explanation.

The transcript segments (in order) are below. Some may already be classified
by the rule-based system (listed as "already classified"). Do NOT reclassify
those — only classify the unmatched ones.

Already classified items (for context only):
{already_classified}

Unmatched segments to classify:
{unmatched_text}

For each unmatched segment, classify as one of:
- task: new to-do item
- habit_log with habit=[weight|piano|lifting|cardio|food|expense]: activity log
- comment: free thought, no action needed
- mark_done: completing an existing task
- correction: fixing a previous entry
- complement: adding detail to an existing entry
- recurring_task: creating a periodic task

Output JSON schema:
{... same as R8 ...}
```

### R8 — Unified JSON Item Schema

Mesmo schema que ambos os caminhos (pattern e LLM) produzem:

```json
{
  "type": "task|habit_log|comment|mark_done|correction|complement|recurring_task",
  "habit": "weight|piano|lifting|cardio|food|expense",  // só em habit_log
  "data": { /* campos específicos do tipo */ },
  "_source": "pattern:weight_log|llm",   // metadata pra debugging
  "_confidence": 0.95                     // metadata pra logging
}
```

**Validation rules (enforced by Python):**
- `type` must be one of the 7 valid types
- `habit_log.habit` must be one of: weight, piano, lifting, cardio, food, expense
- `expense.amount` must be a number (never estimated)
- `food.calories` may be null or estimated; if estimated, `estimated` must be true
- `mark_done.is_recurring` triggers the next-occurrence creation logic in Python
- Dates in `YYYY-MM-DD` format or null, never invented

### R9 — Python Formatter Module

New module `formatter/` with one function per item type:

```
formatter/
├── __init__.py
├── daily_note.py     # create_or_get_daily_note(), reads template, creates if missing
├── task.py           # format_task() → "- [ ] descrição 📅 data"
├── habit_log.py      # format_weight(), format_piano(), format_lifting(), format_cardio(), format_food(), format_expense()
├── comment.py        # format_comment() → bullet simples
├── mark_done.py      # find_and_mark_done() → searches vault, marks [x], handles 🔁
├── correction.py     # find_and_correct() → searches vault, edits line in-place
├── complement.py     # find_and_complement() → searches vault, adds sub-bullet
├── recurring.py      # format_recurring_task() → cria bloco em Tarefas Recorrentes.md
└── resumo.py         # generate_resumo() → "RESUMO: ..." deterministico
```

Each function:
- Receives the typed `data` dict from JSON
- Returns the markdown line(s) to insert
- For search-based types (mark_done, correction, complement): reads vault files,
  does string matching, returns result + any warnings

### R10 — Pattern Matcher Module

New module `patterns/`:

```
patterns/
├── __init__.py       # Pattern dataclass, registry, match_transcript()
├── weight.py         # P1
├── lifting.py        # P2
├── piano.py          # P3
├── cardio.py         # P4
├── expense.py        # P5
├── food.py           # P6
├── task.py           # P7
├── correction.py     # P8
└── engine.py         # Segmentation, matching loop, confidence scoring
```

`engine.match_transcript(transcript: str) -> tuple[list[Item], str]`:
- Recebe a transcrição bruta
- Segmenta em frases
- Roda todos os padrões
- Retorna (itens classificados, texto unmatched)

### R11 — Target Section Resolution

Cada tipo de item mapeia deterministicamente para um arquivo e seção.
**Zero AI nessa decisão — é um dicionário hardcoded em Python.**

| Item Type | Target File | Target Section | Mode |
|-----------|-------------|----------------|------|
| `task` | `10 Daily/{date}.md` | `### ✅ Tarefas Registradas` | Append no fim da seção |
| `habit_log` (6 subtipos) | `10 Daily/{date}.md` | `### 📓 Anotações` | Append no fim da seção |
| `comment` | `10 Daily/{date}.md` | `### 📓 Anotações` | Append no fim da seção |
| `mark_done` | Determinado pela busca | Onde a tarefa original está | Edição in-place |
| `correction` | Determinado pela busca | Onde a linha original está | Edição in-place |
| `complement` | Determinado pela busca | Abaixo da linha original | Sub-bullet in-place |
| `recurring_task` | `10 Daily/Tarefas Recorrentes.md` | Fim do arquivo (novo bloco `---`) | Append |

### R12 — Edit Operations and Error Recovery

Os 3 tipos de edição (`mark_done`, `correction`, `complement`) compartilham o mesmo
pipeline de busca → match → edição.

#### Algoritmo de busca

```
1. Normaliza query: lowercase, strip accents, remove emoji/priority markers,
   collapse whitespace, remove pontuação
2. Normaliza cada linha candidata no vault: mesma transformação
3. Extrai o "core" da linha candidata: remove [field:: value] inline fields,
   tags #log/..., marcadores 📅/✅/🔁/⏳/➕ — sobra só o texto descritivo
4. Pontua cada candidata:
   - core contém query exata    → score 100
   - core contém query substring → score 80
   - tokens da query batem >50%  → score 60
   - tokens batem >30%           → score 40
   - abaixo disso                 → ignorada
5. Ordena por score decrescente
6. Se top score ≥ 80 E segundo < 80 → match claro
7. Se top score ≥ 60 E gap pro segundo ≥ 20 → match claro
8. Caso contrário → ambíguo
```

**Ordem de busca nos arquivos:**
1. `10 Daily/{date_str}.md` (nota de hoje)
2. `10 Daily/Tarefas Recorrentes.md`
3. `10 Daily/*.md` (últimos 30 dias, mais recente primeiro)
4. `10 Daily/*.md` (mais antigos)

**Restrição de escopo:** Edições só em `10 Daily/**`.

#### Comportamento por tipo

| Operação | Match claro | Sem match / Ambíguo / Fora do escopo |
|----------|-------------|---------------------------------------|
| `mark_done` | Marca `[x]` + `✅ data`. Se `is_recurring`: cria próxima ocorrência | Fallback → `comment`: "Disse ter concluído '<hint>' mas não encontrei a tarefa original" |
| `correction` | Edita linha in-place, substitui campo | Fallback → `comment`: "Pediu para corrigir '<hint>' mas não encontrei a anotação original" |
| `complement` | Adiciona `    - <detail>` abaixo da linha | Fallback → `comment`: "Pediu para complementar '<hint>' mas não encontrei a tarefa original" |

### R13 — Wiki-Link Resolution

Para `habit_log` de piano e musculação, o Python resolve `piece_hint` /
`exercise_hint` em um nome exato de nota do vault:

```
1. Glob os diretórios: 70 Piano/**/*.md, 100 Fitness/Exercícios/**/*.md
2. Extrai nomes de nota (stem do arquivo .md)
3. Normaliza hint e nomes (lowercase, strip accents)
4. Melhor match: substring > token overlap
5. Se match ≥ threshold → usa o nome exato da nota → [[Nome Exato]]
6. Se sem match → usa o hint original como [[hint original]]
7. Score < 100 → avisa no RESUMO: "⚠️ Não encontrei nota existente para '<hint>'"
```

### R14 — Daily Note Creation

Python cria `10 Daily/{date_str}.md` se não existir, usando
`_templates/generic_daily_note.md` como template. Substitutes:
- `date_created` field with `{date_str}T{time_str}`
- Date aliases in Portuguese
- Day-of-week heading
- `tasks` query date ranges relative to `{date_str}`

### R15 — Backward Compatibility

- External behavior identical: receives audio, replies `✅ RESUMO: ...`
- `prompt_template.txt` replaced by pattern definitions + compact LLM fallback prompt
- Audio/transcript file handling (dedup, naming, Whisper) unchanged
- `.env` configuration unchanged
- Claude CLI still available but called less often (only on unmatched segments)

### R16 — Error Handling

- Pattern matching never crashes — exceptions caught, segment goes to unmatched
- LLM returns invalid JSON → all unmatched segments become `comment`
- LLM timeout → segments become `comment`, log warning
- Unknown `type` in any item → treat as `comment`
- Vault search fails → fallback to `comment`, mention in RESUMO
- Daily note template missing → log error, reply with warning
- `claude_lock` (serialization) behavior unchanged

### R17 — Observability

Todo item carrega metadados de origem:
- `_source: "pattern:weight_log"` ou `_source: "llm"`
- `_confidence: 0.95`

Logging:
- `INFO Classifier: 3 items por pattern, 1 segmento pro LLM (42 chars)`
- `INFO Pattern match: weight_log (confidence=0.95, source="me pesei 82 quilos")`
- `INFO LLM fallback: 1 segmento classificado (custo=$0.01, 2s)`
- `INFO LLM skipped: todos os 4 segmentos resolvidos por pattern`

Isso permite acompanhar a proporção pattern vs LLM ao longo do tempo e
identificar quais padrões precisam de mais triggers.

## Out of Scope

- Replacing Claude entirely (local LLM via Ollama) — architectural foundation, not this feature
- Changing the Telegram interface (commands, multi-user, etc.)
- Changing the vault structure or conventions
- Real-time streaming feedback during processing
- Machine learning on pattern matching (keep it explicit, auditable regex)

## Success Metrics

- [ ] ≥70% dos segmentos de transcrição classificados por pattern (sem LLM)
- [ ] ≥80% de redução no custo Claude (chamado em ~30% dos áudios, prompt menor)
- [ ] ≥50% de redução na latência (patterns são instantâneos)
- [ ] All 7 current categories (A-G) produce identical formatted output in the vault
- [ ] RESUMO lines are deterministic per item type
- [ ] Fallback to comment never silently drops information
