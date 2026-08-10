"""T14 — Recurring task creator.

Creates blocks in ``10 Daily/Tarefas Recorrentes.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from patterns import normalize
from formatter.schema import RecurringTaskData

logger = logging.getLogger(__name__)

_PRIORITY_MAP = {"urgente": "🔺", "alta": "⏫", "média": "🔼"}


def format_recurring(
    data: RecurringTaskData,
    date_str: str,
    vault_dir: Path,
) -> tuple[str | None, str | None]:  # (formatted_line, warning)
    """Format a recurring task line and check for duplicates.

    Returns ``(line, warning)``.  If a duplicate exists, *line* is ``None``
    and *warning* explains why.
    """
    target_path = vault_dir / "10 Daily" / "Tarefas Recorrentes.md"

    # Check duplicate
    if _is_duplicate(data.description, target_path):
        return None, (
            f"Tarefa recorrente '{data.description}' já existe em "
            f"Tarefas Recorrentes.md — não foi recriada."
        )

    # Build the line
    parts = ["- [ ]", data.description]

    if data.is_payment:
        parts.append("#chore #payment")
    else:
        parts.append("#chore")

    if data.priority and data.priority in _PRIORITY_MAP:
        parts.append(_PRIORITY_MAP[data.priority])

    parts.append(f"🔁 {data.frequency}")

    if data.due_day is not None:
        # Compute next occurrence date
        from datetime import date as dt
        today = dt.today()
        # Simple: use the due_day in the current or next month
        try:
            target = today.replace(day=min(data.due_day, 28))
            if target <= today:
                # Move to next month
                if today.month == 12:
                    target = target.replace(year=today.year + 1, month=1)
                else:
                    target = target.replace(month=today.month + 1)
            parts.append(f"📅 {target.isoformat()}")
        except ValueError:
            pass

    parts.append(f"➕ {date_str}")

    if data.due_date:
        parts.append(f"📅 {data.due_date}")
    elif data.due_day and "📅" not in " ".join(parts):
        pass  # Already handled above

    line = " ".join(parts)

    # If the file doesn't end with ---, add it before the new block
    if target_path.exists():
        content = target_path.read_text(encoding="utf-8")
        if not content.rstrip().endswith("---"):
            line = "---\n" + line
    else:
        line = "---\n" + line

    return line, None


def _is_duplicate(description: str, target_path: Path) -> bool:
    """Check if a similar recurring task already exists."""
    if not target_path.exists():
        return False

    norm_desc = normalize(description)
    if not norm_desc:
        return False

    content = target_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        if not line.strip().startswith("- [ ]"):
            continue
        norm_line = normalize(line)
        if not norm_line:
            continue
        # High overlap → duplicate
        desc_tokens = set(norm_desc.split())
        line_tokens = set(norm_line.split())
        if not desc_tokens:
            continue
        overlap = len(desc_tokens & line_tokens) / len(desc_tokens)
        if overlap > 0.6:
            return True

    return False
