"""Relative date parser for Portuguese expressions."""

from __future__ import annotations

import re
from datetime import date, timedelta

# Day-of-week mapping (Portuguese → Python weekday 0=Mon..6=Sun)
_WEEKDAY_MAP: dict[str, int] = {
    "segunda": 0, "segunda-feira": 0, "terça": 1, "terça-feira": 1,
    "terca": 1, "terca-feira": 1, "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3, "sexta": 4, "sexta-feira": 4,
    "sábado": 5, "sabado": 5, "domingo": 6,
}

_RELATIVE_PATTERNS: list[tuple[re.Pattern, int]] = [
    # Days
    (re.compile(r"\bhoje\b", re.IGNORECASE), 0),
    (re.compile(r"\bamanh[ãa]\b", re.IGNORECASE), 1),
    (re.compile(r"\bdepois\s+de\s+amanh[ãa]\b", re.IGNORECASE), 2),
    # Weeks
    (re.compile(r"\b(?:essa|nesta)\s+semana\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:pr[óo]xima\s+semana|semana\s+que\s+vem)\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:pr[óo]xim[oa])\s+semana\b", re.IGNORECASE), 7),
    # Months
    (re.compile(r"\b(?:esse|neste)\s+m[êe]s\b", re.IGNORECASE), 30),
    (re.compile(r"\bm[êe]s\s+que\s+vem\b", re.IGNORECASE), 30),
    (re.compile(r"\bpr[óo]ximo\s+m[êe]s\b", re.IGNORECASE), 30),
]

# Day-of-month: "dia 20", "dia 5"
_DAY_OF_MONTH_RE = re.compile(r"\bdia\s+(\d{1,2})\b", re.IGNORECASE)


def parse_relative_date(text: str, today: date | None = None) -> str | None:
    """Parse a relative date expression into YYYY-MM-DD.

    Returns ``None`` if no recognizable date expression is found.
    """
    if today is None:
        today = date.today()

    # Check for explicit day-of-month first (most specific)
    m = _DAY_OF_MONTH_RE.search(text)
    if m:
        day = int(m.group(1))
        try:
            target = today.replace(day=min(day, 28))
            if target <= today:
                # Move to next month
                if today.month == 12:
                    target = target.replace(year=today.year + 1, month=1)
                else:
                    target = target.replace(month=today.month + 1)
            return target.isoformat()
        except ValueError:
            pass

    # Check for day-of-week: "domingo", "segunda-feira", "na terça"
    for name, dow in _WEEKDAY_MAP.items():
        if re.search(rf"\b(?:no\s+|na\s+|neste\s+|nessa\s+|pr[óo]xim[oa]\s+)?{name}\b", text, re.IGNORECASE):
            days_ahead = dow - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = today + timedelta(days=days_ahead)
            # "próxima segunda" means next week, not this week
            if re.search(rf"\bpr[óo]xim[oa]\s+{name}\b", text, re.IGNORECASE):
                target += timedelta(days=7)
            return target.isoformat()

    # Check relative expressions
    for pattern, days_offset in _RELATIVE_PATTERNS:
        if pattern.search(text):
            target = today + timedelta(days=days_offset)
            return target.isoformat()

    return None
