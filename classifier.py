"""
Classification orchestrator — pattern matching first, LLM as fallback.

``classify_transcript()`` is the main entry point.  It runs the pattern
engine against the transcript, then calls Claude CLI only for segments
that no pattern could handle.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from patterns import PatternRegistry
from patterns.engine import classify as pattern_classify
from patterns.weight import weight_pattern
from patterns.lifting import lifting_pattern
from patterns.piano_cardio import piano_pattern, cardio_pattern
from patterns.expense_food import expense_pattern, food_pattern
from patterns.task_correction import task_pattern, correction_pattern
from formatter.schema import validate_item

if TYPE_CHECKING:
    from formatter.schema import Item

logger = logging.getLogger(__name__)

# Prompt template for LLM fallback
_PROMPT_PATH = Path(__file__).resolve().parent / "prompt_classify.txt"

# Build the pattern registry once
_REGISTRY = PatternRegistry()
_REGISTRY.register_all([
    weight_pattern,
    lifting_pattern,
    piano_pattern,
    cardio_pattern,
    expense_pattern,
    food_pattern,
    task_pattern,
    correction_pattern,
])


def classify_transcript(
    transcript: str,
    claude_runner,
) -> tuple[list[Item], str]:
    """Classify a transcript into structured items.

    Parameters
    ----------
    transcript:
        Raw transcription text from Whisper.
    claude_runner:
        Callable ``(prompt: str) -> tuple[bool, str]`` — same signature as
        ``bot.run_claude_cli``.

    Returns
    -------
    (items, unmatched_text)
        *items* is a list of validated Items.  *unmatched_text* is the
        text that neither patterns nor LLM could classify (empty if all
        segments were handled).
    """
    # Phase 1 — Pattern matching
    raw_items, unmatched = pattern_classify(transcript, _REGISTRY)
    items = [_safe_validate(r) for r in raw_items]

    n_pattern = len(items)
    n_unmatched = len(unmatched)

    if not unmatched:
        logger.info(
            "LLM skipped: todos os %d segmentos resolvidos por pattern",
            n_pattern,
        )
        return items, ""

    logger.info(
        "Classifier: %d items por pattern, %d chars unmatched → LLM fallback",
        n_pattern, len(unmatched),
    )

    # Phase 2 — LLM fallback
    already_summary = _build_already_summary(items)
    prompt = _build_llm_prompt(unmatched, already_summary)

    success, output = claude_runner(prompt)
    if not success:
        logger.warning("LLM fallback failed: %s", output[:200])
        # Convert unmatched to a comment
        fallback = validate_item({
            "type": "comment",
            "data": {"text": f"[LLM fallback falhou] {unmatched[:300]}"},
            "_source": "fallback",
            "_confidence": 0.0,
        })
        items.append(fallback)
        return items, unmatched

    # Parse LLM JSON
    llm_items = _parse_llm_output(output)
    for raw in llm_items:
        raw["_source"] = raw.get("_source", "llm")
        raw["_confidence"] = raw.get("_confidence", 0.75)
        item = _safe_validate(raw)
        items.append(item)

    logger.info(
        "LLM fallback: %d segmentos classificados, total=%d items",
        len(llm_items), len(items),
    )

    return items, unmatched if not llm_items else ""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _safe_validate(raw: dict) -> Item:
    """Validate a raw item dict, never raising."""
    return validate_item(raw)


def _build_already_summary(items: list[Item]) -> str:
    """Build a compact summary of already-classified items for the LLM prompt."""
    if not items:
        return "(nenhum)"
    lines = []
    for item in items:
        d = item.data
        desc = ""
        if hasattr(d, 'description'):
            desc = str(d.description)[:80]
        elif hasattr(d, 'text'):
            desc = str(d.text)[:80]
        elif hasattr(d, 'exercise_hint'):
            desc = str(d.exercise_hint)[:80]
        elif hasattr(d, 'piece_hint'):
            desc = str(d.piece_hint)[:80]
        elif hasattr(d, 'activity'):
            desc = str(d.activity)[:80]
        elif hasattr(d, 'weight_kg'):
            desc = f"{d.weight_kg}kg"
        elif hasattr(d, 'task_hint'):
            desc = str(d.task_hint)[:80]
        elif hasattr(d, 'search_hint'):
            desc = str(d.search_hint)[:80]
        habit_str = f"/{item.habit}" if item.habit else ""
        lines.append(f"- {item.type}{habit_str}: {desc}")
    return "\n".join(lines)


def _build_llm_prompt(unmatched_text: str, already_summary: str) -> str:
    """Load the prompt template and fill placeholders."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.format(
        unmatched_text=unmatched_text,
        already_classified=already_summary,
    )


def _parse_llm_output(output: str) -> list[dict]:
    """Parse Claude CLI output into a list of item dicts.

    Handles:
    - JSON array at the start
    - JSON embedded in markdown fences
    - Plain text with inline JSON
    """
    # Strip markdown fences
    output = re.sub(r"^```(?:json)?\s*", "", output.strip())
    output = re.sub(r"\s*```$", "", output)

    # Find the JSON array
    # Try full parse first
    try:
        result = json.loads(output)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try to extract JSON array from within text
    m = re.search(r"\[.*\]", output, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Last resort — try to find individual objects
    items = []
    for m in re.finditer(r"\{[^{}]*\}", output):
        try:
            items.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            continue

    if items:
        return items

    return []
