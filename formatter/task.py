"""T10 — Task + Comment formatters.

Convert structured Item data into Obsidian markdown lines.
"""

from __future__ import annotations

from formatter.schema import CommentData, TaskData

# Priority markers
_PRIORITY_MAP = {"urgente": "🔺", "alta": "⏫", "média": "🔼"}


def format_task(data: TaskData) -> str:
    """Format a task as an Obsidian Tasks plugin checkbox line.

    Returns: ``- [ ] <description> [🔺|⏫|🔼] 📅 YYYY-MM-DD``
    with optional sub-bullets for time and comment.
    """
    parts = ["- [ ]", data.description]

    if data.priority and data.priority in _PRIORITY_MAP:
        parts.append(_PRIORITY_MAP[data.priority])

    if data.due_date:
        parts.append(f"📅 {data.due_date}")

    if data.time:
        parts.append(f"[time:: {data.time}]")

    line = " ".join(parts)

    # Sub-bullet for comment only (time is now inline)
    sub = []
    if data.comment:
        sub.append(f"    - {data.comment}")

    if sub:
        return line + "\n" + "\n".join(sub)
    return line


def format_comment(data: CommentData) -> str:
    """Format a free-form comment as a bullet."""
    return f"- {data.text}"
