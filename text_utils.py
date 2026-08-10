"""Text normalization utilities shared by patterns and formatters.

No dependencies on either package — safe to import from anywhere.
"""

from __future__ import annotations

import re
import unicodedata

# Filler words removed before matching
_FILLER_RE = re.compile(
    r"\b(?:é|tipo\s+assim|tipo|então|né|assim|sabe|ahn?|hum|eh|assim\s+é)\b",
    re.IGNORECASE,
)


def clean_segment(text: str) -> str:
    """Remove filler words and normalise whitespace from a transcript segment."""
    text = _FILLER_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize(text: str) -> str:
    """Aggressive normalisation for matching: lowercase, strip accents,
    collapse whitespace, remove punctuation."""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def number_parse(s: str) -> float | None:
    """Parse a Portuguese-language number string into a float.

    Handles: ``"82.5"``, ``"82,5"``, ``"cem"``, ``"cento e cinquenta"``.
    Returns ``None`` if the string cannot be parsed.
    """
    if not s:
        return None
    s = s.strip().lower()

    # Try direct numeric parse
    try:
        return float(s.replace(",", "."))
    except ValueError:
        pass

    # Portuguese number words
    _WORDS: dict[str, float] = {
        "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2,
        "três": 3, "tres": 3, "quatro": 4, "cinco": 5,
        "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
        "onze": 11, "doze": 12, "treze": 13, "quatorze": 14,
        "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17,
        "dezoito": 18, "dezenove": 19, "vinte": 20,
        "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
        "setenta": 70, "oitenta": 80, "noventa": 90,
        "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
        "trezentos": 300, "trezentas": 300, "quatrocentos": 400,
        "quinhentos": 500, "quinhentas": 500, "mil": 1000,
    }

    if s in _WORDS:
        return _WORDS[s]

    # "cento e cinquenta" → 100 + 50 = 150
    if " e " in s:
        parts = s.split(" e ")
        total = 0.0
        for part in parts:
            val = _WORDS.get(part.strip())
            if val is None:
                return None
            if val >= 100 and total > 0:
                total *= val
            else:
                total += val
        return total if total > 0 else None

    return None
