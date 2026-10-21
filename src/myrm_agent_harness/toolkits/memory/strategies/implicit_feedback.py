"""Implicit feedback signal detection and memory correction planner.

[INPUT]
- memory.strategies.extractor::{FeedbackSignal, detect_feedback_signals} (POS: regex-based fast pre-filter)
- memory.types::{AnyMemory, SemanticMemory, MemoryType} (POS: memory data models)
- utils.json_parsing::parse_llm_json_object, parse_llm_json_list (POS: robust JSON object/list extraction from LLM output — fences, prose, bare control chars, trailing commas)

[OUTPUT]
- ImplicitFeedbackResult: Detected signals with planned memory actions
- detect_implicit_feedback: Regex pre-filter + LLM deep detection pipeline
- plan_memory_corrections: Plans concrete memory operations from detected signals

[POS]
Session-level implicit feedback detection and memory correction planner.
Upgrades the basic regex-only `detect_feedback_signals` with an LLM refinement
pass that catches implicit contradictions (e.g. "I left that job" without
explicit negation words). Produces structured correction proposals (add/update/delete)
for the Governance queue.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.strategies.extractor import (
    FeedbackSignal,
    detect_feedback_signals,
    detect_language,
)
from myrm_agent_harness.utils.json_parsing import parse_llm_json_list, parse_llm_json_object

logger = logging.getLogger(__name__)

LLMFunc = Callable[[str, str], Awaitable[str]]


class CorrectionAction(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class CorrectionProposal:
    """A single memory correction action proposed by the planner."""

    action: CorrectionAction
    memory_type: str
    content: str
    confidence: float
    reasoning: str
    target_memory_id: str | None = None
    old_content: str | None = None


@dataclass(frozen=True, slots=True)
class ImplicitFeedbackResult:
    """Result of implicit feedback detection + planning."""

    signal: FeedbackSignal
    has_implicit_contradiction: bool
    proposals: list[CorrectionProposal] = field(default_factory=list)
    raw_detection_response: str | None = None


_SIGNAL_DETECTION_SYSTEM = """\
You are an implicit feedback analyst. Given a conversation between a user and an AI assistant, \
detect whether the user is IMPLICITLY correcting a factual assumption the AI is making — \
even without using explicit negation words like "wrong" or "incorrect".

Examples of implicit corrections:
- AI assumes user works at Company A, user says "I left there last month"
- AI references a tech stack, user says "We migrated to X already"
- AI assumes a preference, user redirects without confrontation: "Actually I prefer Y"
- User repeats the same question differently (AI clearly misunderstood)

Your task: Analyze the last few exchanges. Output JSON:
{"has_contradiction": true/false, "signals": [{"round_index": N, "user_said": "...", "ai_assumed": "...", "correct_fact": "..."}]}

Rules:
1. Only flag genuine factual contradictions — not stylistic disagreements or follow-up questions.
2. round_index is 0-based from the start of the provided snippet.
3. If no contradiction: {"has_contradiction": false, "signals": []}
4. Output ONLY valid JSON, no other text."""

_PLAN_SYSTEM = """\
You are a memory correction planner. Given detected contradiction signals and optionally \
related existing memories, plan concrete memory operations.

Available actions:
- "add": Store a new correct fact (when no existing memory covers this topic)
- "update": Replace an existing memory's content with the corrected version
- "delete": Remove an existing memory that is now factually wrong

Output JSON array of actions:
[{"action": "add|update|delete", "memory_type": "semantic|episodic|procedural", \
"content": "the correct fact", "confidence": 0.0-1.0, "reasoning": "why", \
"target_memory_id": "id_or_null", "old_content": "what_was_wrong_or_null"}]

