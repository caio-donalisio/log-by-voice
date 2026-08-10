"""P9 — Mark done pattern: \"concluí X\", \"terminei Y\", \"organizei Z\"."""

from __future__ import annotations

import re

from patterns import Pattern


def _build(match, text: str) -> dict:
    data: dict = {}

    # Detect trigger type: explicit ("concluí") vs past-tense ("organizei")
    explicit = bool(re.search(
        r"\b(?:conclu[íi]|terminei|finalizei|acabei\s+de|j[áa]\s+(?:fiz|paguei|terminei|comprei|resolvi|organizei|arrumei)|(?:t[áa]\s+)?(?:feito|pago|conclu[íi]do|pronto))\b",
        text, re.IGNORECASE,
    ))

    # Extract task hint — what was completed
    hint = text
    # Remove trigger phrases
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
    data["_explicit"] = explicit

    # Detect if this is likely a recurring task (payment-related)
    if re.search(r"\b(?:paguei|pagar|conta|boleto|fatura|mensalidade|IPTU|condom[íi]nio|financiamento)\b", text, re.IGNORECASE):
        data["is_recurring"] = True

    return {"type": "mark_done", "data": data}


def _adjust_mark_done_confidence(item: dict, base: float) -> float:
    """Boost confidence for explicit completion phrases."""
    explicit = item.get("data", {}).get("_explicit", False)
    if explicit:
        return 0.92  # Well above 0.80 + 0.10 ambiguity gap
    return base  # 0.75 → below threshold → LLM decides


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
        # Natural past tense — action completed (lower confidence)
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
    confidence=0.75,  # Below 0.80 threshold → LLM disambiguates past-tense vs comment
    build_item=_build,
    required_fields=["task_hint"],
    adjust_confidence=_adjust_mark_done_confidence,
)
