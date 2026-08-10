# Tasks — Separate Classification from Content Generation

**Feature:** separate-classification-from-generation
**Date:** 2026-08-10
**Total tasks:** 20

## Dependency Graph

```
Phase 1: Foundation
  T1 ──┬── T3 (engine)
  T2 ──┘
        │
Phase 2: Patterns (all parallel after T3)
        ├── T4 (weight)
        ├── T5 (lifting)
        ├── T6 (piano+cardio)
        ├── T7 (expense+food)
        └── T8 (task+correction)
              │
Phase 3: Formatters (T9 → rest parallel)
        T9 ──┬── T10 (task+comment)
             ├── T11 (habit_log: weight,cardio,food,expense)
             ├── T12 (habit_log: piano,lifting + wiki-links)
             ├── T13 (mark_done,correction,complement)
             ├── T14 (recurring_task)
             └── T15 (resumo)
                   │
Phase 4: LLM Fallback (depends on Phase 3 schema)
        T16 ── T17
               │
Phase 5: Integration (depends on all above)
        T18 ── T19 ── T20
```

---

## Phase 1 — Foundation

### T1 — JSON Item Schema + Validation

**Depends on:** nothing
**Files:** `formatter/__init__.py`, `formatter/schema.py`

- [ ] Define `Item` dataclass with all 7 types as a `Literal` union
- [ ] Define typed data classes per item type (`TaskData`, `WeightData`, `LiftingData`, etc.)
- [ ] `validate_item(item: dict) -> Item`: validates type, required fields, numeric ranges
- [ ] `validate_item()` returns `InvalidItem` (treated as `comment`) on validation failure — never raises
- [ ] Unit tests: valid items pass, invalid items fallback to comment, expense with estimated=true rejected

**Verification:** `pytest` on schema validation with 10+ sample dicts

### T2 — Pattern Dataclass + Registry

**Depends on:** T1
**Files:** `patterns/__init__.py`, `patterns/engine.py` (skeleton)

- [ ] `Pattern` dataclass: name, category, habit, triggers (list[str]), regex (str), confidence (float), build_item (callable)
- [ ] `PatternRegistry`: register/load all patterns, iterate for matching
- [ ] `trigger_normalize(text: str) -> str`: lowercase, strip accents, collapse whitespace — shared by all patterns
- [ ] `number_parse(s: str) -> float`: "82.5" → 82.5, "82,5" → 82.5, "cem" → 100

**Verification:** instantiate all 8 patterns, verify no import errors, test normalization edge cases

---

## Phase 2 — Pattern Matching Engine

### T3 — Segmentation + Engine Core

**Depends on:** T1, T2
**Files:** `patterns/engine.py`

- [ ] `segment_transcript(text: str) -> list[str]`: split into sentences on `. ! ?` and newlines
- [ ] `clean_segment(text: str) -> str`: remove filler words ("é", "tipo assim", "então", "né", "assim", "sabe")
- [ ] `match_segment(text: str, patterns: list[Pattern]) -> tuple[Item | None, float, str]`:
  - Runs all patterns against segment
  - Returns (item, confidence, matched_pattern_name) or (None, 0, "")
  - Multiple matches: highest score wins if gap ≥ 0.2; otherwise None (ambiguous → LLM)
- [ ] `classify(transcript: str) -> tuple[list[Item], str]`:
  - Segments → matches each segment → collects items + unmatched text
  - Returns (items, unmatched_concat)
- [ ] Anti-trigger check: `não precisofazer`, `não tenho que` before task pattern negates match

**Verification:** unit tests with single-segment inputs. "me pesei 82 quilos" → 1 item. "não preciso comprar nada" → 0 items (anti-trigger). "fiz supino e depois corri" → ambiguous → unmatched

### T4 — Weight Pattern (P1)

**Depends on:** T3
**Files:** `patterns/weight.py`

- [ ] Triggers covering: `pesei|me pesei|me pesar|peso deu|peso tá|peso marcou|tô pesando|estou pesando|balança deu|balança marcou`
- [ ] Regex: capture `weight` as number, optional unit suffix
- [ ] `build_item`: `habit_log` with `habit="weight"`, `weight_kg` as float
- [ ] Confidence: 0.95
- [ ] Edge cases: "82.5" (decimal comma), "82.5 quilos", "82 e meio" → unmatched (LLM), "peso" sozinho sem número → unmatched

