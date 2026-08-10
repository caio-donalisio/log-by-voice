"""P2 — Lifting log: \"fiz X séries de Y de Z quilos de EXERCÍCIO\"."""

from __future__ import annotations

import re
from typing import Any

from patterns import Pattern


def _build(match, text: str) -> dict:
    data: dict[str, Any] = {}

    # Parse sets
    m = re.search(r"(?P<sets>\d+)\s*(?:s[ée]ries?|series?|x)", text)
    if m:
        data["sets"] = int(m.group("sets"))

    # Parse reps
    m = re.search(r"(?P<reps>\d+)\s*(?:repeti[çc][õo]es|reps?|repeti[çc]|rep)", text)
    if m:
        data["reps"] = int(m.group("reps"))

    # Parse weight
    m = re.search(
        r"(?P<weight>\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos|quilo)",
        text,
    )
    if m:
        data["weight_kg"] = float(m.group("weight").replace(",", "."))

    # Parse exercise name — clean the text of known patterns, keep the rest
    exercise_text = text
    # Remove leading filler verbs
    exercise_text = re.sub(
        r"\b(?:fiz|fazer|fizemos|treinei|malhei|treinar|malhar)\b",
        "",
        exercise_text,
        flags=re.IGNORECASE,
    )
    # Remove number patterns
    exercise_text = re.sub(
        r"\d+\s*(?:s[ée]ries?|series?|x|repeti[çc][õo]es|reps?|quilos|kg|kilos|quilo)",
        "",
        exercise_text,
    )
    exercise_text = re.sub(r"\d+(?:[.,]\d+)?", "", exercise_text)
    # Remove lingering connectors
    exercise_text = re.sub(r"\s+de\s+", " ", exercise_text)
    exercise_text = exercise_text.strip().rstrip(".")
    if exercise_text:
        data["exercise_hint"] = exercise_text

    return {
        "type": "habit_log",
        "habit": "lifting",
        "data": data,
    }


# Trigger patterns — exercise names + generic lifting phrases
_EXERCISE_NAMES = [
    r"\bsupino\b", r"\bagachamento\b", r"\brosca\b", r"\btr[íi]ceps\b",
    r"\bb[íi]ceps\b", r"\bleg\s?press\b", r"\bremada\b",
    r"\bdesenvolvimento\b", r"\bstiff\b", r"\bpuxada\b",
    r"\beleva[çc][ãa]o\b", r"\babdominal\b", r"\bprancha\b",
    r"\bafundo\b", r"\bpassada\b", r"\bburpee\b", r"\bflex[ãa]o\b",
]

lifting_pattern = Pattern(
    name="lifting_log",
    category="habit_log",
    habit="lifting",
    triggers=[
        r"\bs[ée]ries?\s+de\b",
        r"\brepeti[çc][õo]es?\b",
        # Compact format "3x10" — require BOTH numbers ≥ 2 to avoid scorelines (3x1)
        r"\b[2-9]\d*\s*[xX]\s*[2-9]\d*\b",
        *_EXERCISE_NAMES,
    ],
    regex=r".*",  # Always matches — extraction is in build_item
    confidence=0.90,
    build_item=_build,
    required_fields=["exercise_hint"],
)
