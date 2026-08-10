"""P5 — Expense log + P6 — Food log."""

from __future__ import annotations

import re

from patterns import Pattern


# ---------------------------------------------------------------------------
# P5 — Expense
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = {
    "mercado", "restaurantes", "moradia", "saúde", "saude",
    "transporte", "educação", "educacao", "lazer", "pets", "negócio", "negocio",
    "outros",
}

_CATEGORY_MAP = {
    "saude": "Saúde", "educacao": "Educação", "negocio": "Negócio",
}


def _build_expense(match, text: str) -> dict:
    data: dict = {}

    # Amount — try "X reais e Y centavos" first, then simple "X reais"
    amount = None
    reais_centavos = re.search(
        r"(?P<reais>\d+)\s*reais?\s*e\s*(?P<cents>\d+)\s*centavos?",
        text,
    )
    if reais_centavos:
        amount = float(reais_centavos.group("reais")) + float(reais_centavos.group("cents")) / 100
    else:
        m = re.search(
            r"(?:R\$\s*)?(?P<amount>\d+(?:[.,]\d+)?)\s*(?:reais|real|conto|pila|pilas|R\$)?",
            text,
        )
        if m:
            amount = float(m.group("amount").replace(",", "."))
    if amount is not None:
        data["amount"] = amount

    # Description — clean verbs and filler words, keep the product name
    desc = text
    desc = re.sub(
        r"\b(?:paguei|comprei|gastei|pagar|comprar|gastar|gastou|comprei|pagou|comprou)\b",
        "", desc, flags=re.IGNORECASE,
    )
    desc = re.sub(r"\b(?:hoje|eu|um|uma|uns|umas)\b", "", desc, flags=re.IGNORECASE)
    # Remove amount-related text
    desc = re.sub(r"\d+\s*reais?\s*e\s*\d+\s*centavos?", "", desc)
    desc = re.sub(r"\d+(?:[.,]\d+)?\s*(?:reais|real|conto|pila|pilas|centavos)", "", desc)
    desc = re.sub(r"\s+(?:por|—|–|-)\s*", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip().rstrip(".")
    if not desc:
        desc = text.strip().rstrip(".")
    data["description"] = desc

    # Category — only if explicitly mentioned
    for cat in _VALID_CATEGORIES:
        cat_re = re.compile(rf"\b{cat}\b", re.IGNORECASE)
        if cat_re.search(text):
            mapped = _CATEGORY_MAP.get(cat, cat.title())
            data["category"] = mapped
            break

    return {
        "type": "habit_log",
        "habit": "expense",
        "data": data,
    }


def _adjust_expense_confidence(item: dict, base: float) -> float:
    """Lower confidence when no amount was extracted."""
    amount = item.get("data", {}).get("amount")
    if amount is None:
        return base * 0.60  # 0.85 * 0.60 = 0.51 → below threshold → LLM
    return base


expense_pattern = Pattern(
    name="expense_log",
    category="habit_log",
    habit="expense",
    triggers=[
        r"\bpaguei\b", r"\bcomprei\b", r"\bgastei\b",
        r"\bpagar\b", r"\bcomprar\b", r"\bgastar\b",
        r"\b(?:pagou|comprou|gastou)\b",
    ],
    regex=r".*",
    confidence=0.85,
    build_item=_build_expense,
    required_fields=[],
    adjust_confidence=_adjust_expense_confidence,
)


# ---------------------------------------------------------------------------
# P6 — Food
# ---------------------------------------------------------------------------

_MEAL_MAP = {
    "café da manhã": "café da manhã", "café": "café da manhã",
    "cafe da manha": "café da manhã", "cafe": "café da manhã",
    "almocei": "almoço", "almoço": "almoço", "almoco": "almoço",
    "almoçar": "almoço", "almocar": "almoço",
    "lanchei": "lanche", "lanche": "lanche",
    "jantei": "jantar", "jantar": "jantar",
    "jante": "jantar",
}


def _infer_meal(text: str) -> str | None:
    """Infer meal from verb or time-of-day keywords."""
    text_lower = text.lower()
    for keyword, meal in _MEAL_MAP.items():
        if keyword in text_lower:
            return meal
    return None


def _build_food(match, text: str) -> dict:
    data: dict = {}

    # Calories — explicit number only
    m = re.search(r"(?P<cal>\d+)\s*(?:calorias|cal|kcal)", text)
    if m:
        data["calories"] = int(m.group("cal"))
        data["estimated"] = False
    else:
        data["estimated"] = True

    # Description — clean the text
    desc = text
    # Remove verbs
    desc = re.sub(
        r"\b(?:comi|almocei|jantei|lanchei|comer|almocar|almoçar|jantar|lanchar|tomei|tomar|comemos|comeram)\b",
        "", desc, flags=re.IGNORECASE,
    )
    # Remove filler prefix words
    desc = re.sub(
        r"\b(?:hoje|eu|um|uma|uns|umas)\b",
        "", desc, flags=re.IGNORECASE,
    )
    desc = re.sub(r"\d+\s*(?:calorias|cal|kcal)", "", desc)
    # Collapse whitespace
    desc = re.sub(r"\s+", " ", desc).strip().rstrip(".")
    if not desc:
        desc = text.strip().rstrip(".")
    data["description"] = desc

    # Meal inference
    meal = _infer_meal(text)
    if meal:
        data["meal"] = meal

    return {
        "type": "habit_log",
        "habit": "food",
        "data": data,
    }


food_pattern = Pattern(
    name="food_log",
    category="habit_log",
    habit="food",
    triggers=[
        r"\bcomi\b", r"\balmocei\b", r"\bjantei\b", r"\blanchei\b",
        r"\btomei\b", r"\btomar\b",
        r"\bcomer\b", r"\balmo[cç]ar\b", r"\bjantar\b", r"\blanchar\b",
        r"\bcafé\s+da\s+manh[ãa]\b", r"\balmo[cç]o\b", r"\bjantar\b",
        r"\bcaneca\s+de\b",  # "caneca de café/chá/etc"
    ],
    regex=r".*",
    confidence=0.80,
    build_item=_build_food,
    required_fields=["description"],
)