**Verification:** test 6+ variations, confirm correct extraction, confirm edge cases go unmatched

### T5 — Lifting Pattern (P2)

**Depends on:** T3
**Files:** `patterns/lifting.py`

- [ ] Triggers: exercise names from vault (`100 Fitness/Exercícios/**/*.md`) loaded at init + generic (`séries de`, `repetiç`, `supino`, `agachamento`, etc.)
- [ ] Regex: capture `sets`, `reps`, `weight_kg`, `exercise` (all optional except exercise)
- [ ] `build_item`: `habit_log` with `habit="lifting"`, all captured fields
- [ ] Confidence: 0.90 when exercise found, 0.70 when only generic trigger (→ unmatched by threshold)
- [ ] Number formats: "3x10" → sets=3, reps=10. "15kg" → weight_kg=15. "3 séries de 10 de 15 quilos"

**Verification:** test "fiz 3 séries de 10 de 15 quilos de supino reto", "3x10 supino reto 15kg", "fiz supino" (low conf → unmatched)

### T6 — Piano + Cardio Patterns (P3, P4)

**Depends on:** T3
**Files:** `patterns/piano.py`, `patterns/cardio.py`

**Piano:**
- [ ] Triggers: `pratiquei|estudei|toquei|piano|teclado|praticar|estudar|tocar`
- [ ] Regex: capture `minutes` (optional) and `piece_hint`
- [ ] Confidence: 0.85 (wiki-link resolution happens later in T12)
- [ ] Edge case: "toquei piano" sem peça → unmatched

**Cardio:**
- [ ] Triggers: `bicicleta|esteira|corri|corrida|caminhada|bike|eliptico|cardio`
- [ ] Regex: capture `minutes` (optional) and `activity`
- [ ] Confidence: 0.90

**Verification:** "pratiquei 45 min de Chopin Estudo Op 10" → piano item. "fiz 30 min de bicicleta" → cardio item

### T7 — Expense + Food Patterns (P5, P6)

**Depends on:** T3
**Files:** `patterns/expense.py`, `patterns/food.py`

**Expense:**
- [ ] Triggers: `paguei|comprei|gastei|pagar|comprar|gastar` + value indicator (`reais|R\$|\$|por`)
- [ ] Regex: capture `description` and `amount`
- [ ] Confidence: 0.90 with amount, 0.60 without → unmatched if no amount
- [ ] Category extraction: if text contains one of the 9 valid categories by name → include; otherwise leave null
- [ ] Edge case: "paguei Sensei" sem valor → unmatched

**Food:**
- [ ] Triggers: `comi|almocei|jantei|lanchei|tomei café|café da manhã|almoço|jantar|lanche`
- [ ] Regex: capture `description` (rest of text), optional `calories` number
- [ ] Confidence: 0.80 (always needs calorie estimation if no number)
- [ ] Meal inference: if "almocei" → meal="almoço", "jantei" → "jantar", etc.

**Verification:** "comprei uma saia vermelha por 80 reais" → expense. "almocei arroz feijão e frango" → food (no calories → estimated in LLM fallback)

### T8 — Task + Correction Patterns (P7, P8)

**Depends on:** T3
**Files:** `patterns/task.py`, `patterns/correction.py`

**Task:**
- [ ] Triggers: `registra tarefa|cria tarefa|anota tarefa|lembrete|tenho que|preciso|não esquecer|lembrar de`
- [ ] Anti-triggers: `não preciso|não tenho que` → negates match
- [ ] Regex: capture `description`, optional `due_date` (dates like "domingo", "dia 20", "amanhã")
- [ ] Confidence: 0.85
- [ ] Date parsing: "domingo" → next Sunday, "dia 20" → YYYY-MM-20, "amanhã" → tomorrow

**Correction:**
- [ ] Triggers: `corrige|corrija|corrigir|na verdade|errei|tá errado`
- [ ] Regex: capture `search_hint` and `new_value` (both greedy, best-effort)
- [ ] Confidence: 0.80 (this is the most fragile — expected ~50% LLM fallback)
- [ ] Edge case: if new_value is empty → unmatched

**Verification:** "registra tarefa de ir no meu pai domingo" → task. "corrige meu peso de hoje na verdade foi 81" → correction

