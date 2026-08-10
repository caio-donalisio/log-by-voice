"""P2 — Lifting log: \"fiz X séries de Y de Z quilos de EXERCÍCIO\"."""

from __future__ import annotations

import re
from typing import Any

from patterns import Pattern


# Map Portuguese number words to ints
_NUM_WORDS: dict[str, int] = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2,
    "três": 3, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
}


def _extract_number(text: str, pattern: str) -> int | None:
    """Try to find a number (digit or word) matching *pattern*."""
    # Try digit first
    m = re.search(pattern, text)
    if m and m.group(1):
        return int(m.group(1))
    # Try number word
    for word, val in _NUM_WORDS.items():
        word_pat = pattern.replace(r"\d+", word)
        if re.search(word_pat, text):
            return val
    return None


def _build(match, text: str) -> dict:
    data: dict[str, Any] = {}

    # Parse sets
    sets = _extract_number(text, r"(?P<n>\d+)\s*(?:s[ée]ries?|series?|x)")
    if sets is not None:
        data["sets"] = sets

    # Parse reps
    reps = _extract_number(text, r"(?P<n>\d+)\s*(?:repeti[çc][õo]es|reps?|repeti[çc]|rep)")
    if reps is not None:
        data["reps"] = reps

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
        r"\b(?:fiz|fazer|fizemos|treinei|malhei|treinar|malhar|hoje|eu)\b",
        "",
        exercise_text,
        flags=re.IGNORECASE,
    )
    # Remove Portuguese number words
    exercise_text = re.sub(
        r"\b(?:três|tres|duas|dois|uma|um|quatro|cinco|seis|sete|oito|nove|dez)\b",
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
    # Remove lingering connectors and punctuation
    exercise_text = re.sub(r"\s+de\s+", " ", exercise_text)
    exercise_text = re.sub(r"^[,\s]+", "", exercise_text)
    exercise_text = re.sub(r"[,\s]+$", "", exercise_text)
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
