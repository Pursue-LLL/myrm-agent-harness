"""LLM conflict detector for CCSP.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: compile LLM)
..core.structure::WikiStructure (POS: read concept summaries)
utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取 — 兼容 reasoning 模型 content 空回退)
utils.json_parsing::parse_llm_json_object (POS: robust JSON object extraction from LLM output — fences, prose, bare control chars, trailing commas)

[OUTPUT]
- detect_conflict: structured verdict for a concept pair

[POS]
Optional LLM pass after zero-LLM pairing. Returns None when no factual conflict or low confidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.section_contract import (
    extract_compiled_truth_summary,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.json_parsing import parse_llm_json_object
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .types import ConceptPair, ConflictVerdict

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

logger = get_agent_logger(__name__)

MIN_CONFLICT_CONFIDENCE = 0.7


def _concept_summary(structure: WikiStructure, concept_name: str, *, fallback_definition: str) -> str:
    path = structure.get_concept_file_path(concept_name)
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if content.strip():
            summary = extract_compiled_truth_summary(content)
            if summary:
                return summary
    cleaned = fallback_definition.strip()
    return cleaned or concept_name


async def detect_conflict(
    llm: BaseChatModel,
    structure: WikiStructure,
    pair: ConceptPair,
    *,
    definition_a: str,
    definition_b: str,
) -> ConflictVerdict | None:
    """Return a conflict verdict when the pair has a factual contradiction above confidence threshold."""
    summary_a = _concept_summary(structure, pair.concept_a, fallback_definition=definition_a)
    summary_b = _concept_summary(structure, pair.concept_b, fallback_definition=definition_b)

    system_msg = SystemMessage(
        content=(
            "You compare two wiki concepts for factual contradictions. "
            "Style or emphasis differences are NOT conflicts. "
            "Respond with JSON only."
        )
    )
    human_msg = HumanMessage(
        content=(
            "Compare these two concepts. Output JSON with keys:\n"
            "is_factual_conflict (boolean), confidence (0-1 number), topic (string), "
            "side_a (string), side_b (string), resolution_hint (string).\n\n"
            f"Concept A ({pair.concept_a}):\n{summary_a}\n\n"
            f"Concept B ({pair.concept_b}):\n{summary_b}"
        )
    )

    try:
        response = await llm.ainvoke([system_msg, human_msg])
        text = extract_answer_text(response).strip()
        payload = parse_llm_json_object(text)
        if payload is None:
            return None
    except Exception as exc:
        logger.warning(
            "Conflict detection failed for %s vs %s: %s",
            pair.concept_a,
            pair.concept_b,
            exc,
        )
        return None

    is_conflict = bool(payload.get("is_factual_conflict"))
    confidence_raw = payload.get("confidence", 0.0)
    if isinstance(confidence_raw, str):
        try:
            confidence = float(confidence_raw)
        except ValueError:
            confidence = 0.0
    elif isinstance(confidence_raw, (int, float)):
        confidence = float(confidence_raw)
    else:
        confidence = 0.0

    if not is_conflict or confidence < MIN_CONFLICT_CONFIDENCE:
        return None

    topic = str(payload.get("topic", "")).strip() or pair.concept_a.rsplit("/", maxsplit=1)[-1]
    side_a = str(payload.get("side_a", "")).strip() or summary_a[:240]
    side_b = str(payload.get("side_b", "")).strip() or summary_b[:240]
    resolution_hint = str(payload.get("resolution_hint", "")).strip() or (
        "Review both positions and decide which claim should take priority."
    )

    return ConflictVerdict(
        is_factual_conflict=True,
        confidence=min(max(confidence, 0.0), 1.0),
        topic=topic,
        side_a=side_a,
        side_b=side_b,
        resolution_hint=resolution_hint,
    )
