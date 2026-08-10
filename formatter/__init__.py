"""Formatter package — deterministic markdown generation from structured items."""

from formatter.schema import (
    CardioData,
    CommentData,
    ComplementData,
    CorrectionData,
    ExpenseData,
    FoodData,
    Item,
    LiftingData,
    MarkDoneData,
    PianoData,
    RecurringTaskData,
    TaskData,
    WeightData,
    validate_item,
)
from formatter.daily_note import (
    append_to_section,
    ensure_daily_note,
    read_file_lines,
    write_file_lines,
)
from formatter.task import format_comment, format_task
from formatter.habit_log import (
    format_cardio,
    format_expense,
    format_food,
    format_lifting,
    format_piano,
    format_weight,
)
from formatter.edits import find_and_correct, find_and_complement, find_and_mark_done
from formatter.recurring import format_recurring
from formatter.resumo import generate_resumo
from formatter.wiki_resolver import resolve_exercise, resolve_piece

__all__ = [
    # Schema
    "Item",
    "TaskData",
    "WeightData",
    "PianoData",
    "LiftingData",
    "CardioData",
    "FoodData",
    "ExpenseData",
    "CommentData",
    "MarkDoneData",
    "CorrectionData",
    "ComplementData",
    "RecurringTaskData",
    "validate_item",
    # Daily note
    "ensure_daily_note",
    "append_to_section",
    "read_file_lines",
    "write_file_lines",
    # Formatters
    "format_task",
    "format_comment",
    "format_weight",
    "format_cardio",
    "format_food",
    "format_expense",
    "format_piano",
    "format_lifting",
    # Edits
    "find_and_mark_done",
    "find_and_correct",
    "find_and_complement",
    # Recurring
    "format_recurring",
    # RESUMO
    "generate_resumo",
    # Wiki resolver
    "resolve_piece",
    "resolve_exercise",
]