---

## Phase 3 — Formatter Module

### T9 — Daily Note Creation + Section Management

**Depends on:** nothing (reads vault template)
**Files:** `formatter/daily_note.py`

- [ ] `read_template() -> str`: reads `_templates/generic_daily_note.md`
- [ ] `create_daily_note(date_str, time_str) -> Path`: creates `10 Daily/{date}.md` from template, substitutes dates
- [ ] `ensure_daily_note(date_str, time_str) -> tuple[Path, bool]`: returns (path, created) — creates if missing, no-op if exists
- [ ] `append_to_section(file_path, section_heading, lines)`: finds section, appends lines at end of section
- [ ] `read_file_lines(path) -> list[str]`, `write_file_lines(path, lines)`: safe read/write
- [ ] Dates in Portuguese: `2026-08-10` → "domingo, 10 de agosto de 2026"

**Verification:** test with real template from vault. Fresh date → creates file. Existing date → appends. Section not found → creates section at end of file

### T10 — Task + Comment Formatters

**Depends on:** T9
**Files:** `formatter/task.py`, `formatter/comment.py`

**Task:**
- [ ] `format_task(data: TaskData) -> str`: `- [ ] <description>`
- [ ] Priority markers: `data.priority == "urgente"` → `🔺`, `"alta"` → `⏫`, `"média"` → `🔼`
- [ ] Due date: `📅 YYYY-MM-DD` if present
- [ ] Sub-bullets: time → `    - Às HH:MM`, comment → `    - <comment>`, can combine both
- [ ] `write_task(note_path, item)`: appends to `### ✅ Tarefas Registradas`

**Comment:**
- [ ] `format_comment(data: CommentData) -> str`: clean bullet, no invented info
- [ ] `write_comment(note_path, item)`: appends to `### 📓 Anotações`

**Verification:** compare output with existing vault format. Task with all fields → identical to current Claude output

### T11 — Habit Log Formatters (weight, cardio, food, expense)

**Depends on:** T9
**Files:** `formatter/habit_log.py` (single file with per-habit functions)

- [ ] `format_weight(data) -> str`: `- Me pesei [weight:: <N>] #log/fitness #fitness/weight`
- [ ] `format_cardio(data) -> str`: `- [x] Fazer <Atividade> [minutes:: <N>] #habit #fitness #fitness/cardio #log/fitness 📅 YYYY-MM-DD ✅ YYYY-MM-DD`
- [ ] `format_food(data) -> str`: `- Comi <descrição> [calories:: <N>] #log/fitness #fitness/calories` with optional `[meal:: <café da manhã|almoço|lanche|jantar>]` and `(estimativa)` suffix
- [ ] `format_expense(data) -> str`: `- Paguei <descrição> [amount:: <N>] [category:: <cat>] #log/finance #finance/expense`
- [ ] All write to `### 📓 Anotações` via `append_to_section`

**Verification:** each habit produces identical format to current Claude output. Expense without category omits `[category::]`. Food with estimated=true appends "(estimativa)"

### T12 — Habit Log Formatters (piano, lifting) + Wiki-Link Resolution

**Depends on:** T9, T11
**Files:** `formatter/habit_log.py` (add), `formatter/wiki_resolver.py`

**Wiki resolver:**
- [ ] `find_note_name(hint: str, search_dirs: list[str]) -> tuple[str, float]`: glob → normalize → fuzzy match → returns (best_name, score)
- [ ] Cache note names per directory (loaded once, refreshed if mtime changes)
- [ ] Fallback: if no match → return hint as-is with score 0

**Piano formatter:**
- [ ] Resolves `piece_hint` via `find_note_name` in `70 Piano/**/*.md`
- [ ] `- <Pratiquei|Estudei> [[<Nome Exato>]] [minutes:: <N>] #log/piano #piano/<repertoire|exercise|theory>`
- [ ] action: "practice" → "Pratiquei", "study" → "Estudei"

**Lifting formatter:**
- [ ] Resolves `exercise_hint` via `find_note_name` in `100 Fitness/Exercícios/**/*.md`
- [ ] `- [[<Nome Exato>]] [weight:: <kg>] [reps:: <N>] [sets:: <N>] #log/fitness #fitness/lifting`
- [ ] Optional fields omitted when null

