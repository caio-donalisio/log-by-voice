"""P9 — Mark done pattern: \"concluí X\", \"terminei Y\", \"já paguei Z\"."""

from __future__ import annotations

import re

from patterns import Pattern


def _build(match, text: str) -> dict:
    data: dict = {}

    # Extract task hint — what was completed
    hint = text

    # Remove trigger phrases (including past-tense verbs)
    hint = re.sub(
        r"\b(?:conclu[íi]|terminei|finalizei|acabei\s+de|organizei|resolvi|arrumei|limpei|entreguei|mandei|enviei|liguei|marquei|agendei|estudei|consertei|providenciei|verifiquei|chequei|confirmei)\b",
        "", hint, flags=re.IGNORECASE,
    )
    hint = re.sub(
        r"\bj[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi|organizei|arrumei)\b",
        "", hint, flags=re.IGNORECASE,
    )
    hint = re.sub(
        r"\b(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto)\b",
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
        # Explicit completion
        r"\bconclu[íi]\b",
        r"\bterminei\b",
        r"\bfinalizei\b",
        r"\bacabei\s+de\b",
        r"\b(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto)\b",
        r"\bj[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi|organizei|arrumei)\b",
        # Natural past tense — action completed
        r"\borganizei\b",
        r"\bresolvi\b",
        r"\barrumei\b",
        r"\blimpei\b",
        r"\bentreguei\b",
        r"\bmandei\b",
        r"\benviei\b",
        r"\bliguei\b",
        r"\bmarquei\b",
        r"\bagendei\b",
        r"\bestudei\b",
        r"\bconsertei\b",
        r"\bprovidenciei\b",
        r"\bverifiquei\b",
        r"\bchequei\b",
        r"\bconfirmei\b",
    ],
    regex=r".*",
    confidence=0.80,
    build_item=_build,
    required_fields=["task_hint"],
)
