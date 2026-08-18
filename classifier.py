"""Classification orchestrator — pattern matching first, LLM as fallback."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from patterns import classify as pattern_classify, default_registry
from formatter import validate_item

if TYPE_CHECKING:
    from formatter import Item

logger = logging.getLogger(__name__)
_PROMPT_PATH = Path(__file__).resolve().parent / "prompt_classify.txt"
_REGISTRY = default_registry()

# Trigger phrases that force full-LLM mode (bypass patterns)
_FORCE_LLM_RE = re.compile(
    r"\b(?:modo\s+IA|for[çc]a\s+(?:a\s+)?IA|deixa\s+(?:a\s+)?IA)\b", re.I,
)


_CLASSIFY_SYSTEM = """\
Você é um classificador de transcrições de áudio pessoais em português.
Sua única função é retornar um array JSON com a classificação de cada segmento.
Regras absolutas:
- Retorne APENAS o array JSON, sem texto antes ou depois.
- Use APENAS os tipos e campos definidos no schema.
- Na dúvida, classifique como "comment".
- NUNCA invente datas, valores ou números.
- expense: NUNCA estime amount — se não foi dito número, amount=null.
- food: estime calorias se a pessoa descreveu a comida sem número; marque estimated=true."""

def classify_transcript(transcript: str, llm_runner) -> tuple[list[Item], str]:
    # Force LLM?
    if _FORCE_LLM_RE.search(transcript):
        logger.info("Force LLM: trigger phrase detected, bypassing patterns")
        success, output = llm_runner(
            _build_llm_prompt(transcript, "(forçado pelo usuário)"),
            system_prompt=_CLASSIFY_SYSTEM)
        if success:
            llm_items = _parse_llm_output(output)
            items = [_safe_validate(r) for r in llm_items]
            stats.record(items, "")
            return items, ""

    # Phase 1 — Pattern matching
    raw_items, unmatched = pattern_classify(transcript, _REGISTRY)
    items = [_safe_validate(r) for r in raw_items]

    if not unmatched:
        stats.record(items, "")
        logger.info("LLM skipped: todos os %d segmentos resolvidos por pattern", len(items))
        return items, ""

    logger.info("Classifier: %d items por pattern, %d chars unmatched → LLM fallback",
                len(items), len(unmatched))

    # Phase 2 — LLM fallback
    success, output = llm_runner(
        _build_llm_prompt(unmatched, _build_already_summary(items)),
        system_prompt=_CLASSIFY_SYSTEM)
    if not success:
        items.append(validate_item({"type": "comment", "data": {"text": f"[LLM fallback falhou] {unmatched[:300]}"},
                                    "_source": "fallback", "_confidence": 0.0}))
        stats.record(items, unmatched)
        return items, unmatched

    llm_items = _parse_llm_output(output)
    for raw in llm_items:
        raw.setdefault("_source", "llm")
        raw.setdefault("_confidence", 0.75)
        items.append(_safe_validate(raw))

    logger.info("LLM fallback: %d segmentos classificados, total=%d items", len(llm_items), len(items))
    stats.record(items, unmatched if not llm_items else "")
    return items, unmatched if not llm_items else ""


# -- helpers --

def _safe_validate(raw: dict) -> Item:
    return validate_item(raw)


def _build_already_summary(items: list[Item]) -> str:
    if not items: return "(nenhum)"
    lines = []
    for item in items:
        d = item.data
        desc = ""
        for attr in ["description","text","exercise_hint","piece_hint","activity","task_hint","search_hint"]:
            if hasattr(d, attr):
                desc = str(getattr(d, attr))[:80]; break
        if not desc and hasattr(d, "weight_kg"): desc = f"{d.weight_kg}kg"
        habit_str = f"/{item.habit}" if item.habit else ""
        lines.append(f"- {item.type}{habit_str}: {desc}")
    return "\n".join(lines)


def _build_llm_prompt(unmatched_text: str, already_summary: str) -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").format(
        unmatched_text=unmatched_text, already_classified=already_summary)


def _parse_llm_output(output: str) -> list[dict]:
    output = re.sub(r"^```(?:json)?\s*", "", output.strip())
    output = re.sub(r"\s*```$", "", output)
    try:
        result = json.loads(output)
        if isinstance(result, list): return result
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", output, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(0))
            if isinstance(result, list): return result
        except json.JSONDecodeError:
            pass
    items = []
    for m in re.finditer(r"\{[^{}]*\}", output):
        try: items.append(json.loads(m.group(0)))
        except json.JSONDecodeError: continue
    return items


# -- stats --

class Stats:
    def __init__(self):
        self.total_audios = 0; self.total_segments = 0
        self.pattern_matches = 0; self.llm_calls = 0; self.llm_skips = 0
        self.by_pattern: dict[str, int] = {}; self.by_type: dict[str, int] = {}

    def record(self, items: list[Item], unmatched: str) -> None:
        self.total_audios += 1
        self.total_segments += len(items) + (1 if unmatched else 0)
        for item in items:
            if item.source.startswith("pattern:"):
                self.pattern_matches += 1
                name = item.source.split(":", 1)[1]
                self.by_pattern[name] = self.by_pattern.get(name, 0) + 1
            elif item.source == "llm":
                self.by_pattern["llm"] = self.by_pattern.get("llm", 0) + 1
            self.by_type[item.type] = self.by_type.get(item.type, 0) + 1
        if unmatched: self.llm_calls += 1
        else: self.llm_skips += 1

    def summary(self) -> str:
        if not self.total_audios: return "Stats: sem dados"
        pr = 100 * self.pattern_matches / max(self.total_segments, 1)
        lr = 100 * self.llm_calls / max(self.total_audios, 1)
        lines = [
            f"Stats: {self.total_audios} áudios, {self.total_segments} segmentos",
            f"  Pattern match: {self.pattern_matches} ({pr:.0f}%)",
            f"  LLM fallback: {self.llm_calls}/{self.total_audios} áudios ({lr:.0f}%)",
            f"  LLM skips: {self.llm_skips} áudios (100% pattern)",
        ]
        if self.by_pattern:
            lines.append("  By pattern:")
            for n, c in sorted(self.by_pattern.items(), key=lambda x: -x[1]):
                lines.append(f"    {n}: {c}")
        if self.by_type:
            lines.append("  By type:")
            for t, c in sorted(self.by_type.items(), key=lambda x: -x[1]):
                lines.append(f"    {t}: {c}")
        return "\n".join(lines)


stats = Stats()
