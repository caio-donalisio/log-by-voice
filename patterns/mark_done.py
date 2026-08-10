"""P9 — Mark done pattern: \"concluí X\", \"terminei Y\", \"já paguei Z\"."""

from __future__ import annotations

import re

from patterns import Pattern


def _build(match, text: str) -> dict:
    data: dict = {}

    # Extract task hint — what was completed
    hint = text

    # Remove trigger phrases
    hint = re.sub(
        r"\b(?:conclu[íi]|terminei|j[áa]\s+(?:fiz|paguei|terminei|comprei)|finalizei|acabei\s+de)\b",
        "", hint, flags=re.IGNORECASE,
    )
    # Remove filler
    hint = re.sub(r"\b(?:hoje|agora|j[áa]|finalmente|enfim)\b", "", hint, flags=re.IGNORECASE)
    hint = re.sub(r"\s+", " ", hint).strip().rstrip(".")

    if hint:
        data["task_hint"] = hint

    # Detect if this is likely a recurring task (payment-related)
    if re.search(r"\b(?:paguei|pagar|conta|boleto|fatura|mensalidade|IPTU|condom[íi]nio|financiamento)\b", text, re.IGNORECASE):
        data["is_recurring"] = True

    return {"type": "mark_done", "data": data}


mark_done_pattern = Pattern(
    name="mark_done",
    category="mark_done",
    habit=None,
    triggers=[
        r"\bconclu[íi]\b",
        r"\bterminei\b",
        r"\bj[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi)\b",
        r"\bfinalizei\b",
        r"\bacabei\s+de\b",
        r"\b(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto)\b",
    ],
    regex=r".*",
    confidence=0.80,
    build_item=_build,
    required_fields=["task_hint"],
)
