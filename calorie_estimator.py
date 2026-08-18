"""Calorie estimation via LLM — minimal prompt, single-purpose call."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_CALORIE_SYSTEM = """\
Você é um estimador de calorias. Dada uma lista de refeições, retorne APENAS
um objeto JSON mapeando o índice (número) para calorias estimadas (inteiro).
Sem texto antes ou depois. Exemplo: {"0": 550, "1": 120}"""

_CALORIE_PROMPT = """\
Estime as calorias (kcal) de cada item:

{items}

JSON:"""


def estimate_calories(
    food_items: list[tuple[int, str]],
    llm_runner,
) -> dict[int, int]:
    """Estimate calories for food descriptions via LLM.

    Args:
        food_items: List of (index, description) tuples.
        llm_runner: ``(prompt: str, system_prompt: str = "") -> tuple[bool, str]``

    Returns:
        Dict mapping index → estimated_calories.  Empty dict on failure.
    """
    if not food_items:
        return {}

    # Build prompt
    items_text = "\n".join(
        f"{i}. {desc}" for i, desc in food_items
    )
    prompt = _CALORIE_PROMPT.format(items=items_text)

    success, output = llm_runner(prompt, system_prompt=_CALORIE_SYSTEM)
    if not success:
        logger.warning("Calorie estimation failed: %s", output[:200])
        return {}

    return _parse_calorie_response(output)


def _parse_calorie_response(output: str) -> dict[int, int]:
    """Parse LLM calorie response into {index: calories}."""
    # Strip markdown
    output = re.sub(r"^```(?:json)?\s*", "", output.strip())
    output = re.sub(r"\s*```$", "", output)

    # Try direct JSON parse
    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        # Try to extract JSON object from text
        m = re.search(r"\{[^}]+\}", output, re.DOTALL)
        if m:
            try:
                raw = json.loads(m.group(0))
            except json.JSONDecodeError:
                return {}
        else:
            return {}

    # Convert string keys to int, validate values
    result: dict[int, int] = {}
    for key, value in raw.items():
        try:
            idx = int(key)
            cals = int(value)
            if 0 < cals < 5000:  # Sanity check
                result[idx] = cals
        except (ValueError, TypeError):
            continue

    return result
