"""
Daily note creation and section management for the Obsidian vault.

Replaces the Claude-driven daily note creation — Python reads the Templater
template, substitutes dates, and creates/appends deterministically.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import override


# ---------------------------------------------------------------------------
# Portuguese locale data (hardcoded — no system locale dependency)
# ---------------------------------------------------------------------------

_WEEKDAYS: dict[int, str] = {
    0: "segunda-feira",
    1: "terça-feira",
    2: "quarta-feira",
    3: "quinta-feira",
    4: "sexta-feira",
    5: "sábado",
    6: "domingo",
}

_MONTHS: dict[int, str] = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

# Validate date_str is strictly YYYY-MM-DD (path traversal guard)
_DATE_STR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_VALID_SECTIONS: set[str] = {
    "### ✅ Tarefas Registradas",
    "### 📓 Anotações",
}


# ---------------------------------------------------------------------------
# Daily note
# ---------------------------------------------------------------------------

def ensure_daily_note(
    vault_dir: Path,
    date_str: str,
    time_str: str,
) -> tuple[Path, bool]:
    """Return (path, created) for the daily note.

    If the note doesn't exist, it is created from the vault's daily template
    with all Templater placeholders resolved for *date_str*.
    """
    # Validate date_str format to prevent path traversal
    if not _DATE_STR_RE.match(date_str):
        raise ValueError(
            f"date_str must be YYYY-MM-DD, got: {date_str!r}"
        )

    note_path = vault_dir / "10 Daily" / f"{date_str}.md"
    if note_path.exists():
        return note_path, False

    template_path = vault_dir / "_templates" / "generic_daily_note.md"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template diário não encontrado: {template_path}"
        )

    dt = _parse_date(date_str)
    template = template_path.read_text(encoding="utf-8")
    content = _resolve_template(template, dt, time_str)

    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    return note_path, True


def append_to_section(
    note_path: Path,
    section_heading: str,
    lines: list[str],
) -> None:
    """Append *lines* at the end of *section_heading* in *note_path*.

    If the section heading is not found, it is created at the end of the file.
    """
    if section_heading not in _VALID_SECTIONS:
        raise ValueError(
            f"Seção desconhecida: {section_heading}. "
            f"Válidas: {', '.join(sorted(_VALID_SECTIONS))}"
        )

    content = note_path.read_text(encoding="utf-8")
    new_content = _insert_after_section(content, section_heading, lines)
    note_path.write_text(new_content, encoding="utf-8")


def read_file_lines(path: Path) -> list[str]:
    """Read file, return lines (with trailing newlines preserved)."""
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def write_file_lines(path: Path, lines: list[str]) -> None:
    """Write lines to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Templater resolution
# ---------------------------------------------------------------------------

# Matches {{date:FORMAT}} and {{time:FORMAT}}
_DATE_TAG_RE = re.compile(r"\{\{(date|time):([^}]+)\}\}")

# Matches <% tp.date.now("FORMAT", OFFSET, REFERENCE) %>
_TP_DATE_NOW_RE = re.compile(
    r"<%[ \t]*tp\.date\.now\([ \t]*\"([^\"]+)\"[ \t]*,[ \t]*(-?\d+)[ \t]*,[ \t]*([^)]+)\)[ \t]*%>"
)

# Matches <% tp.file.title %>
_TP_FILE_TITLE_RE = re.compile(r"<%[ \t]*tp\.file\.title[ \t]*%>")


def _resolve_template(template: str, dt: date, time_str: str) -> str:
    """Resolve all Templater placeholders in *template* for *dt* and *time_str*."""
    result = template

    # 1. Resolve {{date:FORMAT}} and {{time:FORMAT}}
    def _date_tag_replacer(m: re.Match) -> str:
        kind = m.group(1)
        fmt = m.group(2)
        if kind == "date":
            return _format_moment_date(dt, fmt)
        else:
            return _format_moment_time(time_str, fmt)

    result = _DATE_TAG_RE.sub(_date_tag_replacer, result)

    # 2. Resolve <% tp.date.now("FORMAT", OFFSET, REFERENCE) %>
    def _tp_date_replacer(m: re.Match) -> str:
        fmt = m.group(1)
        offset = int(m.group(2))
        ref = m.group(3).strip()
        # Reference is always tp.file.title for daily notes
        ref_date = dt  # tp.file.title = the note's date = our dt
        target = ref_date + timedelta(days=offset)
        return _format_moment_date(target, fmt)

    result = _TP_DATE_NOW_RE.sub(_tp_date_replacer, result)

    # 3. Resolve <% tp.file.title %>
    result = _TP_FILE_TITLE_RE.sub(dt.isoformat(), result)

    return result