**Verification:** "Chopin Estudo Op 10" → matches real vault note. New unknown piece → uses hint as link name, warns

### T13 — Edit Operations (mark_done, correction, complement)

**Depends on:** T9
**Files:** `formatter/mark_done.py`, `formatter/correction.py`, `formatter/complement.py`

**Shared search (used by all 3):**
- [ ] `search_lines(pattern: str, scope: str) -> list[tuple[Path, int, str, float]]`: implements R12 search algorithm
- [ ] `find_best_match(hint: str, scope: str) -> tuple[Path, int, str, float] | None`: returns best match or None

**Mark done:**
- [ ] `mark_done(file_path, line_num, date_str, comment=None)`: replace `[ ]` with `[x]`, append `✅ {date}` at EOL
- [ ] `add_sub_bullet(file_path, line_num, text)`: insert `    - <text>` after line
- [ ] If `is_recurring`: `create_next_occurrence(file_path, line_num, date_str)` — reads `🔁` rule, creates next line
- [ ] Fallback: `format_comment_fallback("Disse ter concluído '<hint>' mas não encontrei a tarefa original")`

**Correction:**
- [ ] `correct_line(file_path, line_num, new_field, new_value)`: regex replace `[new_field:: old]` → `[new_field:: new]`
- [ ] Only touches the matched field, preserves rest of line

**Complement:**
- [ ] `complement_line(file_path, line_num, detail)`: add `    - <detail>` below matched line

**Verification:** mock vault files, test each operation. Mark recurring → verify next occurrence. Correction → verify only target field changed

### T14 — Recurring Task Creator

**Depends on:** T9
**Files:** `formatter/recurring.py`

- [ ] `format_recurring(data: RecurringData) -> str`: creates a block in `Tarefas Recorrentes.md`
- [ ] Format: `---\n- [ ] <description> [#payment] [priority] 🔁 every <period>[ when done] ➕ {date} [⏳ {date}] 📅 {date}`
- [ ] `check_duplicate(description: str) -> bool`: searches `Tarefas Recorrentes.md` for similar description → returns True if exists
- [ ] If duplicate found → returns None, caller logs warning, item becomes comment

**Verification:** new recurring task → proper block. Duplicate detection → "Pagar gás" matches existing "Pagar Gás" (case/accent normalization)

### T15 — RESUMO Generator

**Depends on:** T10-T14
**Files:** `formatter/resumo.py`

- [ ] `generate_resumo(items: list[Item], warnings: list[str]) -> str`: deterministic summary
- [ ] Templates per item count and type:
  - 1 item: "Adicionei <descrição> em <seção> da nota de <data>"
  - N items: "<N> itens adicionados em <data>: <lista curta>"
  - Mixed (add + edit): "<N> itens adicionados, <M> tarefas atualizadas em <data>"
- [ ] Warnings appended: "⚠️ Não encontrei a tarefa '<hint>' para marcar como concluída"
- [ ] Format: `RESUMO: <frase>` (last line, matching current bot expectation)

**Verification:** compare RESUMO output with real examples from bot.log

---

## Phase 4 — LLM Fallback

### T16 — Compact Classification Prompt

**Depends on:** T1 (schema definition)
**Files:** `prompt_classify.txt` (new, ~30 lines)

- [ ] Describes the 7 item types with 1-line definitions
- [ ] Shows the JSON schema inline (compact)
- [ ] Rules: prefer comment when uncertain, never estimate expense, estimate calories when food, never read files, never write
- [ ] Format: `{already_classified}` and `{unmatched_text}` placeholders (Python .format())
- [ ] Output instruction: "Return ONLY the JSON array. No markdown, no explanation, no RESUMO."

**Verification:** prompt is under 50 lines. All 7 types described. Placeholders correct

### T17 — LLM Fallback Integration

**Depends on:** T16, T1
**Files:** `bot.py` (modify `run_claude_cli` usage), new `classifier.py`

- [ ] `classify_with_llm(unmatched_text: str, already_classified: list[Item]) -> list[Item]`:
  - Formats prompt with already_classified summary + unmatched text
  - Calls `run_claude_cli` (existing function, same lock, same timeout)
  - Parses JSON response
  - Validates each item via T1 schema
  - Invalid items → convert to `comment`
  - On Claude failure → all unmatched becomes `comment`
