"""Pattern definitions + matching engine — all in one file.

Pattern-first classification: regex/keyword matching as primary path,
LLM as fallback for unmatched segments.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from formatter import HabitType, ItemType
from text_utils import clean_segment, normalize

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern dataclass + registry
# ---------------------------------------------------------------------------

@dataclass
class Pattern:
    name: str
    category: ItemType
    habit: HabitType | None
    triggers: list[str]
    regex: str
    confidence: float
    build_item: Callable[[re.Match, str], dict[str, Any]]
    required_fields: list[str] = field(default_factory=list)
    adjust_confidence: Callable[[dict[str, Any], float], float] | None = None
    _trigger_res: list[re.Pattern] = field(default_factory=list, repr=False)
    _extraction_re: re.Pattern | None = field(default=None, repr=False)


class PatternRegistry:
    def __init__(self) -> None:
        self._patterns: list[Pattern] = []

    def register(self, pattern: Pattern) -> None:
        pattern._trigger_res = [re.compile(t, re.I | re.U) for t in pattern.triggers]
        pattern._extraction_re = re.compile(pattern.regex, re.I | re.U)
        self._patterns.append(pattern)

    def register_all(self, patterns: list[Pattern]) -> None:
        for p in patterns:
            self.register(p)

    @property
    def patterns(self) -> list[Pattern]:
        return list(self._patterns)


# ---------------------------------------------------------------------------
# Engine — segmentation, matching, scoring
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE = 0.80
AMBIGUITY_GAP = 0.10
_SEGMENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_ANTI_TRIGGERS = [
    re.compile(r"\bnão\s+(?:preciso|tenho\s+que|precisa|vou|quero)\b", re.I),
]


def segment_transcript(text: str) -> list[str]:
    raw = _SEGMENT_RE.split(text)
    segs = [s.strip() for s in raw if s.strip()]
    return segs if segs else [text.strip()]


def match_segment(
    segment: str, registry: PatternRegistry,
) -> tuple[dict | None, float, str]:
    cleaned = clean_segment(segment)
    cleaned_re = re.sub(r"[.!?]+$", "", cleaned).strip()

    if any(at.search(cleaned) for at in _ANTI_TRIGGERS):
        return None, 0.0, ""

    candidates: list[tuple[dict, float, str]] = []

    for p in registry.patterns:
        if not any(t.search(cleaned) for t in p._trigger_res):
            continue
        m = p._extraction_re.search(cleaned_re) if p._extraction_re else None
        if m is None:
            m = p._extraction_re.search(cleaned) if p._extraction_re else None
        if m is None:
            continue
        try:
            item_dict = p.build_item(m, cleaned)
        except Exception:
            continue
        if item_dict is None:
            continue
        # Required fields
        item_data = item_dict.get("data", {})
        if p.required_fields:
            if any(item_data.get(f) is None for f in p.required_fields):
                continue
        conf = p.confidence
        if p._extraction_re and p._extraction_re.groupindex:
            all_g = set(p._extraction_re.groupindex)
            captured = {g for g in all_g if m.group(g) is not None}
            if len(captured) < len(all_g):
                conf *= 0.80
        if p.adjust_confidence:
            conf = p.adjust_confidence(item_dict, conf)
        candidates.append((item_dict, conf, p.name))

    if not candidates:
        return None, 0.0, ""

    candidates.sort(key=lambda c: c[1], reverse=True)
    best_dict, best_conf, best_name = candidates[0]
    if best_conf < HIGH_CONFIDENCE:
        return None, 0.0, ""
    if len(candidates) >= 2 and (best_conf - candidates[1][1]) < AMBIGUITY_GAP:
        return None, 0.0, ""

    best_dict["_source"] = f"pattern:{best_name}"
    best_dict["_confidence"] = best_conf
    return best_dict, best_conf, best_name


def classify(transcript: str, registry: PatternRegistry) -> tuple[list[dict], str]:
    segments = segment_transcript(transcript)
    items, unmatched = [], []
    for seg in segments:
        d, conf, name = match_segment(seg, registry)
        if d is not None:
            items.append(d)
            logger.info("Pattern match: %s (%.2f, \"%s\")", name, conf, seg[:60])
        else:
            unmatched.append(seg)
    return items, " ".join(unmatched).strip()


# ===================================================================
# Pattern definitions
# ===================================================================

# -- P1: Weight --

def _build_weight(m, text):
    return {"type": "habit_log", "habit": "weight",
            "data": {"weight_kg": float(m.group("weight").replace(",", "."))}}

weight = Pattern("weight_log", "habit_log", "weight", [
    r"\b(?:me\s+)?pesei\b", r"\b(?:me\s+)?pesar\b", r"\b(?:me\s+)?pesou\b",
    r"\b(?:o\s+)?(?:meu\s+)?peso\s+(?:deu|t[áa]|est[áa]|marcou|estava)\b",
    r"\b(?:t[ôo]|estou|to)\s+pesando\b", r"\bbalan[çc]a\s+(?:marcou|deu|mostrou)\b",
], r"(?P<weight>\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos|quilo)?", 0.95,
    _build_weight, ["weight_kg"])


# -- P2: Lifting --

def _build_lifting(m, text):
    data: dict[str, Any] = {}
    for field, pat in [("sets", r"(?P<n>\d+)\s*(?:s[ée]ries?|series?|x)"),
                        ("reps", r"(?P<n>\d+)\s*(?:repeti[çc][õo]es|reps?|repeti[çc]|rep)")]:
        mm = re.search(pat, text);
        if mm: data[field] = int(mm.group("n"))
    mm = re.search(r"(?P<w>\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos|quilo)", text)
    if mm: data["weight_kg"] = float(mm.group("w").replace(",", "."))
    ex = text
    for w in ["fiz","fazer","fizemos","treinei","malhei","treinar","malhar","hoje","eu",
              "três","tres","duas","dois","uma","um","quatro","cinco","seis","sete","oito","nove","dez"]:
        ex = re.sub(rf"\b{w}\b", "", ex, flags=re.I)
    ex = re.sub(r"\d+\s*(?:s[ée]ries?|series?|x|repeti[çc][õo]es|reps?|quilos|kg|kilos|quilo)", "", ex)
    ex = re.sub(r"\d+(?:[.,]\d+)?", "", ex); ex = re.sub(r"\s+de\s+", " ", ex)
    ex = re.sub(r"^[,\s]+", "", ex); ex = re.sub(r"[,\s]+$", "", ex); ex = ex.strip().rstrip(".")
    if ex: data["exercise_hint"] = ex
    return {"type": "habit_log", "habit": "lifting", "data": data}

_EXERCISES = [r"\bsupino\b", r"\bagachamento\b", r"\brosca\b", r"\btr[íi]ceps\b",
              r"\bb[íi]ceps\b", r"\bleg\s?press\b", r"\bremada\b", r"\bdesenvolvimento\b",
              r"\bstiff\b", r"\bpuxada\b", r"\beleva[çc][ãa]o\b", r"\babdominal\b",
              r"\bprancha\b", r"\bafundo\b", r"\bpassada\b", r"\bburpee\b", r"\bflex[ãa]o\b"]

lifting = Pattern("lifting_log", "habit_log", "lifting", [
    r"\bs[ée]ries?\s+de\b", r"\brepeti[çc][õo]es?\b",
    r"\b[2-9]\d*\s*[xX]\s*[2-9]\d*\b", *_EXERCISES,
], r".*", 0.90, _build_lifting, ["exercise_hint"])


# -- P3/P4: Piano + Cardio --

def _build_piano(m, text):
    data: dict = {}
    mm = re.search(r"(?P<m>\d+)\s*(?:min|minutos?|minuto)", text)
    if mm: data["minutes"] = int(mm.group("m"))
    if re.search(r"\bpratiquei|praticar|toquei|tocar\b", text): data["action"] = "practice"
    elif re.search(r"\bestudei|estudar\b", text): data["action"] = "study"
    hint = re.sub(r"\b(?:pratiquei|praticar|toquei|tocar|estudei|estudar|piano|teclado)\b", "", text, flags=re.I)
    hint = re.sub(r"\d+\s*(?:min|minutos?|minuto)", "", hint); hint = re.sub(r"\d+", "", hint)
    hint = re.sub(r"\s+de\s+", " ", hint); hint = hint.strip().rstrip(".")
    if hint: data["piece_hint"] = hint
    return {"type": "habit_log", "habit": "piano", "data": data}

piano = Pattern("piano_log", "habit_log", "piano", [
    r"\bpratiquei\b", r"\bpraticar\b", r"\bpraticou\b", r"\bestudei\b", r"\bestudar\b",
    r"\bestudou\b", r"\btoquei\b", r"\btocar\b", r"\btocou\b", r"\bpiano\b", r"\bteclado\b",
], r".*", 0.85, _build_piano, ["piece_hint"])

_CARDIO = [r"\bbicicleta\b", r"\besteira\b", r"\bcorri\b", r"\bcorrida\b", r"\bcaminhada\b",
           r"\bbike\b", r"\bel[ií]ptico\b", r"\beliptico\b", r"\bcardio\b", r"\bnata[çc][ãa]o\b", r"\bcorrer\b"]

def _build_cardio(m, text):
    data: dict = {}
    mm = re.search(r"(?P<m>\d+)\s*(?:min|minutos?|minuto)", text)
    if mm: data["minutes"] = int(mm.group("m"))
    for a in _CARDIO:
        if re.search(a, text): data["activity"] = re.search(a, text).group(0).lower(); break
    if "activity" not in data: data["activity"] = "cardio"
    return {"type": "habit_log", "habit": "cardio", "data": data}

cardio = Pattern("cardio_log", "habit_log", "cardio", _CARDIO, r".*", 0.90, _build_cardio)


# -- P5/P6: Expense + Food --

def _build_expense(m, text):
    data: dict = {}
    rc = re.search(r"(?P<r>\d+)\s*reais?\s*e\s*(?P<c>\d+)\s*centavos?", text)
    if rc: data["amount"] = float(rc.group("r")) + float(rc.group("c")) / 100
    else:
        mm = re.search(r"(?:R\$\s*)?(?P<a>\d+(?:[.,]\d+)?)\s*(?:reais|real|conto|pila|pilas|R\$)?", text)
        if mm: data["amount"] = float(mm.group("a").replace(",", "."))
    desc = re.sub(r"\b(?:paguei|comprei|gastei|pagar|comprar|gastar|gastou|comprei|pagou|comprou)\b", "", text, flags=re.I)
    desc = re.sub(r"\b(?:hoje|eu|um|uma|uns|umas)\b", "", desc, flags=re.I)
    desc = re.sub(r"\d+\s*reais?\s*e\s*\d+\s*centavos?", "", desc)
    desc = re.sub(r"\d+(?:[.,]\d+)?\s*(?:reais|real|conto|pila|pilas|centavos)", "", desc)
    desc = re.sub(r"\s+(?:por|—|–|-)\s*", " ", desc); desc = re.sub(r"\s+", " ", desc).strip().rstrip(".")
    if not desc: desc = text.strip().rstrip(".")
    data["description"] = desc
    for cat in ["Mercado","Restaurantes","Moradia","Saúde","Transporte","Educação","Lazer","Pets","Negócio","Outros"]:
        if re.search(rf"\b{cat}\b", text, re.I): data["category"] = cat; break
    return {"type": "habit_log", "habit": "expense", "data": data}

def _adj_expense(item, base):
    return base * 0.60 if item.get("data", {}).get("amount") is None else base

expense = Pattern("expense_log", "habit_log", "expense", [
    r"\bpaguei\b", r"\bcomprei\b", r"\bgastei\b", r"\bpagar\b", r"\bcomprar\b",
    r"\bgastar\b", r"\b(?:pagou|comprou|gastou)\b",
], r".*", 0.85, _build_expense, adjust_confidence=_adj_expense)

_MEAL_MAP = {"café da manhã":"café da manhã","café":"café da manhã","cafe da manha":"café da manhã",
             "cafe":"café da manhã","almocei":"almoço","almoço":"almoço","almoco":"almoço",
             "almoçar":"almoço","almocar":"almoço","lanchei":"lanche","lanche":"lanche",
             "jantei":"jantar","jantar":"jantar","jante":"jantar"}

def _build_food(m, text):
    data: dict = {}
    mm = re.search(r"(?P<c>\d+)\s*(?:calorias|cal|kcal)", text)
    if mm: data["calories"] = int(mm.group("c")); data["estimated"] = False
    else: data["estimated"] = True
    desc = re.sub(r"\b(?:comi|almocei|jantei|lanchei|comer|almocar|almoçar|jantar|lanchar|tomei|tomar|comemos|comeram)\b", "", text, flags=re.I)
    desc = re.sub(r"\b(?:hoje|eu|um|uma|uns|umas)\b", "", desc, flags=re.I)
    desc = re.sub(r"\d+\s*(?:calorias|cal|kcal)", "", desc)
    desc = re.sub(r"\s+", " ", desc).strip().rstrip(".")
    if not desc: desc = text.strip().rstrip(".")
    data["description"] = desc
    for kw, meal in _MEAL_MAP.items():
        if kw in text.lower(): data["meal"] = meal; break
    return {"type": "habit_log", "habit": "food", "data": data}

food = Pattern("food_log", "habit_log", "food", [
    r"\bcomi\b", r"\balmocei\b", r"\bjantei\b", r"\blanchei\b", r"\btomei\b", r"\btomar\b",
    r"\bcomer\b", r"\balmo[cç]ar\b", r"\bjantar\b", r"\blanchar\b", r"\bcafé\s+da\s+manh[ãa]\b",
    r"\balmo[cç]o\b", r"\bjantar\b", r"\bcaneca\s+de\b",
], r".*", 0.80, _build_food, ["description"])


# -- P7/P8: Task + Correction --

def _build_task(m, text):
    data: dict = {}
    desc = re.sub(
        r"\b(?:registr[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|cri[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|anot[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|adicion[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|marqu[ei]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|marcar\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|inser[ai]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|inserir\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|tenho\s+que|preciso\s*(?:de)?|n[ãa]o\s+esquecer\s*(?:de)?|lembrete\s*:?\s*)",
        "", text, flags=re.I)
    desc = desc.strip().rstrip(".")
    data["description"] = desc
    data["_explicit"] = bool(re.search(
        r"\b(?:tarefa|registr[ae]|cri[ae]\s+tarefa|anot[ae]\s+tarefa|adicion[ae]\s+tarefa|marqu[ei]\s+tarefa|marcar\s+tarefa|inser[ai]\s+tarefa|inserir\s+tarefa)\b",
        text, re.I))
    if re.search(r"\burgente\b", text, re.I): data["priority"] = "urgente"
    elif re.search(r"\balta\b\s+prioridade|\bprioridade\s+alta\b", text, re.I): data["priority"] = "alta"
    mm = re.search(r"(?:[àa]s?)\s*(?P<h>\d{1,2})\s*[h:]\s*(?P<m>\d{2})?", text)
    if mm: data["time"] = f"{int(mm.group('h')):02d}:{int(mm.group('m')):02d}" if mm.group('m') else f"{int(mm.group('h')):02d}:00"
    from date_utils import parse_relative_date
    pd = parse_relative_date(text)
    if pd: data["due_date"] = pd
    return {"type": "task", "data": data}

def _adj_task(item, base):
    if item.get("data", {}).get("_explicit"): return 0.95
    d = item.get("data", {})
    if d.get("due_date") or d.get("due_day") or d.get("time") or d.get("priority"): return 0.90
    return base

task = Pattern("task", "task", None, [
    r"\bregistr[ae]\b", r"\bcri[ae]\s+(?:uma\s+)?tarefa\b", r"\banot[ae]\s+(?:uma\s+)?tarefa\b",
    r"\badicion[ae]\s+(?:uma\s+)?tarefa\b", r"\bmarqu[ei]\s+(?:uma\s+)?tarefa\b",
    r"\bmarcar\s+(?:uma\s+)?tarefa\b", r"\binser[ai]\s+(?:uma\s+)?tarefa\b",
    r"\binserir\s+(?:uma\s+)?tarefa\b", r"\btenho\s+que\b", r"\bpreciso\b",
    r"\bn[ãa]o\s+esquecer\b", r"\blembrete\s*:", r"\blembrar\s+de\b",
    r"\b(?:organizar|resolver|marcar|agendar|enviar|mandar|estudar|limpar|arrumar|consertar|entregar|ligar|providenciar|agilizar|confirmar|verificar|checar|conferir)\b",
], r".*", 0.80, _build_task, ["description"], adjust_confidence=_adj_task)

def _build_correction(m, text):
    data: dict = {}
    data["search_scope"] = "today" if re.search(r"\b(?:hoje|de hoje)\b", text) else "recent"
    hint = re.sub(r"\b(?:corrig[ae]|corrij[ae]|corrigir|na\s+verdade|errei|t[áa]\s+errado)\b", "", text, flags=re.I)
    mm = re.search(r"(.+?)\s+(?:pra|para|é|foi)\s+(.+)", hint)
    if mm:
        data["search_hint"] = mm.group(1).strip()
        data["new_value"] = mm.group(2).strip().rstrip(".")
        if re.search(r"\b(?:peso|quilos|kg)\b", mm.group(1)): data["new_field"] = "weight"
        elif re.search(r"\b(?:calorias|cal)\b", mm.group(1)): data["new_field"] = "calories"
        elif re.search(r"\b(?:valor|pre[çc]o|amount|reais)\b", mm.group(1)): data["new_field"] = "amount"
        else: data["new_field"] = "description"
    else:
        data["search_hint"] = hint.strip().rstrip(".")
        data["new_field"] = "description"; data["new_value"] = hint.strip().rstrip(".")
    return {"type": "correction", "data": data}

correction = Pattern("correction", "correction", None, [
    r"\bcorrig[ae]\b", r"\bcorrij[ae]\b", r"\bcorrigir\b", r"\bna\s+verdade\b",
    r"\berrei\b", r"\bt[áa]\s+errado\b",
], r".*", 0.80, _build_correction, ["search_hint"])


# -- P9: Mark Done --

def _build_mark_done(m, text):
    data: dict = {}
    explicit = bool(re.search(
        r"\b(?:conclu[íi]|terminei|finalizei|acabei\s+de|j[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi|organizei|arrumei)|(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto))\b",
        text, re.I))
    hint = re.sub(
        r"\b(?:conclu[íi]|terminei|finalizei|acabei\s+de|organizei|resolvi|arrumei|limpei|entreguei|mandei|enviei|liguei|marquei|agendei|estudei|consertei|providenciei|verifiquei|chequei|confirmei)\b",
        "", text, flags=re.I)
    hint = re.sub(r"\bj[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi|organizei|arrumei)\b", "", hint, flags=re.I)
    hint = re.sub(r"\b(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto)\b", "", hint, flags=re.I)
    hint = re.sub(r"\b(?:hoje|agora|j[áa]|finalmente|enfim)\b", "", hint, flags=re.I)
    hint = re.sub(r"\s+", " ", hint).strip().rstrip(".")
    if hint: data["task_hint"] = hint
    data["_explicit"] = explicit
    if re.search(r"\b(?:paguei|pagar|conta|boleto|fatura|mensalidade|IPTU|condom[íi]nio|financiamento)\b", text, re.I):
        data["is_recurring"] = True
    return {"type": "mark_done", "data": data}

def _adj_mark_done(item, base):
    return 0.92 if item.get("data", {}).get("_explicit") else base

mark_done = Pattern("mark_done", "mark_done", None, [
    r"\bconclu[íi]\b", r"\bterminei\b", r"\bfinalizei\b", r"\bacabei\s+de\b",
    r"\b(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto)\b",
    r"\bj[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi|organizei|arrumei)\b",
    r"\borganizei\b", r"\bresolvi\b", r"\barrumei\b", r"\blimpei\b", r"\bentreguei\b",
    r"\bmandei\b", r"\benviei\b", r"\bliguei\b", r"\bmarquei\b", r"\bagendei\b",
    r"\bestudei\b", r"\bconsertei\b", r"\bprovidenciei\b", r"\bverifiquei\b",
    r"\bchequei\b", r"\bconfirmei\b",
], r".*", 0.75, _build_mark_done, ["task_hint"], adjust_confidence=_adj_mark_done)


# -- P10: Undo --

def _build_undo(m, text):
    hint = re.sub(r"\b(?:desfaz|desfazer|desmarca|desmarcar|não\s+(?:conclu[íi]|fiz|era|foi)|reverte|reverter|volta|anula|anular)\b", "", text, flags=re.I)
    hint = re.sub(r"\b(?:hoje|agora|isso|aquilo|essa|essa\s+tarefa|aquele)\b", "", hint, flags=re.I)
    hint = re.sub(r"\s+", " ", hint).strip().rstrip(".")
    return {"type": "undo", "data": {"task_hint": hint} if hint else {}}

undo = Pattern("undo", "undo", None, [
    r"\bdesfaz\b", r"\bdesfazer\b", r"\bdesmarca\b", r"\bdesmarcar\b",
    r"\bnão\s+(?:conclu[íi]|fiz|era|foi)\b", r"\breverte\b", r"\breverter\b",
    r"\bvolta\b", r"\banula\b", r"\banular\b",
], r".*", 0.92, _build_undo, ["task_hint"])


# -- Registry --

def default_registry() -> PatternRegistry:
    r = PatternRegistry()
    r.register_all([weight, lifting, piano, cardio, expense, food, task, correction, mark_done, undo])
    return r
