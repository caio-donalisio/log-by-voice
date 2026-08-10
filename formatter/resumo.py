"""T15 — Deterministic, descriptive RESUMO generator."""

from __future__ import annotations

from formatter.schema import Item


def generate_resumo(
    items: list[Item],
    warnings: list[str],
    daily_note_created: bool = False,
) -> str:
    """Generate a descriptive Portuguese summary of what was written and where.

    Returns the full ``RESUMO: ...`` line.
    """
    if not items and not warnings:
        return "RESUMO: Nenhum item processado."

    parts: list[str] = []

    for item in items:
        desc = _describe_item(item)
        if desc:
            parts.append(desc)

    if daily_note_created:
        parts.append("nota diária criada")

    if warnings:
        for w in warnings:
            parts.append(f"⚠️ {w}")

    if not parts:
        return "RESUMO: Nenhum item processado."

    return "RESUMO: " + "; ".join(parts) + "."


def _describe_item(item: Item) -> str:
    """Describe a single item in Portuguese, saying what and where."""
    d = item.data
    t = item.type
    h = item.habit

    # --- habit_log ---
    if t == "habit_log" and h == "weight":
        return f"Peso {d.weight_kg}kg registrado em 📓 Anotações"

    if t == "habit_log" and h == "cardio":
        mins = f" ({d.minutes}min)" if getattr(d, 'minutes', None) else ""
        return f"{_cap(getattr(d, 'activity', 'Cardio'))}{mins} registrado em 📓 Anotações"

    if t == "habit_log" and h == "food":
        desc = getattr(d, 'description', 'refeição')
        cals = f" ({d.calories} kcal)" if getattr(d, 'calories', None) else ""
        return f"Comi {desc}{cals} → 📓 Anotações"

    if t == "habit_log" and h == "expense":
        desc = getattr(d, 'description', 'gasto')
        amt = f" R${d.amount:.2f}" if getattr(d, 'amount', None) else ""
        return f"Paguei {desc}{amt} → 📓 Anotações"

    if t == "habit_log" and h == "piano":
        piece = getattr(d, 'piece_hint', 'peça')
        mins = f" ({d.minutes}min)" if getattr(d, 'minutes', None) else ""
        return f"Piano: {piece}{mins} → 📓 Anotações"

    if t == "habit_log" and h == "lifting":
        ex = getattr(d, 'exercise_hint', 'exercício')
        sets = f" {d.sets}x" if getattr(d, 'sets', None) else ""
        reps = str(d.reps) if getattr(d, 'reps', None) else ""
        wgt = f" @{d.weight_kg}kg" if getattr(d, 'weight_kg', None) else ""
        return f"Musculação: {ex}{sets}{reps}{wgt} → 📓 Anotações"

    # --- task ---
    if t == "task":
        desc = getattr(d, 'description', 'tarefa')
        due = f" 📅 {d.due_date}" if getattr(d, 'due_date', None) else ""
        return f"Tarefa \"{desc}\"{due} → ✅ Tarefas Registradas"

    # --- comment ---
    if t == "comment":
        text = getattr(d, 'text', 'anotação')
        short = text[:80] + ("..." if len(text) > 80 else "")
        return f"Anotação \"{short}\" → 📓 Anotações"

    # --- mark_done ---
    if t == "mark_done":
        hint = getattr(d, 'task_hint', 'tarefa')
        return f"Tarefa \"{hint}\" marcada como concluída ✅"

    # --- correction ---
    if t == "correction":
        hint = getattr(d, 'search_hint', 'item')
        return f"Correção em \"{hint}\" aplicada"

    # --- complement ---
    if t == "complement":
        hint = getattr(d, 'search_hint', 'item')
        return f"Detalhe adicionado em \"{hint}\""

    # --- recurring_task ---
    if t == "recurring_task":
        desc = getattr(d, 'description', 'tarefa')
        return f"Tarefa recorrente \"{desc}\" → Tarefas Recorrentes"

    return ""


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else ""
