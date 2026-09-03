"""Session blind spot knowledge extraction strategy.

Analyzes missed queries, user corrections, and negative interaction signals
across sessions to extract structured knowledge patches (Wiki, Procedural, Skill gaps).
Pure strategy module decoupled from specific persistence layers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import AliasChoices, BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_DEFAULT_MIN_CANDIDATES = 1
_MAX_PROMPT_CANDIDATES = 50

_SYSTEM_PROMPT = """You are a knowledge consolidation specialist.
Analyze missed user queries and user corrections from past assistant sessions.
Extract concrete, structured knowledge patches to fill knowledge gaps.

Classify each gap into one of:
- "wiki": Factual knowledge, architecture info, entity attributes, or domain facts.
- "procedural": User preferences, formatting rules, workflow constraints, or style instructions.
- "skill_gap": Missing tool capabilities or external integration requests that cannot be solved by text alone.

Rules:
1. Only produce high-confidence patches supported by clear user inquiries or explicit corrections.
2. Do not fabricate answers if the user only asked without providing or implying the fact. In such cases, frame the wiki patch as an explicit unresolved topic with placeholder context for user review.
3. Consolidate closely related questions into a single cohesive patch.
4. Keep titles concise (< 60 chars). Content must be objective and directly usable.
"""


class PatchTargetType(StrEnum):
    """Destination type for a blind spot knowledge patch."""

    WIKI = "wiki"
    PROCEDURAL = "procedural"
    SKILL_GAP = "skill_gap"


@dataclass(frozen=True, slots=True)
class BlindSpotCandidate:
    """A single missed query or user correction candidate."""

    query: str
    session_id: str = ""
    turn_index: int = 0
    user_correction: str | None = None
    thumbs_down: bool = False
    created_at_iso: str = ""


class BlindSpotKnowledgePatch(BaseModel):
    """A structured knowledge patch extracted from session blind spots."""

    title: str = Field(
        validation_alias=AliasChoices("title", "name", "topic"),
        description="Short concise title of the missing knowledge (<60 chars)",
    )
    target_type: PatchTargetType = Field(
        default=PatchTargetType.WIKI,
        validation_alias=AliasChoices("target_type", "type", "category"),
        description="Target category: wiki, procedural, or skill_gap",
    )
    content: str = Field(
        description="The extracted fact, procedural rule, or capability description",
    )
    trigger_condition: str = Field(
        default="",
        validation_alias=AliasChoices("trigger_condition", "trigger", "when"),
        description="Condition or query pattern where this knowledge applies",
    )
    rationale: str = Field(
        default="",
        validation_alias=AliasChoices("rationale", "reason", "evidence"),
        description="Why this patch was extracted and which signals supported it",
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    source_queries: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("source_queries", "queries", "sources"),
        description="List of raw user queries that inspired this patch",
    )
    suggested_action: str = Field(
        default="",
        validation_alias=AliasChoices("suggested_action", "action", "next_step"),
        description="Suggested action for the user upon review",
    )


class BlindSpotResponse(BaseModel):
    """Structured LLM response for blind spot extraction."""

    patches: list[BlindSpotKnowledgePatch] = Field(default_factory=list)
    summary_note: str = Field(default="", description="High-level overview of observed blind spots")


@dataclass(frozen=True, slots=True)
class BlindSpotReport:
    """Immutable result of a blind spot extraction cycle."""

    patches: tuple[BlindSpotKnowledgePatch, ...] = ()
    summary_note: str = ""
    candidate_count: int = 0
    duration_ms: float = 0.0
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "patches": [p.model_dump() for p in self.patches],
            "summary_note": self.summary_note,
            "candidate_count": self.candidate_count,
            "duration_ms": self.duration_ms,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }

    @property
    def has_patches(self) -> bool:
        return len(self.patches) > 0


def _build_blind_spot_prompt(candidates: Sequence[BlindSpotCandidate]) -> str:
    lines = ["## Missed Queries & Interaction Signals", ""]
    for idx, c in enumerate(candidates[:_MAX_PROMPT_CANDIDATES], start=1):
        line = f"{idx}. Query: {c.query}"
        if c.user_correction:
            line += f" | User Correction: {c.user_correction}"
        if c.thumbs_down:
            line += " | [Feedback: Negative / Thumbs Down]"
        lines.append(line)
    lines.append("")
    lines.append("Extract consolidated, structured knowledge patches for these gaps.")
    return "\n".join(lines)


async def extract_blind_spot_patches(
    candidates: Sequence[BlindSpotCandidate],
    llm: BaseChatModel | None,
    *,
    min_candidates: int = _DEFAULT_MIN_CANDIDATES,
) -> BlindSpotReport:
    """Extract structured knowledge patches from session blind spot candidates."""
    start_time = time.perf_counter()

    if not candidates or len(candidates) < min_candidates:
        return BlindSpotReport(
            candidate_count=len(candidates),
            skipped=True,
            skip_reason=f"Insufficient candidates ({len(candidates)} < {min_candidates})",
        )

    if llm is None:
        return BlindSpotReport(
            candidate_count=len(candidates),
            skipped=True,
            skip_reason="No LLM provided for extraction",
        )

    prompt_text = _build_blind_spot_prompt(candidates)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured_llm = llm.with_structured_output(BlindSpotResponse)
        response: BlindSpotResponse = await structured_llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=prompt_text),
            ]
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.warning("Blind spot extraction LLM call failed: %s", exc)
        return BlindSpotReport(
            candidate_count=len(candidates),
            duration_ms=elapsed,
            skipped=True,
            skip_reason=f"LLM extraction error: {exc}",
        )

    elapsed = (time.perf_counter() - start_time) * 1000
    valid_patches = [p for p in response.patches if p.confidence >= 0.5]

    return BlindSpotReport(
        patches=tuple(valid_patches),
        summary_note=response.summary_note,
        candidate_count=len(candidates),
        duration_ms=elapsed,
    )
