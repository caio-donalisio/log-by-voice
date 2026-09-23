"""Tests for daily-note line formatting."""
from formatter import ExpenseData, format_expense


class TestFormatExpense:
    def test_plain_description_gets_paguei_prefix(self):
        line = format_expense(ExpenseData(description="conta de luz", amount=178))
        assert line.startswith("- Paguei conta de luz [amount:: 178]")

    def test_llm_description_with_same_verb_is_not_duplicated(self):
        """LLM returned 'Paguei condomínio.' → was '- Paguei Paguei condomínio.'."""
        line = format_expense(ExpenseData(description="Paguei condomínio.", category="Moradia"))
        assert line.startswith("- Paguei condomínio [category:: Moradia]")

    def test_llm_description_with_other_verb_keeps_it(self):
        """'Abati 6 mil reais do financiamento.' must not become 'Paguei Abati ...'."""
        line = format_expense(
            ExpenseData(description="Abati 6 mil reais do financiamento.", amount=6000)
        )
        assert line.startswith("- Abati 6 mil reais do financiamento [amount:: 6000]")

    def test_leading_punctuation_is_stripped(self):
        line = format_expense(ExpenseData(description=", conta de luz, R$178"))
        assert line.startswith("- Paguei conta de luz, R$178")
