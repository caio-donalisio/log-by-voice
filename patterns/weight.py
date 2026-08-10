"""P1 — Weight log: \"me pesei X quilos\" and variations."""

from __future__ import annotations

from patterns import Pattern


def _build(match, text: str) -> dict:
    weight_str = match.group("weight").replace(",", ".")
    return {
        "type": "habit_log",
        "habit": "weight",
        "data": {"weight_kg": float(weight_str)},
    }


weight_pattern = Pattern(
    name="weight_log",
    category="habit_log",
    habit="weight",
    triggers=[
        # "me pesei" and conjugations
        r"\b(?:me\s+)?pesei\b",
        r"\b(?:me\s+)?pesar\b",
        r"\b(?:me\s+)?pesou\b",
        # "o peso deu/tá/está/marcou"
        r"\b(?:o\s+)?(?:meu\s+)?peso\s+(?:deu|t[áa]|est[áa]|marcou|estava)\b",
        # "tô/estou pesando"
        r"\b(?:t[ôo]|estou|to)\s+pesando\b",
        # "balança marcou/deu/mostrou"
        r"\bbalan[çc]a\s+(?:marcou|deu|mostrou)\b",
    ],
    regex=r"(?P<weight>\d+(?:[.,]\d+)?)\s*(?:quilos|kg|kilos|quilo)?",
    confidence=0.95,
    build_item=_build,
    required_fields=["weight_kg"],
)