# ---------------------------------------------------------------------------
# Moment.js → Python date formatting (Portuguese locale)
# ---------------------------------------------------------------------------

# Regex to match Moment.js bracket-escaped literals: [...] → literal text
_BRACKET_ESCAPE_RE = re.compile(r"\[([^\]]*)\]")


def _format_moment_date(dt: date, fmt: str) -> str:
    """Format a date using Moment.js-compatible format tokens (Portuguese).

    Handles Moment.js bracket escaping: ``D [de] MMMM`` → ``10 de agosto``.
    """
    # 1. Protect bracket-escaped literals: replace [text] with a placeholder
    literals: list[str] = []

    def _save_literal(m: re.Match) -> str:
        literals.append(m.group(1))
        return f"\x00LIT{len(literals) - 1}\x00"

    working = _BRACKET_ESCAPE_RE.sub(_save_literal, fmt)

    # 2. Replace format tokens (order matters: longer first)
    tokens = [
        ("dddd", _WEEKDAYS[dt.weekday()]),
        ("YYYY", f"{dt.year:04d}"),
        ("MMMM", _MONTHS[dt.month]),
        ("MM", f"{dt.month:02d}"),
        ("DD", f"{dt.day:02d}"),
        ("D", str(dt.day)),
    ]
    for token, replacement in tokens:
        working = working.replace(token, replacement)

    # 3. Restore literals
    for i, lit in enumerate(literals):
        working = working.replace(f"\x00LIT{i}\x00", lit)

    return working


def _format_moment_time(time_str: str, fmt: str) -> str:
    """Format a time string (HH:MM) using Moment.js-compatible format tokens."""
    # Protect bracket literals
    literals: list[str] = []

    def _save_literal(m: re.Match) -> str:
        literals.append(m.group(1))
        return f"\x00LIT{len(literals) - 1}\x00"

    working = _BRACKET_ESCAPE_RE.sub(_save_literal, fmt)

    parts = time_str.split(":")
    hour = int(parts[0]) if len(parts) >= 1 else 0
    minute = int(parts[1]) if len(parts) >= 2 else 0

    tokens = [
        ("HH", f"{hour:02d}"),
        ("mm", f"{minute:02d}"),
    ]
    for token, replacement in tokens:
        working = working.replace(token, replacement)

    for i, lit in enumerate(literals):
        working = working.replace(f"\x00LIT{i}\x00", lit)

    return working


# ---------------------------------------------------------------------------
# Section insertion
# ---------------------------------------------------------------------------

def _insert_after_section(
    content: str,
    heading: str,
    new_lines: list[str],
) -> str:
    """Insert *new_lines* at the end of the section identified by *heading*.

    The end of a section is the line before the next heading (any `#`-prefixed
    line) or the end of file.  Lines are inserted before the blank line that
    typically separates sections.
    """
    content_lines = content.splitlines(keepends=True)

    # Find the heading line
    heading_idx = None
    for i, line in enumerate(content_lines):
        if line.strip() == heading:
            heading_idx = i
            break

    if heading_idx is None:
        # Section not found — create it at the end of file
        if content_lines and not content_lines[-1].endswith("\n"):
            content_lines.append("\n")
        content_lines.append(f"\n{heading}\n")
        heading_idx = len(content_lines) - 2  # the heading we just added

    # Find the end of this section (next heading or EOF)
    insert_idx = len(content_lines)
    for i in range(heading_idx + 1, len(content_lines)):
        stripped = content_lines[i].strip()
        if stripped.startswith("#"):
            insert_idx = i
            break

    # Walk backwards from insert_idx to find the last non-empty, non-heading
    # content line — we'll insert after it.  But for bullet lists we want to
    # append right before the blank-line-then-next-heading gap.
    #
    # Strategy: insert before the first blank line that precedes a heading or
    # EOF, right after the last content bullet.
    insert_point = insert_idx
    while insert_point > heading_idx + 1 and content_lines[insert_point - 1].strip() == "":
        insert_point -= 1

    # Build the insertion: each new line + newline
    insertion = "".join(
        f"{line}\n" if not line.endswith("\n") else line
        for line in new_lines
    )

    content_lines.insert(insert_point, insertion)
    return "".join(content_lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> date:
    """Parse YYYY-MM-DD into a date object."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()
