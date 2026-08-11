"""P7 — Task + P8 — Correction patterns."""

from __future__ import annotations

import re

from patterns import Pattern


# ---------------------------------------------------------------------------
# P7 — Task
# ---------------------------------------------------------------------------

def _build_task(match, text: str) -> dict:
    data: dict = {}

    # Extract description — everything after the trigger phrase
    desc = text
    desc = re.sub(
        r"\b(?:registr[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|cri[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|anot[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|adicion[ae]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|marqu[ei]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|marcar\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|inser[ai]\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|inserir\s+(?:uma\s+)?tarefa\s*(?:de|pra|para)?|tenho\s+que|preciso\s*(?:de)?|n[ãa]o\s+esquecer\s*(?:de)?|lembrete\s*:?\s*)",
        "", desc, flags=re.IGNORECASE,
    )
    desc = desc.strip().rstrip(".")
    data["description"] = desc

    # Flag explicit task commands for confidence boost
    data["_explicit"] = bool(re.search(
        r"\b(?:tarefa|registr[ae]|cri[ae]\s+tarefa|anot[ae]\s+tarefa|adicion[ae]\s+tarefa|marqu[ei]\s+tarefa|marcar\s+tarefa|inser[ai]\s+tarefa|inserir\s+tarefa)\b",
        text, re.IGNORECASE,
    ))

    # Priority
    if re.search(r"\burgente\b", text, re.IGNORECASE):
        data["priority"] = "urgente"
    elif re.search(r"\balta\b\s+prioridade", text, re.IGNORECASE) or re.search(r"\bprioridade\s+alta\b", text, re.IGNORECASE):
        data["priority"] = "alta"
    elif re.search(r"\bm[ée]dia\b\s+prioridade", text, re.IGNORECASE):
        data["priority"] = "média"

    # Due date — use relative date parser
    from date_utils import parse_relative_date
    parsed_date = parse_relative_date(text)
    if parsed_date:
        data["due_date"] = parsed_date

    # Explicit date pattern: "dia N" or "dia NN" (fallback if parser missed)
    if not parsed_date:
        m = re.search(r"\bdia\s+(\d{1,2})\b", text)
        if m:
            data["due_day"] = int(m.group(1))

    # Time: "às HH:MM" or "às HHh"
    m = re.search(r"(?:[àa]s?)\s*(?P<hour>\d{1,2})\s*[h:]\s*(?P<min>\d{2})?", text)
    if m:
        hour = int(m.group("hour"))
        minute = int(m.group("min")) if m.group("min") else 0
        data["time"] = f"{hour:02d}:{minute:02d}"

    # Comment — if there's text after the main description mentioning context
    # (Simple heuristic: second clause after comma)
    parts = re.split(r"[,;]\s*", desc, maxsplit=1)
    if len(parts) > 1 and len(parts[1]) > 10:
        data["comment"] = parts[1].strip()
        data["description"] = parts[0].strip()

    return {"type": "task", "data": data}


def _adjust_task_confidence(item: dict, base: float) -> float:
    """Boost confidence when the task has explicit signals."""
    data = item.get("data", {})
    if data.get("_explicit"):
        return 0.95  # "adicione tarefa", "marque tarefa", etc.
    if data.get("due_date") or data.get("due_day") or data.get("time") or data.get("priority"):
        return 0.90
    return base


task_pattern = Pattern(
    name="task",
    category="task",
    habit=None,
    triggers=[
        # Explicit task commands (high signal)
        r"\bregistr[ae]\b",
        r"\bcri[ae]\s+(?:uma\s+)?tarefa\b",
        r"\banot[ae]\s+(?:uma\s+)?tarefa\b",
        r"\badicion[ae]\s+(?:uma\s+)?tarefa\b",
        r"\bmarqu[ei]\s+(?:uma\s+)?tarefa\b",
        r"\bmarcar\s+(?:uma\s+)?tarefa\b",
        r"\binser[ai]\s+(?:uma\s+)?tarefa\b",
        r"\binserir\s+(?:uma\s+)?tarefa\b",
        r"\btenho\s+que\b",
        r"\bpreciso\b",
        r"\bn[ãa]o\s+esquecer\b",
        r"\blembrete\s*:",
        r"\blembrar\s+de\b",
        # Infinitive verbs — uniquely task-oriented (excludes verbs covered
        # by other patterns: comprar/pagar→expense, fazer→lifting/cardio, etc.)
        r"\b(?:organizar|resolver|marcar|agendar|enviar|mandar|estudar|limpar|arrumar|consertar|entregar|ligar|providenciar|agilizar|confirmar|verificar|checar|conferir)\b",
    ],
    regex=r".*",
    confidence=0.80,  # Lower base — infinitive verbs aren't always tasks
    build_item=_build_task,
    adjust_confidence=_adjust_task_confidence,
    required_fields=["description"],
)


# ---------------------------------------------------------------------------
# P8 — Correction
# ---------------------------------------------------------------------------

def _build_correction(match, text: str) -> dict:
    data: dict = {}

    # Determine search scope
    if re.search(r"\b(?:hoje|de hoje)\b", text):
        data["search_scope"] = "today"
    else:
        data["search_scope"] = "recent"

    # Clean trigger words
    hint = text
    hint = re.sub(
        r"\b(?:corrige|corrija|corrigir|na\s+verdade|errei|t[áa]\s+errado)\b",
        "", hint, flags=re.IGNORECASE,
    )

    # Try to split into "search_hint" and "new_value"
    # Pattern: "corrige X para Y" or "X na verdade é Y"
    m = re.search(r"(.+?)\s+(?:pra|para|é|foi)\s+(.+)", hint)
    if m:
        data["search_hint"] = m.group(1).strip()
        rest = m.group(2).strip().rstrip(".")
        # Try to identify what field to correct
        if re.search(r"\b(?:peso|quilos|kg)\b", data["search_hint"]):
            data["new_field"] = "weight"
            # Extract just the number
            num = re.search(r"(\d+(?:[.,]\d+)?)", rest)
            if num:
                data["new_value"] = num.group(1)
            else:
                data["new_value"] = rest
        elif re.search(r"\b(?:calorias|cal)\b", data["search_hint"]):
            data["new_field"] = "calories"
            data["new_value"] = rest
        elif re.search(r"\b(?:valor|pre[çc]o|amount|reais)\b", data["search_hint"]):
            data["new_field"] = "amount"
            num = re.search(r"(\d+(?:[.,]\d+)?)", rest)
            data["new_value"] = num.group(1) if num else rest
        else:
            data["new_field"] = "description"
            data["new_value"] = rest
    else:
        data["search_hint"] = hint.strip().rstrip(".")
        data["new_field"] = "description"
        data["new_value"] = hint.strip().rstrip(".")

    return {"type": "correction", "data": data}


correction_pattern = Pattern(
    name="correction",
    category="correction",
    habit=None,
    triggers=[
        r"\bcorrig[ae]\b", r"\bcorrij[ae]\b", r"\bcorrigir\b",
        r"\bna\s+verdade\b", r"\berrei\b", r"\bt[áa]\s+errado\b",
    ],
    regex=r".*",
    confidence=0.80,
    build_item=_build_correction,
    required_fields=["search_hint"],
)
