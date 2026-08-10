"""Relative date parser for Portuguese expressions."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

# Day-of-week mapping (Portuguese → Python weekday 0=Mon..6=Sun)
_WEEKDAY_MAP: dict[str, int] = {
    "segunda": 0, "segunda-feira": 0, "terça": 1, "terça-feira": 1,
    "terca": 1, "terca-feira": 1, "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3, "sexta": 4, "sexta-feira": 4,
    "sábado": 5, "sabado": 5, "domingo": 6,
}

# Month name → number
_MONTH_MAP: dict[str, int] = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
    "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

# "dia N" — captures day number
_DAY_OF_MONTH_RE = re.compile(r"\bdia\s+(\d{1,2})\b", re.IGNORECASE)

# Words after a day number that INVALIDATE it as a date
_DAY_INVALID_FOLLOW = re.compile(
    r"\bdia\s+\d{1,2}\s+(?:d[ae]ss[ae]|d[ae]st[ae]|ness[ae]|nest[ae]|n[ae])\s+(?:semana)\b",
    re.IGNORECASE,
)

# "de <month>" after a day number (e.g. "dia 30 de setembro")
_MONTH_AFTER_DAY_RE = re.compile(
    r"\bdia\s+\d{1,2}\s+de\s+(" + "|".join(_MONTH_MAP) + r")\b",
    re.IGNORECASE,
)

# "do mês que vem", "do próximo mês" after a day
_NEXT_MONTH_MODIFIER_RE = re.compile(
    r"\b(?:do|no)\s+(?:m[êe]s\s+que\s+vem|pr[óo]ximo\s+m[êe]s)\b",
    re.IGNORECASE,
)

_RELATIVE_PATTERNS: list[tuple[re.Pattern, int]] = [
    # Days
    (re.compile(r"\bhoje\b", re.IGNORECASE), 0),
    (re.compile(r"\bamanh[ãa]\b", re.IGNORECASE), 1),
    (re.compile(r"\bdepois\s+de\s+amanh[ãa]\b", re.IGNORECASE), 2),
    # Weeks (esse/este/a = all "this" in spoken PT)
    (re.compile(r"\b(?:ess[ae]|est[ae]|ness[ae]|nest[ae])\s+semana\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:pr[óo]xima\s+semana|semana\s+que\s+vem)\b", re.IGNORECASE), 7),
    # Months
    (re.compile(r"\b(?:ess[ae]|est[ae]|ness[ae]|nest[ae])\s+m[êe]s\b", re.IGNORECASE), 30),
    (re.compile(r"\bm[êe]s\s+que\s+vem\b", re.IGNORECASE), 30),
    (re.compile(r"\bpr[óo]ximo\s+m[êe]s\b", re.IGNORECASE), 30),
    # Years
    (re.compile(r"\bano\s+que\s+vem\b", re.IGNORECASE), 365),
    (re.compile(r"\bpr[óo]ximo\s+ano\b", re.IGNORECASE), 365),
]


def _clamp_day(year: int, month: int, day: int) -> int:
    """Clamp day to the actual last day of the month."""
    last = calendar.monthrange(year, month)[1]
    return min(day, last)


def parse_relative_date(text: str, today: date | None = None) -> str | None:
    """Parse a relative date expression into YYYY-MM-DD.

    Handles:
    - Relative: hoje, amanhã, domingo, essa semana, mês que vem, ano que vem
    - Day of month: dia 20, dia 5
    - Month: dia 30 de setembro, dia 5 de janeiro
    - Modifiers: dia 30 do mês que vem, dia 15 do próximo mês

    Returns ``None`` if no recognizable date expression is found.
    """
    if today is None:
        today = date.today()

    # 1. "dia N de <month>" — most specific
    m = _MONTH_AFTER_DAY_RE.search(text)
    if m:
        day = int(re.search(r"\d{1,2}", m.group(0)).group(0))  # type: ignore[union-attr]
        month_name = m.group(1).lower()
        month = _MONTH_MAP[month_name]
        year = today.year
        if month < today.month:
            year += 1
        try:
            target = date(year, month, _clamp_day(year, month, day))
            return target.isoformat()
        except ValueError:
            return None

    # 2. "ano que vem" / "próximo ano" — full year shift for day expressions
    next_year = bool(
        re.search(r"\b(?:ano\s+que\s+vem|pr[óo]ximo\s+ano)\b", text, re.IGNORECASE)
    )

    # 3. "dia N" — skip if invalidated by semana/mês passado/ano passado
    if _DAY_INVALID_FOLLOW.search(text):
        pass  # "dia 15 dessa semana" → not a date
    else:
        m = _DAY_OF_MONTH_RE.search(text)
        if m:
            day = int(m.group(1))
            try:
                if next_year:
                    year = today.year + 1
                    target = today.replace(year=year, day=1)
                    target = date(year, target.month, _clamp_day(year, target.month, day))
                elif _NEXT_MONTH_MODIFIER_RE.search(text):
                    if today.month == 12:
                        target = date(today.year + 1, 1, _clamp_day(today.year + 1, 1, day))
                    else:
                        target = date(today.year, today.month + 1, _clamp_day(today.year, today.month + 1, day))
                else:
                    target = today.replace(day=_clamp_day(today.year, today.month, day))
                    if target <= today:
                        if today.month == 12:
                            target = date(today.year + 1, 1, _clamp_day(today.year + 1, 1, day))
                        else:
                            target = date(today.year, today.month + 1, _clamp_day(today.year, today.month + 1, day))
                return target.isoformat()
            except ValueError:
                return None

    # 4. "daqui a X dias/semanas/meses" or "em X dias/semanas/meses"
    m = re.search(
        r"\b(?:daqui\s+a|em)\s+(\d+)\s+(dias?|semanas?|m[êe]s(?:es)?)\b",
        text, re.IGNORECASE,
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if "semana" in unit:
            n *= 7
        elif "mês" in unit or "mes" in unit:
            n *= 30
        target = today + timedelta(days=n)
        return target.isoformat()

    # 5. Day-of-week
    for name, dow in _WEEKDAY_MAP.items():
        if re.search(rf"\b(?:no\s+|na\s+|neste\s+|nessa\s+|pr[óo]xim[oa]\s+)?{name}\b", text, re.IGNORECASE):
            days_ahead = dow - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = today + timedelta(days=days_ahead)
            if re.search(rf"\bpr[óo]xim[oa]\s+{name}\b", text, re.IGNORECASE):
                target += timedelta(days=7)
            return target.isoformat()

    # 6. Relative expressions (weeks, months)
    for pattern, days_offset in _RELATIVE_PATTERNS:
        if pattern.search(text):
            target = today + timedelta(days=days_offset)
            return target.isoformat()

    return None
