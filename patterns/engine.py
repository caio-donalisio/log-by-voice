"""
Pattern matching engine — segmentation, matching loop, confidence scoring.

The core of the "pattern-first" classification pipeline.  ``classify()`` is the
main entry point.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from patterns import Pattern, PatternRegistry, clean_segment, normalize

if TYPE_CHECKING:
    from formatter.schema import Item

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE = 0.80    # Use item directly, no LLM needed
AMBIGUITY_GAP = 0.20      # If top-2 scores differ by less than this → ambiguous


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

# Split on sentence-ending punctuation followed by space, or on newlines
_SEGMENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def segment_transcript(text: str) -> list[str]:
    """Split transcript text into sentence-level segments.

    Returns non-empty segments with whitespace trimmed.
    """
    raw = _SEGMENT_SPLIT_RE.split(text)
    segments = [s.strip() for s in raw if s.strip()]
    # If nothing matched the split pattern, treat whole text as one segment
    if not segments and text.strip():
        segments = [text.strip()]
    return segments


# ---------------------------------------------------------------------------
# Anti-trigger detection
# ---------------------------------------------------------------------------

# Patterns that negate an otherwise-matching trigger
_ANTI_TRIGGERS = [
    re.compile(r"\bnão\s+(?:preciso|tenho\s+que|precisa|vou|quero)\b", re.IGNORECASE),
    re.compile(r"\b(?:não|nem)\s+(?:é|era|foi|seria)\s+(?:uma?\s+)?(?:tarefa|lembrete)\b", re.IGNORECASE),
]


def _has_anti_trigger(text: str) -> bool:
    """Return True if the text contains a negation that voids any match."""
    return any(at.search(text) for at in _ANTI_TRIGGERS)


# ---------------------------------------------------------------------------
# Single-segment matching
# ---------------------------------------------------------------------------

def match_segment(
    segment: str,
    registry: PatternRegistry,
) -> tuple[dict | None, float, str]:
    """Try all patterns against *segment*.

    Returns ``(item_dict, confidence, pattern_name)`` on success, or
    ``(None, 0.0, "")`` if no pattern matched with sufficient confidence.
    """
    cleaned = clean_segment(segment)
    # Also strip trailing punctuation for cleaner regex matching
    cleaned_for_re = re.sub(r"[.!?]+$", "", cleaned).strip()

    if _has_anti_trigger(cleaned):
        logger.debug("Anti-trigger matched in segment: %s", cleaned[:80])
        return None, 0.0, ""

    candidates: list[tuple[dict, float, str]] = []

    for pattern in registry.patterns:
        # Phase 1 — trigger check (on the original cleaned text)
        trigger_hit = any(
            trigger.search(cleaned) for trigger in pattern._trigger_res
        )
        if not trigger_hit:
            continue

        # Phase 2 — extraction (on punctuation-stripped text)
        m = pattern._extraction_re.search(cleaned_for_re) if pattern._extraction_re else None
        if m is None:
            # Retry on original cleaned text
            m = pattern._extraction_re.search(cleaned) if pattern._extraction_re else None
        if m is None:
            continue

        # Phase 3 — build item (may return None if extraction fails)
        try:
            item_dict = pattern.build_item(m, cleaned)
        except Exception:
            logger.debug(
                "Pattern %s build_item raised", pattern.name, exc_info=True,
            )
            continue

        if item_dict is None:
            continue

        # Phase 4 — required fields (checked in the output data dict)
        if pattern.required_fields:
            item_data = item_dict.get("data", {})
            missing = [
                f for f in pattern.required_fields
                if f not in item_data or item_data[f] is None
            ]
            if missing:
                logger.debug(
                    "Pattern %s matched but missing data fields: %s",
                    pattern.name, missing,
                )
                continue

        # Adjust confidence based on extraction completeness
        confidence = pattern.confidence
        # If regex captured all named groups, confidence stays; otherwise drop
        if pattern._extraction_re:
            all_groups = {
                name for name, _ in pattern._extraction_re.groupindex.items()
            }
            captured = {name for name in all_groups if m.group(name) is not None}
            if len(captured) < len(all_groups):
                confidence *= 0.80  # partial extraction → lower confidence

        # Allow pattern to further adjust confidence (e.g. expense without amount)
        if pattern.adjust_confidence:
            confidence = pattern.adjust_confidence(item_dict, confidence)

        candidates.append((item_dict, confidence, pattern.name))

    if not candidates:
        return None, 0.0, ""

    # Sort by confidence descending
    candidates.sort(key=lambda c: c[1], reverse=True)
    best_dict, best_conf, best_name = candidates[0]

    # Low confidence → unmatched
    if best_conf < HIGH_CONFIDENCE:
        logger.debug(
            "Best match %s below threshold (%.2f < %.2f)",
            best_name, best_conf, HIGH_CONFIDENCE,
        )
        return None, 0.0, ""

    # Ambiguity check: if top 2 are too close, send to LLM
    if len(candidates) >= 2:
        second_conf = candidates[1][1]
        gap = best_conf - second_conf
        if gap < AMBIGUITY_GAP:
            logger.debug(
                "Ambiguous: %s=%.2f vs %s=%.2f (gap=%.2f < %.2f)",
                best_name, best_conf, candidates[1][2], second_conf,
                gap, AMBIGUITY_GAP,
            )
            return None, 0.0, ""

    # Stamp source metadata
    best_dict["_source"] = f"pattern:{best_name}"
    best_dict["_confidence"] = best_conf

    return best_dict, best_conf, best_name


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def classify(
    transcript: str,
    registry: PatternRegistry,
) -> tuple[list[dict], str]:
    """Classify a full transcript.

    Returns ``(items, unmatched_text)`` where *items* is a list of raw dicts
    (ready for ``formatter.schema.validate_item``) and *unmatched_text* is
    the concatenation of all segments that no pattern could handle.
    """
    segments = segment_transcript(transcript)
    if not segments:
        return [], ""

    items: list[dict] = []
    unmatched_parts: list[str] = []

    for seg in segments:
        item_dict, conf, name = match_segment(seg, registry)

        if item_dict is not None:
            items.append(item_dict)
            logger.info(
                "Pattern match: %s (confidence=%.2f, source=\"%s\")",
                name, conf, seg[:60],
            )
        else:
            unmatched_parts.append(seg)

    unmatched_text = " ".join(unmatched_parts).strip()

    return items, unmatched_text
