"""Unit tests for schema validation (T1)."""
import pytest
from formatter import (
    WeightData, TaskData, ExpenseData, FoodData,
    LiftingData, CommentData, validate_item,
)


class TestSchemaValidation:
    def test_valid_weight(self):
        item = validate_item({
            "type": "habit_log", "habit": "weight",
            "data": {"weight_kg": 82.5},
        })
        assert item.type == "habit_log"
        assert item.habit == "weight"
        assert isinstance(item.data, WeightData)
        assert item.data.weight_kg == 82.5

    def test_valid_task(self):
        item = validate_item({
            "type": "task",
            "data": {
                "description": "Comprar conduíte",
                "priority": "média",
                "due_date": "2026-08-15",
                "time": "14:30",
            },
        })
        assert item.type == "task"
        assert isinstance(item.data, TaskData)
        assert item.data.priority == "média"

    def test_invalid_type_falls_back_to_comment(self):
        item = validate_item({"type": "nonexistent", "data": {}})
        assert item.type == "comment"
        assert "fallback" in item.data.text

    def test_invalid_date_becomes_none(self):
        item = validate_item({
            "type": "task",
            "data": {"description": "X", "due_date": "not a date"},
        })
        assert item.data.due_date is None

    def test_expense_invalid_category_stripped(self):
        item = validate_item({
            "type": "habit_log", "habit": "expense",
            "data": {"description": "Test", "amount": 50, "category": "FakeCategory"},
        })
        assert item.data.category is None

    def test_expense_valid_category_preserved(self):
        item = validate_item({
            "type": "habit_log", "habit": "expense",
            "data": {"description": "Mercado", "amount": 50, "category": "Mercado"},
        })
        assert item.data.category == "Mercado"

    def test_all_six_habit_types(self):
        for h in ["weight", "piano", "lifting", "cardio", "food", "expense"]:
            item = validate_item({"type": "habit_log", "habit": h, "data": {}})
            assert item.habit == h

    def test_food_estimated_flag(self):
        item = validate_item({
            "type": "habit_log", "habit": "food",
            "data": {"description": "arroz", "calories": 550, "estimated": True},
        })
        assert item.data.estimated is True

    def test_lifting_partial_data(self):
        item = validate_item({
            "type": "habit_log", "habit": "lifting",
            "data": {"exercise_hint": "Supino Reto", "sets": 3, "reps": 10},
        })
        assert item.data.sets == 3
        assert item.data.weight_kg is None

    def test_empty_data_still_validates(self):
        for t in ["task", "comment", "mark_done", "correction", "complement", "recurring_task"]:
            item = validate_item({"type": t, "data": {}})
            assert item.type == t
