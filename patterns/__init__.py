"""
Pattern dataclass, registry, and text normalization utilities.

A Pattern defines triggers (regexes that identify this category) and an
extraction regex (with named groups that capture structured data).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from formatter.schema import ItemType, HabitType


# ---------------------------------------------------------------------------
# Pattern definition
# ---------------------------------------------------------------------------

@dataclass
class Pattern:
    """A single classification pattern.

    Attributes:
        name: Short identifier, e.g. ``"weight_log"``.
        category: The ItemType this pattern produces.
        habit: For ``habit_log`` items, which habit subtype.
        triggers: List of regex patterns.  If ANY trigger matches the
            segment, this pattern is a candidate.
        regex: Extraction regex with named groups (``(?P<name>...)``).
            Runs only after a trigger matches.
        confidence: 0.0–1.0.  Items with confidence ≥ 0.80 are used
            directly; lower-confidence matches go to the LLM fallback.
        build_item: Callable that receives the regex match object and the
            original text segment, and returns an item dict suitable for
            ``formatter.schema.validate_item()``.
        required_fields: Named groups that MUST be captured for this
            pattern to be considered a match.  If any is missing, the
            segment goes unmatched.
    """

    name: str
    category: ItemType
    habit: HabitType | None
    triggers: list[str]
    regex: str
    confidence: float
    build_item: Callable[[re.Match, str], dict[str, Any]]
    required_fields: list[str] = field(default_factory=list)
    # Optional — called with the built item dict; returns adjusted confidence
    adjust_confidence: Callable[[dict[str, Any], float], float] | None = None

    # Compiled at registration time by the registry
    _trigger_res: list[re.Pattern] = field(default_factory=list, repr=False)
    _extraction_re: re.Pattern | None = field(default=None, repr=False)


class PatternRegistry:
    """Holds all registered patterns and provides the match loop."""

    def __init__(self) -> None:
        self._patterns: list[Pattern] = []

    def register(self, pattern: Pattern) -> None:
        """Compile and store a pattern."""
        pattern._trigger_res = [
            re.compile(trig, re.IGNORECASE | re.UNICODE)
            for trig in pattern.triggers
        ]
        pattern._extraction_re = re.compile(
            pattern.regex, re.IGNORECASE | re.UNICODE
        )
        self._patterns.append(pattern)

    def register_all(self, patterns: list[Pattern]) -> None:
        for p in patterns:
            self.register(p)

    @property
    def patterns(self) -> list[Pattern]:
        return list(self._patterns)


# ---------------------------------------------------------------------------
# Text normalization (shared by all patterns)
# ---------------------------------------------------------------------------

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
                total *= val  # "duzentos e cinquenta" = 200 + 50, not 200*50
            else:
                total += val
        return total if total > 0 else None

    return None
