"""
Pattern dataclass, registry, and text normalization utilities.

A Pattern defines triggers (regexes that identify this category) and an
extraction regex (with named groups that capture structured data).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from formatter.schema import ItemType, HabitType
from text_utils import clean_segment, normalize, number_parse  # noqa: F401 — re-exported


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
