"""
JSON item schema and validation for the classification pipeline.

Both the pattern matcher and the LLM fallback produce items in this format.
Validation never raises — invalid items become comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ItemType = Literal[
    "task", "habit_log", "comment", "mark_done",
    "correction", "complement", "recurring_task", "undo",
]

HabitType = Literal["weight", "piano", "lifting", "cardio", "food", "expense"]

Priority = Literal["urgente", "alta", "média"]  # 🔺 ⏫ 🔼

MealType = Literal["café da manhã", "almoço", "lanche", "jantar"]

ExpenseCategory = Literal[
    "Mercado", "Restaurantes", "Moradia", "Saúde",
    "Transporte", "Educação", "Lazer", "Pets", "Negócio", "Outros",
]


# ---------------------------------------------------------------------------
# Data classes — one per item "data" payload
# ---------------------------------------------------------------------------

@dataclass
class TaskData:
    description: str
    priority: Priority | None = None
    due_date: str | None = None   # YYYY-MM-DD
    time: str | None = None       # HH:MM
    comment: str | None = None


@dataclass
class WeightData:
    weight_kg: float


@dataclass
class PianoData:
    piece_hint: str
    minutes: int | None = None
    action: Literal["practice", "study"] | None = None


@dataclass
class LiftingData:
    exercise_hint: str
    weight_kg: float | None = None
    reps: int | None = None
    sets: int | None = None


@dataclass
class CardioData:
    activity: str
    minutes: int | None = None


@dataclass
class FoodData:
    description: str
    calories: int | None = None
    estimated: bool = False
    meal: MealType | None = None


@dataclass
class ExpenseData:
    description: str
    amount: float | None = None   # None = sem valor dito → LLM decide se é expense ou comment
    category: ExpenseCategory | None = None


@dataclass
class CommentData:
    text: str


@dataclass
class MarkDoneData:
    task_hint: str
    comment: str | None = None
    is_recurring: bool = False


@dataclass
class CorrectionData:
    search_hint: str
    new_field: str
    new_value: str
    search_scope: Literal["today", "recent"] = "today"


@dataclass
class ComplementData:
    search_hint: str
    detail: str


@dataclass
class RecurringTaskData:
    description: str
    frequency: str              # "every month", "every week", "every 4 months when done", etc.
    due_day: int | None = None   # dia do mês, se aplicável
    is_payment: bool = False
    priority: Priority | None = None
    due_date: str | None = None  # YYYY-MM-DD, primeiro vencimento


# ---------------------------------------------------------------------------
# Item — the unified output of classification
# ---------------------------------------------------------------------------

@dataclass
class Item:
    type: ItemType
    data: (
        TaskData | WeightData | PianoData | LiftingData | CardioData |
        FoodData | ExpenseData | CommentData | MarkDoneData |
        CorrectionData | ComplementData | RecurringTaskData
    )
    habit: HabitType | None = None     # set only for habit_log
    source: str = ""                    # "pattern:weight_log" or "llm"
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_EXPENSE_CATEGORIES: set[str] = {
    "Mercado", "Restaurantes", "Moradia", "Saúde",
    "Transporte", "Educação", "Lazer", "Pets", "Negócio", "Outros",
}


def validate_item(raw: dict) -> Item:
    """Validate a raw dict from pattern matching or LLM output.

    Returns an Item on success.  On *any* validation failure, returns a
    ``comment`` Item carrying the original text so nothing is lost.
    """
    try:
        item_type = raw.get("type", "")
        data = raw.get("data", {})
        habit = raw.get("habit")
        source = raw.get("_source", raw.get("source", ""))
        confidence = float(raw.get("_confidence", raw.get("confidence", 0)))

        if item_type not in _VALID_TYPES:
            return _fallback_comment(raw, source, f"Unknown type: {item_type}")

        if item_type == "habit_log":
            if habit not in _VALID_HABITS:
                return _fallback_comment(raw, source, f"Unknown habit: {habit}")
            validated_data = _validate_habit_data(habit, data)

        elif item_type == "task":
            validated_data = TaskData(
                description=str(data.get("description", "")),
                priority=_optional_priority(data.get("priority")),
                due_date=_optional_date(data.get("due_date")),
                time=_optional_time(data.get("time")),
                comment=_optional_str(data.get("comment")),
            )
        elif item_type == "comment":
            validated_data = CommentData(text=str(data.get("text", "")))
        elif item_type == "mark_done":
            validated_data = MarkDoneData(
                task_hint=str(data.get("task_hint", "")),
                comment=_optional_str(data.get("comment")),
                is_recurring=bool(data.get("is_recurring", False)),
            )
        elif item_type == "correction":
            validated_data = CorrectionData(
                search_hint=str(data.get("search_hint", "")),
                new_field=str(data.get("new_field", "")),
                new_value=str(data.get("new_value", "")),
                search_scope=data.get("search_scope", "today"),
            )
        elif item_type == "complement":
            validated_data = ComplementData(
                search_hint=str(data.get("search_hint", "")),
                detail=str(data.get("detail", "")),
            )
        elif item_type == "undo":
            validated_data = MarkDoneData(  # Reuse — just needs task_hint
                task_hint=str(data.get("task_hint", "")),
            )
        elif item_type == "recurring_task":
            validated_data = RecurringTaskData(
                description=str(data.get("description", "")),
                frequency=str(data.get("frequency", "")),
                due_day=_optional_int(data.get("due_day")),
                is_payment=bool(data.get("is_payment", False)),
                priority=_optional_priority(data.get("priority")),
                due_date=_optional_date(data.get("due_date")),
            )

        return Item(
            type=item_type,
            data=validated_data,
            habit=habit,
            source=source,
            confidence=confidence,
        )

    except Exception:
        return _fallback_comment(raw, raw.get("_source", ""), "Validation exception")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_TYPES: set[str] = {
    "task", "habit_log", "comment", "mark_done",
    "correction", "complement", "recurring_task", "undo",
}

_VALID_HABITS: set[str] = {
    "weight", "piano", "lifting", "cardio", "food", "expense",
}


def _validate_habit_data(habit: str, data: dict):
    """Route to the correct habit data class."""
    if habit == "weight":
        return WeightData(weight_kg=float(data.get("weight_kg", 0)))
    elif habit == "piano":
        return PianoData(
            piece_hint=str(data.get("piece_hint", "")),
            minutes=_optional_int(data.get("minutes")),
            action=data.get("action"),
        )
    elif habit == "lifting":
        return LiftingData(
            exercise_hint=str(data.get("exercise_hint", "")),
            weight_kg=_optional_float(data.get("weight_kg")),
            reps=_optional_int(data.get("reps")),
            sets=_optional_int(data.get("sets")),
        )
    elif habit == "cardio":
        return CardioData(
            activity=str(data.get("activity", "")),
            minutes=_optional_int(data.get("minutes")),
        )
    elif habit == "food":
        return FoodData(
            description=str(data.get("description", "")),
            calories=_optional_int(data.get("calories")),
            estimated=bool(data.get("estimated", False)),
            meal=data.get("meal"),
        )
    elif habit == "expense":
        amount = _optional_float(data.get("amount"))
        category = data.get("category")
        if category is not None and category not in _VALID_EXPENSE_CATEGORIES:
            category = None
        return ExpenseData(
            description=str(data.get("description", "")),
            amount=amount,
            category=category,
        )
    return CommentData(text=str(data))


def _fallback_comment(raw: dict, source: str, reason: str) -> Item:
    """Convert a broken item into a safe comment."""
    text = str(raw.get("data", raw))
    if len(text) > 500:
        text = text[:500]
    return Item(
        type="comment",
        data=CommentData(text=f"[fallback: {reason}] {text}"),
        source=source,
        confidence=0.0,
    )


def _optional_str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _optional_priority(value) -> Priority | None:
    if value in ("urgente", "alta", "média"):
        return value
    return None


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _optional_date(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if _DATE_RE.match(s) else None


_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _optional_time(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if _TIME_RE.match(s) else None
