"""T15 — Deterministic RESUMO generator.

Produces the ``RESUMO: ...`` line that the bot sends back to Telegram.
"""

from __future__ import annotations

from formatter.schema import Item


def generate_resumo(
    items: list[Item],
    warnings: list[str],
    daily_note_created: bool = False,
) -> str:
    """Generate a deterministic Portuguese summary of what was written.

    Returns the full ``RESUMO: ...`` line (without newline).
    """
    if not items and not warnings:
        return "RESUMO: Nenhum item processado."

    parts: list[str] = []

    # Count by category
    task_count = sum(1 for i in items if i.type == "task")
    habit_count = sum(1 for i in items if i.type == "habit_log")
    comment_count = sum(1 for i in items if i.type == "comment")
    edit_count = sum(
        1 for i in items
        if i.type in ("mark_done", "correction", "complement")
    )
    recurring_count = sum(1 for i in items if i.type == "recurring_task")

    # Build summary
    added: list[str] = []
    if task_count:
        added.append(_plural(task_count, "tarefa"))
    if habit_count:
        added.append(_plural(habit_count, "registro"))
    if comment_count:
        added.append(_plural(comment_count, "anotação"))

    if added:
        parts.append(f"{_join(added)} adicionad{_a_o(added)}")

    if edit_count:
        parts.append(f"{_plural(edit_count, 'item')} atualizado{_a_o([str(edit_count)])}")

    if recurring_count:
        parts.append(f"{_plural(recurring_count, 'tarefa recorrente')} criada")

    if daily_note_created:
        parts.append("nota diária criada")

    # Warnings
    if warnings:
        for w in warnings:
            parts.append(f"⚠️ {w}")

    summary = ", ".join(parts) if parts else "Nenhum item processado"

    # Determine the actual items count for summary
    return f"RESUMO: {summary}."


# ---------------------------------------------------------------------------
# Portuguese helpers
# ---------------------------------------------------------------------------

def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"1 {word}"
    # Simple plural — works for regular words
    if word.endswith("r"):
        return f"{n} {word}es"
    if word.endswith("ão"):
        return f"{n} {word[:-2]}ões"
    return f"{n} {word}s"


def _join(lst: list[str]) -> str:
    if len(lst) == 1:
        return lst[0]
    if len(lst) == 2:
        return f"{lst[0]} e {lst[1]}"
    return ", ".join(lst[:-1]) + f" e {lst[-1]}"


def _a_o(lst: list[str]) -> str:
    """Feminine/plural ending for adjectives."""
    # Simplification: if all are feminine plural, use "as"; else "os"
    return "os"
