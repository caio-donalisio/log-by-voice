"""T10 — Task + Comment formatters.

Convert structured Item data into Obsidian markdown lines.
"""

from __future__ import annotations

from formatter.schema import CommentData, TaskData

# Priority markers
_PRIORITY_MAP = {"urgente": "🔺", "alta": "⏫", "média": "🔼"}


def format_task(data: TaskData, time_str: str = "") -> str:
    """Format a task as an Obsidian Tasks plugin checkbox line.

    *time_str* is the recording time (when the audio was sent).
    *data.time* is the deadline mentioned in the audio, if any.

    Returns: ``- [ ] <description> [🔺|⏫|🔼] [time:: HH:MM] 📅 YYYY-MM-DD``
    with optional sub-bullet for deadline and comment.
    """
    parts = ["- [ ]", data.description]

    if data.priority and data.priority in _PRIORITY_MAP:
        parts.append(_PRIORITY_MAP[data.priority])

    if time_str:
        parts.append(f"[time:: {time_str}]")

    if data.due_date:
        parts.append(f"📅 {data.due_date}")

    line = " ".join(parts)

    # Sub-bullet for deadline time (from audio) and comment
    sub = []
    if data.time:
        sub.append(f"    - Às {data.time}")
    if data.comment:
        sub.append(f"    - {data.comment}")

    if sub:
        return line + "\n" + "\n".join(sub)
    return line


def format_comment(data: CommentData) -> str:
    """Format a free-form comment as a bullet."""
    return f"- {data.text}"
