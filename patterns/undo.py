"""P10 — Undo pattern: \"desfaz X\", \"não concluí Y\", \"desmarca Z\"."""

from __future__ import annotations

import re

from patterns import Pattern


def _build(match, text: str) -> dict:
    data: dict = {}

    hint = text
    hint = re.sub(
        r"\b(?:desfaz|desfazer|desmarca|desmarcar|não\s+(?:conclu[íi]|fiz|era|foi)|reverte|reverter|volta|anula|anular)\b",
        "", hint, flags=re.IGNORECASE,
    )
    hint = re.sub(r"\b(?:hoje|agora|isso|aquilo|essa|essa\s+tarefa|aquele)\b", "", hint, flags=re.IGNORECASE)
    hint = re.sub(r"\s+", " ", hint).strip().rstrip(".")

    if hint:
        data["task_hint"] = hint

    return {"type": "undo", "data": data}


undo_pattern = Pattern(
    name="undo",
    category="correction",  # Reuse correction's vault search + edit
    habit=None,
    triggers=[
        r"\bdesfaz\b",
        r"\bdesfazer\b",
        r"\bdesmarca\b",
        r"\bdesmarcar\b",
        r"\bnão\s+(?:conclu[íi]|fiz|era|foi)\b",
        r"\breverte\b",
        r"\breverter\b",
        r"\bvolta\b",
        r"\banula\b",
        r"\banular\b",
    ],
    regex=r".*",
    confidence=0.92,  # Explicit undo intent → high confidence
    build_item=_build,
    required_fields=["task_hint"],
)
