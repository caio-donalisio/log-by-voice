"""T15 — Deterministic, descriptive RESUMO generator with file paths."""

from __future__ import annotations

from formatter.schema import Item


def generate_resumo(
    items: list[Item],
    target_files: list[str],
    undo_ids: list[str],
    warnings: list[str],
    daily_note_created: bool = False,
) -> str:
    """Generate a descriptive Portuguese summary of what was written and where.

    Returns the full ``RESUMO: ...`` line.
    """
    if not items and not warnings:
        return "RESUMO: Nenhum item processado."

    parts: list[str] = []

    for i, (item, target) in enumerate(_zip_items_files(items, target_files)):
        desc = _describe_item(item, target)
        if desc:
            uid = undo_ids[i] if i < len(undo_ids) else "?"
            parts.append(f"[{uid}] {desc}")

    if daily_note_created:
        parts.append("nota diária criada")

    if warnings:
        for w in warnings:
            parts.append(f"⚠️ {w}")

    if not parts:
        return "RESUMO: Nenhum item processado."

    return "RESUMO: " + "; ".join(parts) + "."


def _zip_items_files(
    items: list[Item],
    files: list[str],
) -> list[tuple[Item, str]]:
    """Zip items with their target files, falling back to '?' if mismatched."""
    result = []
    for i, item in enumerate(items):
        f = files[i] if i < len(files) else "?"
        result.append((item, f))
    return result


def _describe_item(item: Item, target_file: str) -> str:
    """Describe a single item in Portuguese, saying what and where."""
    d = item.data
    t = item.type
    h = item.habit
    where = _where(target_file)

    # --- habit_log ---
    if t == "habit_log" and h == "weight":
        return f"Peso {d.weight_kg}kg em {where}"

    if t == "habit_log" and h == "cardio":
        mins = f" ({d.minutes}min)" if getattr(d, 'minutes', None) else ""
        return f"{_cap(getattr(d, 'activity', 'Cardio'))}{mins} em {where}"

    if t == "habit_log" and h == "food":
        desc = getattr(d, 'description', 'refeição')
        cals = f" ({d.calories} kcal)" if getattr(d, 'calories', None) else ""
        return f"Comi {desc}{cals} em {where}"

    if t == "habit_log" and h == "expense":
        desc = getattr(d, 'description', 'gasto')
        amt = f" R${d.amount:.2f}" if getattr(d, 'amount', None) else ""
        return f"Paguei {desc}{amt} em {where}"

    if t == "habit_log" and h == "piano":
        piece = getattr(d, 'piece_hint', 'peça')
        mins = f" ({d.minutes}min)" if getattr(d, 'minutes', None) else ""
        return f"Piano: {piece}{mins} em {where}"

    if t == "habit_log" and h == "lifting":
        ex = getattr(d, 'exercise_hint', 'exercício')
        sets = f" {d.sets}x" if getattr(d, 'sets', None) else ""
        reps = str(d.reps) if getattr(d, 'reps', None) else ""
        wgt = f" @{d.weight_kg}kg" if getattr(d, 'weight_kg', None) else ""
        return f"Musculação: {ex}{sets}{reps}{wgt} em {where}"

    # --- task ---
    if t == "task":
        desc = getattr(d, 'description', 'tarefa')
        due = f" 📅 {d.due_date}" if getattr(d, 'due_date', None) else ""
        return f"Tarefa \"{desc}\"{due} em {where}"

    # --- comment ---
    if t == "comment":
        text = getattr(d, 'text', 'anotação')
        short = text[:80] + ("..." if len(text) > 80 else "")
        return f"Anotação \"{short}\" em {where}"

    # --- mark_done ---
    if t == "mark_done":
        hint = getattr(d, 'task_hint', 'tarefa')
        return f"Tarefa \"{hint}\" concluída ✅ em {where}"

    # --- correction ---
    if t == "correction":
        hint = getattr(d, 'search_hint', 'item')
        return f"Correção em \"{hint}\" em {where}"

    # --- complement ---
    if t == "complement":
        hint = getattr(d, 'search_hint', 'item')
        return f"Detalhe adicionado em \"{hint}\" em {where}"

    # --- recurring_task ---
    if t == "recurring_task":
        desc = getattr(d, 'description', 'tarefa')
        return f"Tarefa recorrente \"{desc}\" em {where}"

    # --- undo ---
    if t == "undo":
        hint = getattr(d, 'task_hint', 'tarefa')
        return f"Desfeito: \"{hint}\" em {where}"

    return ""


def _where(target_file: str) -> str:
    """Format a target file path for display."""
    if not target_file or target_file == "?":
        return "nota do dia"
    # Strip extension
    if target_file.endswith(".md"):
        target_file = target_file[:-3]
    return target_file


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else ""
