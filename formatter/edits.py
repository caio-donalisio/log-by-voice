"""T13 — Edit operations: mark_done, correction, complement.

All three share the same vault search infrastructure and fall back to
comment when no clear match is found.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NamedTuple

from text_utils import normalize

logger = logging.getLogger(__name__)

# Restrict edits to these directories (relative to vault root).
# Edits outside these paths fall back to comment.
_ALLOWED_DIRS = [
    "10 Daily",
    "20 Pessoal/Aniversários",
]

# Files excluded from search (templates, readmes)
_SKIP_FILES = {"_README.md", "Tarefas Recorrentes.md"}

# Search scopes
_RECENT_DAYS = 30


class Match(NamedTuple):
    path: Path
    line_number: int      # 1-based
    line_text: str
    score: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_and_mark_done(
    task_hint: str,
    date_str: str,
    vault_dir: Path,
    is_recurring: bool = False,
    comment: str | None = None,
) -> tuple[str | None, list[str]]:  # (edited_file_path_or_None, warnings)
    """Mark a task as done.

    Returns ``(file_path, warnings)``.  *file_path* is the path to the file
    that was modified, or ``None`` if no match was found (fallback to comment).
    """
    match = _find_match(task_hint, vault_dir)
    if match is None:
        return None, [
            f"Não encontrei a tarefa '{task_hint}' para marcar como concluída."
        ]

    lines = _read(match.path)
    old_line = lines[match.line_number - 1]

    # Replace [ ] with [x]
    new_line = re.sub(r"-\s*\[ \]", "- [x]", old_line, count=1)
    # Append ✅ date if not already present
    done_marker = f"✅ {date_str}"
    if done_marker not in new_line:
        new_line = new_line.rstrip("\n") + f" {done_marker}\n"

    lines[match.line_number - 1] = new_line

    # If recurring, create next occurrence
    if is_recurring and "🔁" in old_line:
        next_line = _create_next_occurrence(old_line, date_str)
        if next_line:
            lines.insert(match.line_number, next_line + "\n")

    # Add comment sub-bullet if provided
    if comment:
        lines.insert(match.line_number + (2 if is_recurring else 1),
                     f"    - {comment}\n")

    _write(match.path, lines)
    return str(match.path), []


def find_and_correct(
    search_hint: str,
    new_field: str,
    new_value: str,
    vault_dir: Path,
    search_scope: str = "today",
) -> tuple[str | None, list[str]]:
    """Correct a previously logged value.

    Edits the matching line in-place, replacing only the targeted field.
    """
    match = _find_match(search_hint, vault_dir, search_scope)
    if match is None:
        return None, [
            f"Não encontrei a anotação '{search_hint}' para corrigir."
        ]

    lines = _read(match.path)
    old_line = lines[match.line_number - 1]

    # Replace [field:: old_value] with [field:: new_value]
    field_pattern = re.compile(
        rf"\[{re.escape(new_field)}::\s*([^\]]*)\]"
    )
    new_line = field_pattern.sub(
        f"[{new_field}:: {new_value}]", old_line
    )
    lines[match.line_number - 1] = new_line

    _write(match.path, lines)
    return str(match.path), []


def find_and_complement(
    search_hint: str,
    detail: str,
    vault_dir: Path,
) -> tuple[str | None, list[str]]:
    """Add a detail sub-bullet under an existing line."""
    match = _find_match(search_hint, vault_dir)
    if match is None:
        return None, [
            f"Não encontrei a tarefa '{search_hint}' para complementar."
        ]

    lines = _read(match.path)
    lines.insert(match.line_number, f"    - {detail}\n")

    _write(match.path, lines)
    return str(match.path), []


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _find_match(
    hint: str,
    vault_dir: Path,
    scope: str = "today",
) -> Match | None:
    """Search allowed directories for a line matching *hint*."""
    norm_hint = normalize(hint)
    if not norm_hint:
        return None

    candidates: list[Match] = []

    for allowed_rel in _ALLOWED_DIRS:
        search_root = vault_dir / allowed_rel
        if not search_root.is_dir():
            continue

        for md_file in sorted(search_root.rglob("*.md"), reverse=True):
            # Skip template/readme files
            if md_file.name in _SKIP_FILES:
                continue
            # Skip files outside the allowed directory
            try:
                md_file.relative_to(search_root)
            except ValueError:
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            for i, line in enumerate(content.splitlines(), start=1):
                score = _score_line(norm_hint, normalize(line))
                if score >= 60:
                    candidates.append(Match(md_file, i, line, score))

    if not candidates:
        return None

    candidates.sort(key=lambda m: m.score, reverse=True)
    best = candidates[0]

    # Ambiguity check: if top 2 scores are too close and point to DIFFERENT
    # files/lines, reject.  If they point to identical content (same line
    # across multiple days — common for habits), prefer the most recent file
    # (already first in sorted order since we sort reverse=True).
    if len(candidates) >= 2:
        second_score = candidates[1].score
        gap = best.score - second_score
        # If scores are identical (gap=0) and the line "core" matches
        # (same habit, ignoring varying numbers), it's the same habit
        # repeated across days — take the most recent file.
        same_text = (
            _core_text(best.line_text) == _core_text(candidates[1].line_text)
            if gap == 0 else False
        )
        if gap < 20 and not same_text:
            logger.debug(
                "Ambiguous match: '%s' (score=%d) vs '%s' (score=%d)",
                best.line_text[:60], best.score,
                candidates[1].line_text[:60], second_score,
            )
            return None

    # Must be clear: score ≥ 80, or score ≥ 60 with adequate uniqueness
    if best.score < 60:
        return None

    return best


def _core_text(text: str) -> str:
    """Normalize and strip numbers for comparing habit lines across days."""
    import re
    t = normalize(text)
    t = re.sub(r"\d+(?:[.,]\d+)?", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _score_line(hint: str, norm_line: str) -> float:
    """Score a normalized line against a normalized hint.

    Strips inline fields and markers from the line before scoring.
    """
    # Remove [field:: value], #tags, marker emoji
    core = re.sub(r"\[.*?::\s*[^\]]*\]", "", norm_line)
    core = re.sub(r"#\S+", "", core)
    core = re.sub(r"[📅✅🔁⏳➕🔺⏫🔼]", "", core)
    core = re.sub(r"\s+", " ", core).strip()

    if not core:
        return 0.0

    # Exact match
    if hint == core:
        return 100.0
    # Substring — bonus for partial match of the full hint in the core
    if hint in core:
        return 85.0
    if core in hint:
        return 75.0
    # Bonus: each word of hint that appears as substring in core
    hint_words = hint.split()
    matched_words = sum(1 for w in hint_words if w in core)
    word_bonus = (matched_words / max(len(hint_words), 1)) * 10.0
    # Token overlap
    hint_tokens = set(hint.split())
    core_tokens = set(core.split())
    if not hint_tokens:
        return 0.0
    # Stem match: count hint tokens that have a prefix match with any core token
    stem_matches = 0
    for ht in hint_tokens:
        if ht in core_tokens:
            stem_matches += 1
        elif len(ht) >= 5:
            # Check prefix overlap (e.g. organizar ≈ organizei)
            prefix = ht[:5]
            for ct in core_tokens:
                if ct.startswith(prefix) and len(ct) >= len(ht) - 2:
                    stem_matches += 0.8  # Near match
                    break

    effective_overlap = max(
        len(hint_tokens & core_tokens),
        stem_matches,
    ) / max(len(hint_tokens), 1)
    overlap = min(effective_overlap, 1.0)
    score = 0.0
    if overlap > 0.5:
        score = 60.0 * overlap / 0.5
    elif overlap > 0.3:
        score = 40.0 * overlap / 0.3
    # Add word-level substring bonus
    score += word_bonus
    # Fuzzy bonus: catches organizei≈organizar, documentos chinês vs japonês
    import difflib
    fuzzy = difflib.SequenceMatcher(None, hint, core).ratio()
    score += fuzzy * 15.0
    return score


# ---------------------------------------------------------------------------
# Next occurrence for recurring tasks
# ---------------------------------------------------------------------------

def _create_next_occurrence(line: str, completed_date: str) -> str | None:
    """Create the next occurrence line for a recurring task that was just completed.

    Reads the ``🔁`` rule and advances ``📅`` / ``⏳`` accordingly.
    """
    # Extract the recurrence rule
    m = re.search(r"🔁\s*(.+?)(?:\s*➕|\s*📅|\s*$)", line)
    if not m:
        return None
    # For now, create a simple duplicate with ➕ date
    # Full recurrence computation is complex — defer to LLM for now
    new_line = line
    # Replace [x] back to [ ]
    new_line = re.sub(r"-\s*\[x\]", "- [ ]", new_line)
    # Remove ✅ marker
    new_line = re.sub(r"✅\s*\S+", "", new_line)
    # Update ➕
    new_line = re.sub(r"➕\s*\S+", f"➕ {completed_date}", new_line)
    return new_line.strip()


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def _current_date_str() -> str:
    from datetime import date
    return date.today().isoformat()
