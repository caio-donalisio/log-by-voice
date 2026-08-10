"""T11 + T12 — Habit log formatters for all 6 habit types."""

from __future__ import annotations

from formatter.schema import (
    CardioData, ExpenseData, FoodData, LiftingData,
    PianoData, WeightData,
)


# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------

def format_weight(data: WeightData, time_str: str = "") -> str:
    line = f"- Me pesei [weight:: {_fmt_num(data.weight_kg)}]"
    if time_str:
        line += f" [time:: {time_str}]"
    line += " #log/fitness #fitness/weight"
    return line


# ---------------------------------------------------------------------------
# Cardio
# ---------------------------------------------------------------------------

def format_cardio(data: CardioData, date_str: str, time_str: str = "") -> str:
    activity = data.activity or "Cardio"
    line = f"- [x] Fazer {activity.capitalize()}"
    if data.minutes:
        line += f" [minutes:: {data.minutes}]"
    if time_str:
        line += f" [time:: {time_str}]"
    line += f" #habit #fitness #fitness/cardio #log/fitness 📅 {date_str} ✅ {date_str}"
    return line


# ---------------------------------------------------------------------------
# Food
# ---------------------------------------------------------------------------

def format_food(data: FoodData, time_str: str = "") -> str:
    desc = data.description
    if data.estimated and data.calories:
        desc += " (estimativa)"

    line = f"- Comi {desc}"
    if data.calories:
        line += f" [calories:: {data.calories}]"
    if data.meal:
        line += f" [meal:: {data.meal}]"
    if time_str:
        line += f" [time:: {time_str}]"
    line += " #log/fitness #fitness/calories"
    return line


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

def format_expense(data: ExpenseData, time_str: str = "") -> str:
    line = f"- Paguei {data.description}"
    if data.amount is not None:
        line += f" [amount:: {_fmt_num(data.amount)}]"
    if data.category:
        line += f" [category:: {data.category}]"
    if time_str:
        line += f" [time:: {time_str}]"
    line += " #log/finance #finance/expense"
    return line


# ---------------------------------------------------------------------------
# Piano
# ---------------------------------------------------------------------------

def format_piano(data: PianoData, resolved_piece: str | None = None, time_str: str = "") -> str:
    """Format piano log.  *resolved_piece* comes from wiki-link resolution."""
    piece = resolved_piece or data.piece_hint

    # Determine verb
    if data.action == "study":
        verb = "Estudei"
    else:
        verb = "Pratiquei"

    line = f"- {verb} [[{piece}]]"
    if data.minutes:
        line += f" [minutes:: {data.minutes}]"
    if time_str:
        line += f" [time:: {time_str}]"

    tag = "#piano/repertoire"
    if data.action == "study":
        tag = "#piano/theory"

    line += f" #log/piano {tag}"
    return line


# ---------------------------------------------------------------------------
# Lifting
# ---------------------------------------------------------------------------

def format_lifting(data: LiftingData, resolved_exercise: str | None = None, time_str: str = "") -> str:
    """Format lifting log.  *resolved_exercise* from wiki-link resolution."""
    exercise = resolved_exercise or data.exercise_hint

    line = f"- [[{exercise}]]"
    if data.weight_kg is not None:
        line += f" [weight:: {_fmt_num(data.weight_kg)}]"
    if data.reps is not None:
        line += f" [reps:: {data.reps}]"
    if data.sets is not None:
        line += f" [sets:: {data.sets}]"
    if time_str:
        line += f" [time:: {time_str}]"
    line += " #log/fitness #fitness/lifting"
    return line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_num(n: float) -> str:
    """Format number: integer if whole, one decimal otherwise."""
    if n == int(n):
        return str(int(n))
    return f"{n:.1f}"
