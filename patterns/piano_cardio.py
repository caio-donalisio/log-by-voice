"""P3 — Piano log: \"pratiquei/estudei X por Y minutos\"."""

from __future__ import annotations

import re

from patterns import Pattern


def _build(match, text: str) -> dict:
    data: dict = {}

    m = re.search(r"(?P<minutes>\d+)\s*(?:min|minutos?|minuto)", text)
    if m:
        data["minutes"] = int(m.group("minutes"))

    # Determine action
    if re.search(r"\bpratiquei\b|\bpraticar\b|\btoquei\b|\btocar\b", text):
        data["action"] = "practice"
    elif re.search(r"\bestudei\b|\bestudar\b", text):
        data["action"] = "study"

    # Piece hint — everything after the verb, minus time info
    hint = text
    hint = re.sub(r"\b(?:pratiquei|praticar|toquei|tocar|estudei|estudar|piano|teclado)\b", "", hint, flags=re.IGNORECASE)
    hint = re.sub(r"\d+\s*(?:min|minutos?|minuto)", "", hint)
    hint = re.sub(r"\d+", "", hint)
    hint = re.sub(r"\s+de\s+", " ", hint)
    hint = hint.strip().rstrip(".")
    if hint:
        data["piece_hint"] = hint

    return {
        "type": "habit_log",
        "habit": "piano",
        "data": data,
    }


piano_pattern = Pattern(
    name="piano_log",
    category="habit_log",
    habit="piano",
    triggers=[
        r"\bpratiquei\b", r"\bpraticar\b", r"\bpraticou\b",
        r"\bestudei\b", r"\bestudar\b", r"\bestudou\b",
        r"\btoquei\b", r"\btocar\b", r"\btocou\b",
        r"\bpiano\b", r"\bteclado\b",
    ],
    regex=r".*",
    confidence=0.85,
    build_item=_build,
    required_fields=["piece_hint"],
)


# ---------------------------------------------------------------------------
# P4 — Cardio log
# ---------------------------------------------------------------------------

_CARDIO_ACTIVITIES = [
    r"\bbicicleta\b", r"\besteira\b", r"\bcorri\b", r"\bcorrida\b",
    r"\bcaminhada\b", r"\bbike\b", r"\bel[ií]ptico\b", r"\beliptico\b",
    r"\bcardio\b", r"\bnata[çc][ãa]o\b", r"\bcorrer\b",
]


def _build_cardio(match, text: str) -> dict:
    data: dict = {}

    m = re.search(r"(?P<minutes>\d+)\s*(?:min|minutos?|minuto)", text)
    if m:
        data["minutes"] = int(m.group("minutes"))

    # Activity name
    for act_re in _CARDIO_ACTIVITIES:
        m = re.search(act_re, text)
        if m:
            data["activity"] = m.group(0).lower()
            break

    if "activity" not in data:
        data["activity"] = "cardio"

    return {
        "type": "habit_log",
        "habit": "cardio",
        "data": data,
    }


cardio_pattern = Pattern(
    name="cardio_log",
    category="habit_log",
    habit="cardio",
    triggers=_CARDIO_ACTIVITIES,
    regex=r".*",
    confidence=0.90,
    build_item=_build_cardio,
    required_fields=[],
)