- [ ] `classifier.py`: orchestrates `patterns.classify()` → if unmatched → `classify_with_llm()`

**Verification:** unit test with mock Claude output. Test with invalid JSON → all comment fallback. Test with timeout → fallback

---

## Phase 5 — Integration

### T18 — Merge Pipeline in bot.py

**Depends on:** T17, T9-T15
**Files:** `bot.py`

- [ ] Replace Step 4 (run_claude_cli) and Step 5 (extract_resumo) in `handle_audio`:
  ```
  1. transcript → unchanged (Whisper)
  2. items, unmatched = classifier.classify(transcript)
  3. daily_note_path, created = ensure_daily_note(date, time)
  4. for item in items:
       dispatch to formatter → write to vault
  5. resumo = generate_resumo(items, warnings)
  6. reply: ✅ {resumo}
  ```
- [ ] `claude_lock` scope: only around `classify_with_llm()` call, not pattern matching (patterns are instant, no lock needed)
- [ ] Keep existing: dedup, audio save, transcript save, error reply format
- [ ] Remove: `extract_resumo()` (replaced by T15), `PROMPT_TEMPLATE_PATH` (replaced by T16 + patterns)

**Verification:** end-to-end with real `.ogg` files from `audio_logs/`. Compare vault output (diff) with historical runs

### T19 — Observability + Logging

**Depends on:** T18
**Files:** `bot.py`, `patterns/engine.py`

- [ ] Log pattern match stats: `INFO Classifier: 4 items por pattern (weight=1, lifting=1, expense=1, task=1), 1 segmento pro LLM (42 chars)`
- [ ] Log LLM skip: `INFO LLM skipped: todos os 5 segmentos resolvidos por pattern`
- [ ] Log LLM call: `INFO LLM fallback: 1 segmento classificado (custo=$0.01, 2.1s)`
- [ ] Log per-item: `DEBUG item=_source=pattern:weight_log confidence=0.95 type=habit_log`
- [ ] Log warnings: `WARNING mark_done: tarefa 'Pagar IPTU' não encontrada → comment fallback`
- [ ] Track stats in memory: pattern_match_rate, llm_call_count — reported on bot shutdown

**Verification:** run bot, send test audio, verify log output format

### T20 — Integration Test with Real Transcripts

**Depends on:** T19
**Files:** `tests/test_integration.py`

- [ ] Collect 10+ real transcripts from `audio_logs/*.txt` (already have the ground truth of what Claude wrote)
- [ ] Run each through the new pipeline (pattern engine + LLM fallback)
- [ ] Compare output:
  - Item count and types match expected
  - Vault lines match expected format (inline fields, tags, wiki-links)
  - No missing or extra sections touched
- [ ] Measure: pattern match rate, LLM call rate, total latency
- [ ] Known edge cases: "comi um baião de 2" (food), "corrija comprar fralda" (correction → likely LLM), "Paguei Sensei" (expense without amount → LLM)
- [ ] Regression: none of the 10 transcripts produce worse output than today

**Verification:** all tests pass. Pattern match rate ≥ 60% (target is 70%, but 60% is minimum viable)

---

## Execution Order

```
Wave 1 (parallel): T1, T9
Wave 2 (parallel, after T1): T2, T16
Wave 3 (after T2): T3
Wave 4 (parallel, after T3): T4, T5, T6, T7, T8
Wave 5 (parallel, after T9): T10, T11, T12, T13, T14, T15
Wave 6 (after T16): T17
Wave 7 (after all above): T18
Wave 8 (after T18): T19
Wave 9 (after T19): T20
```

**Total:** 20 tasks, 9 waves. Waves 4 and 5 are the heavy parallel ones (5-6 tasks each).

---

## Commit Strategy

```
commit 1: T1+T2 — schema + pattern infrastructure
commit 2: T3 — engine core (testable with mock patterns)
commit 3: T4+T5+T6+T7+T8 — pattern catalog (8 patterns, testable)
commit 4: T9 — daily note management
commit 5: T10+T11+T12+T13+T14+T15 — all formatters
commit 6: T16+T17 — LLM fallback
commit 7: T18+T19 — integration + logging
commit 8: T20 — integration tests + polish
```

Each commit is independently testable and doesn't break the bot (behavior change only after commit 7).
