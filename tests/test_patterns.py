"""Regression tests for pattern matching against real transcripts (T20)."""
from patterns import PatternRegistry
from patterns.engine import classify
from patterns.weight import weight_pattern
from patterns.lifting import lifting_pattern
from patterns.piano_cardio import piano_pattern, cardio_pattern
from patterns.expense_food import expense_pattern, food_pattern
from patterns.task_correction import task_pattern, correction_pattern
from patterns.mark_done import mark_done_pattern


def _registry():
    r = PatternRegistry()
    r.register_all([
        weight_pattern, lifting_pattern, piano_pattern, cardio_pattern,
        expense_pattern, food_pattern, task_pattern, correction_pattern,
        mark_done_pattern,
    ])
    return r


class TestPatternMatching:
    """Each test checks that a real transcript gets the correct classification."""

    def test_weight(self):
        items, unmatched = classify("me pesei 82 quilos hoje", _registry())
        assert len(items) == 1
        assert items[0]["type"] == "habit_log"
        assert items[0]["habit"] == "weight"
        assert items[0]["data"]["weight_kg"] == 82.0
        assert unmatched == ""

    def test_cardio(self):
        items, unmatched = classify("Hoje fiz 30 minutos de bicicleta.", _registry())
        assert len(items) == 1
        assert items[0]["habit"] == "cardio"
        assert unmatched == ""

    def test_lifting(self):
        items, unmatched = classify(
            "Fiz três séries de 10 de 15 quilos de supino reto.",
            _registry(),
        )
        assert len(items) == 1
        assert items[0]["habit"] == "lifting"

    def test_food(self):
        items, unmatched = classify(
            "Hoje eu comi um baião de 2.",
            _registry(),
        )
        assert len(items) == 1
        assert items[0]["habit"] == "food"

    def test_expense_with_amount(self):
        items, unmatched = classify(
            "Comprei uma saia vermelha da Renner por 80 reais e 30 centavos.",
            _registry(),
        )
        assert len(items) == 1
        assert items[0]["habit"] == "expense"
        assert items[0]["data"]["amount"] == 80.30

    def test_expense_without_amount_goes_to_llm(self):
        """Paguei without a number should NOT match as expense (low confidence)."""
        items, unmatched = classify("Paguei condomínio.", _registry())
        # No pattern match — goes unmatched → LLM fallback
        assert len(items) == 0
        assert "condomínio" in unmatched

    def test_task(self):
        items, unmatched = classify(
            "Registre tarefa de ir no meu pai no dia dos pais neste domingo.",
            _registry(),
        )
        assert len(items) == 1
        assert items[0]["type"] == "task"

    def test_correction(self):
        items, unmatched = classify(
            "Corrija comprar fralda da Sofia para chá de fralda da Sofia.",
            _registry(),
        )
        assert len(items) == 1
        assert items[0]["type"] == "correction"

    def test_mark_done(self):
        items, unmatched = classify(
            "já paguei a conta de luz.",
            _registry(),
        )
        assert len(items) == 1
        assert items[0]["type"] == "mark_done"

    def test_comment_goes_unmatched(self):
        """Free-form thoughts should not match any pattern."""
        items, unmatched = classify(
            "Hoje eu assisti o jogo do São Paulo contra Santos, foi 3x1.",
            _registry(),
        )
        assert len(items) == 0  # Should go to LLM
        assert "São Paulo" in unmatched

    def test_multiple_items_in_single_transcript(self):
        items, unmatched = classify(
            "me pesei 82 quilos hoje. fiz 30 minutos de bicicleta. registra tarefa de comprar pão.",
            _registry(),
        )
        assert len(items) == 3
        assert unmatched == ""  # All matched by patterns

    def test_anti_trigger_negation(self):
        """Não preciso should NOT create a task."""
        items, unmatched = classify(
            "não preciso comprar nada.",
            _registry(),
        )
        assert len(items) == 0
