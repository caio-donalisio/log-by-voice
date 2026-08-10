"""T12 — Wiki-link resolver for piano pieces and fitness exercises."""

from __future__ import annotations

import logging
from pathlib import Path

from patterns import normalize

logger = logging.getLogger(__name__)

# Directories to search for wiki-link resolution
_PIANO_DIRS = ["70 Piano"]
_FITNESS_EXERCISE_DIRS = ["100 Fitness/Exercícios"]


def resolve_piece(hint: str, vault_dir: Path) -> tuple[str, float]:
    """Find the closest matching piano piece note name.

    Returns ``(note_name, score)`` where score is 0.0–1.0.
    Score < 1.0 means the match is fuzzy.
    """
    return _find_best_match(hint, vault_dir, _PIANO_DIRS)


def resolve_exercise(hint: str, vault_dir: Path) -> tuple[str, float]:
    """Find the closest matching fitness exercise note name."""
    return _find_best_match(hint, vault_dir, _FITNESS_EXERCISE_DIRS)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _find_best_match(
    hint: str,
    vault_dir: Path,
    search_dirs: list[str],
) -> tuple[str, float]:
    """Search *search_dirs* for .md files whose stem matches *hint*."""
    norm_hint = normalize(hint)
    if not norm_hint:
        return hint, 0.0

    candidates: list[tuple[str, str, float]] = []  # (filename_stem, norm_stem, score)

    for dir_name in search_dirs:
        search_path = vault_dir / dir_name
        if not search_path.is_dir():
            continue
        for md_file in search_path.rglob("*.md"):
            stem = md_file.stem
            norm_stem = normalize(stem)
            if not norm_stem:
                continue

            score = _score_match(norm_hint, norm_stem)
            if score > 0.3:  # Minimum threshold
                candidates.append((stem, norm_stem, score))

    if not candidates:
        return hint, 0.0

    # Best match
    candidates.sort(key=lambda c: c[2], reverse=True)
    best_stem, _, best_score = candidates[0]

    return best_stem, best_score


def _score_match(query: str, candidate: str) -> float:
    """Score how well *query* matches *candidate* (both normalized)."""
    # Exact match
    if query == candidate:
        return 1.0
    # Candidate contains query
    if query in candidate:
        return 0.90
    # Query contains candidate
    if candidate in query:
        return 0.85
    # Token overlap
    query_tokens = set(query.split())
    cand_tokens = set(candidate.split())
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens & cand_tokens) / len(query_tokens)
    return overlap * 0.70