Rules:
1. confidence ≥ 0.85 for corrections (user stated it directly).
2. content must be a concise declarative sentence in third person.
3. memory_type is usually "semantic" for factual corrections.
4. If no action needed: []
5. Output ONLY valid JSON array, no other text."""

_SCAN_WINDOW = 10
_MAX_CONTENT_PER_MSG = 600


async def detect_implicit_feedback(
    messages: Sequence[dict[str, str]],
    llm_func: LLMFunc,
    *,
    existing_memories: Sequence[str] | None = None,
) -> ImplicitFeedbackResult:
    """Two-stage implicit feedback detection: regex fast-path + LLM deep scan.

    Stage 1: Regex pre-filter (zero cost). If NEGATIVE detected, skip LLM detection
    (already confirmed) and go directly to planning.
    Stage 2: LLM detection for implicit contradictions that regex cannot catch.

    Args:
        messages: Full conversation messages
        llm_func: LLM function (system_prompt, user_prompt) -> response
        existing_memories: Optional list of existing memory content strings for context

    Returns:
        ImplicitFeedbackResult with detected signals and planned proposals
    """
    if len(messages) < 2:
        return ImplicitFeedbackResult(signal=FeedbackSignal.NONE, has_implicit_contradiction=False)

    regex_signal = detect_feedback_signals(messages)

    if regex_signal == FeedbackSignal.NEGATIVE:
        proposals = await plan_memory_corrections(messages, llm_func, existing_memories=existing_memories)
        return ImplicitFeedbackResult(
            signal=FeedbackSignal.NEGATIVE,
            has_implicit_contradiction=False,
            proposals=proposals,
        )

    has_contradiction, raw_response = await _llm_detect_contradiction(messages, llm_func)

    if not has_contradiction:
        return ImplicitFeedbackResult(
            signal=regex_signal,
            has_implicit_contradiction=False,
            raw_detection_response=raw_response,
        )

    proposals = await plan_memory_corrections(messages, llm_func, existing_memories=existing_memories)
    return ImplicitFeedbackResult(
        signal=FeedbackSignal.NEGATIVE,
        has_implicit_contradiction=True,
        proposals=proposals,
        raw_detection_response=raw_response,
    )


async def plan_memory_corrections(
    messages: Sequence[dict[str, str]],
    llm_func: LLMFunc,
    *,
    existing_memories: Sequence[str] | None = None,
) -> list[CorrectionProposal]:
    """Plan concrete memory correction operations from a conversation with detected signals.

    Args:
        messages: Conversation messages (at least last N turns)
        llm_func: LLM function
        existing_memories: Relevant existing memories for update/delete context

    Returns:
        List of structured correction proposals
    """
    recent = messages[-_SCAN_WINDOW:]
    language = detect_language(" ".join(m.get("content", "")[:200] for m in recent if m.get("role") == "user"))

    conversation = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')[:_MAX_CONTENT_PER_MSG]}" for m in recent
    )

    prompt_parts = [f"## Conversation\n\n{conversation}"]

    if existing_memories:
        memory_block = "\n".join(f"- {mem}" for mem in existing_memories[:20])
        prompt_parts.append(f"\n## Existing Memories (may need correction)\n\n{memory_block}")

    if language == "zh":
        prompt_parts.append("\n**IMPORTANT**: Write all content in Chinese (中文).")

    prompt_parts.append("\nPlan the memory correction actions. Return ONLY valid JSON array.")
    prompt = "\n".join(prompt_parts)

    try:
        raw = await llm_func(_PLAN_SYSTEM, prompt)
        return _parse_plan_response(raw)
    except Exception as e:
        logger.warning("Memory correction planning failed: %s", e)
        return []


async def _llm_detect_contradiction(
    messages: Sequence[dict[str, str]],
    llm_func: LLMFunc,
) -> tuple[bool, str]:
    """LLM-based implicit contradiction detection.

    Returns:
        (has_contradiction, raw_response)
    """
    recent = messages[-_SCAN_WINDOW:]
    conversation = "\n".join(
        f"[{'USER' if m.get('role') == 'user' else 'AI'}]: {m.get('content', '')[:_MAX_CONTENT_PER_MSG]}"
        for m in recent
    )

    prompt = f"Analyze this conversation for implicit corrections:\n\n{conversation}"

    try:
        raw = await llm_func(_SIGNAL_DETECTION_SYSTEM, prompt)
        parsed = parse_llm_json_object(raw)
        if parsed is not None:
            return bool(parsed.get("has_contradiction", False)), raw
        return False, raw
    except Exception as e:
        logger.warning("Implicit feedback LLM detection failed: %s", e)
        return False, ""


def _parse_plan_response(raw: str) -> list[CorrectionProposal]:
    """Parse LLM planning response into CorrectionProposal objects."""
    data = parse_llm_json_list(raw)
    if data is None:
        return []

    proposals: list[CorrectionProposal] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            action_str = item.get("action", "")
            if action_str not in ("add", "update", "delete"):
                continue
            content = item.get("content", "").strip()
            if not content:
                continue
            proposals.append(
                CorrectionProposal(
                    action=CorrectionAction(action_str),
                    memory_type=item.get("memory_type", "semantic"),
                    content=content,
                    confidence=float(item.get("confidence", 0.85)),
                    reasoning=item.get("reasoning", ""),
                    target_memory_id=item.get("target_memory_id"),
                    old_content=item.get("old_content"),
                )
            )
        except (ValueError, TypeError) as e:
            logger.debug("Skipping malformed correction proposal: %s", e)
    return proposals
