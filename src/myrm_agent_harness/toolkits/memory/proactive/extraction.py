"""Commitment extraction engine — LLM-powered implicit promise detection.

Analyzes conversation turns to detect implicit user commitments and
follow-up opportunities. Uses structured output (Pydantic) for reliable
parsing, with confidence thresholds and deduplication.

[INPUT]
- commitment.types::{CommitmentCandidate, ExtractionBatchResult, CommitmentKind, CommitmentSensitivity} (POS: type definitions)
- commitment.config::CommitmentConfig (POS: extraction thresholds)

[OUTPUT]
- CommitmentExtractor: Stateless extractor class
- extract_commitments: Convenience function for single-shot extraction
- build_extraction_prompt: Prompt builder (exposed for testing)

[POS]
Commitment extraction engine. Analyzes conversations via LLM to detect
implicit promises and follow-up items. Produces CommitmentCandidate
objects validated against configurable confidence thresholds.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.proactive.config import CommitmentConfig
from myrm_agent_harness.toolkits.memory.proactive.types import (
    CommitmentCandidate,
    CommitmentKind,
    CommitmentSensitivity,
    ExtractionBatchResult,
)

logger = logging.getLogger(__name__)

LLMFunc = Callable[[str, str], Awaitable[str]]

_EXTRACTION_PROMPT = """You are a hidden background commitment extractor. Do not address the user.

Analyze the conversation to detect implicit follow-up commitments the agent should track. Create candidates ONLY for items the user did NOT explicitly schedule as reminders or cron tasks.

## Categories
- **event_check_in**: User mentions a future event → check in around that time ("interview on Friday", "dentist next week")
- **deadline_check**: User mentions a deadline → check before it arrives ("report due Friday", "need to submit by Monday")
- **care_check_in**: User shares personal/emotional concern → gentle follow-up later ("mom is sick", "feeling stressed")
- **open_loop**: User mentions ongoing situation without resolution → follow up in a few days ("waiting for client reply", "still researching")

## Rules
1. Output JSON only: {"candidates": [...]}
2. Each candidate: kind, sensitivity, reason, suggestedText, confidence, dedupeKey, dueWindow
3. sensitivity: "routine" (work tasks), "personal" (personal events), "care" (health/emotions)
4. dueWindow.earliest and dueWindow.latest: ISO timestamps in the future
5. **Skip explicit reminders** — "remind me tomorrow", "set a timer" belong to cron/calendar
6. **Skip if already resolved** in the assistant response
7. **Skip if the assistant already scheduled** a cron/reminder for it
8. care_check_in must be gentle, rare, high confidence. Never interrogating.
9. suggestedText: short, natural, suitable for the same channel
10. dedupeKey: stable within session, e.g. "interview:2026-05-20" or "mom-health:2026-05-19"
11. Prefer NO candidate over weak candidates. Quality > quantity.
12. Maximum 3 candidates per extraction."""

_MAX_INPUT_CHARS = 60_000
_HEAD_COUNT = 2


class _ExtractionInput(BaseModel):
    """Internal: formatted input for the extraction prompt."""

    now: str
    timezone: str
    conversation: list[dict[str, str]]
    existing_pending: list[dict[str, str]] = Field(default_factory=list)


def build_extraction_prompt(
    messages: Sequence[dict[str, str]],
    *,
    now_iso: str,
    timezone: str = "UTC",
    existing_pending: Sequence[dict[str, str]] | None = None,
    language: str = "en",
) -> str:
    """Build the user-facing prompt for commitment extraction."""
    truncated = _truncate_head_tail(messages, _MAX_INPUT_CHARS)

    formatted_msgs = []
    for msg in truncated:
        role = msg.get("role", "user").upper()
        content = msg.get("content", "")
        formatted_msgs.append(f"[{role}]: {content}")

    parts = [
        f"Current time: {now_iso}",
        f"Timezone: {timezone}",
        "",
        "## Conversation",
        "",
        *formatted_msgs,
    ]

    if existing_pending:
        parts.extend(["", "## Existing Pending Commitments (do NOT duplicate)"])
        for p in existing_pending:
            parts.append(f"- [{p.get('kind', '?')}] {p.get('reason', '?')} (dedupe: {p.get('dedupe_key', '?')})")

    if language == "zh":
        parts.append("\n**IMPORTANT**: Write reason and suggestedText in Chinese (中文).")

    parts.append('\nExtract implicit commitments. Output JSON only: {"candidates": [...]}')
    parts.append('If no commitments found, output: {"candidates": []}')

    return "\n".join(parts)


def _truncate_head_tail(messages: Sequence[dict[str, str]], max_chars: int) -> list[dict[str, str]]:
    """Keep first 2 + fill from end within budget."""
    total = sum(len(m.get("content", "")) for m in messages)
    if total <= max_chars or len(messages) <= _HEAD_COUNT:
        return list(messages)

    head = list(messages[:_HEAD_COUNT])
    head_chars = sum(len(m.get("content", "")) for m in head)
    budget = max_chars - head_chars

    tail: list[dict[str, str]] = []
    tail_chars = 0
    for msg in reversed(messages[_HEAD_COUNT:]):
        msg_len = len(msg.get("content", ""))
        if tail_chars + msg_len > budget:
            break
        tail.append(msg)
        tail_chars += msg_len
    tail.reverse()

    return head + tail


def _detect_language(messages: Sequence[dict[str, str]]) -> str:
    """Detect primary language based on Chinese character ratio."""
    text = "".join(m.get("content", "") for m in messages)
    if not text:
        return "en"
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if chinese / len(text) >= 0.3 else "en"


def _parse_response(raw: str) -> ExtractionBatchResult:
    """Parse LLM output into structured result with fallback."""
    import json
    import re

    raw = raw.strip()
    if not raw:
        return ExtractionBatchResult()

    match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if match:
        raw = match.group(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Commitment extraction: failed to parse JSON response")
        return ExtractionBatchResult()

    if not isinstance(data, dict) or "candidates" not in data:
        return ExtractionBatchResult()

    candidates: list[CommitmentCandidate] = []
    for item in data.get("candidates", []):
        if not isinstance(item, dict):
            continue
        try:
            kind_val = item.get("kind", "")
            if kind_val not in {k.value for k in CommitmentKind}:
                continue
            sens_val = item.get("sensitivity", "routine")
            if sens_val not in {s.value for s in CommitmentSensitivity}:
                sens_val = "routine"

            due = item.get("dueWindow", {})
            earliest = due.get("earliest", "") if isinstance(due, dict) else ""
            if not earliest:
                continue

            candidates.append(
                CommitmentCandidate(
                    kind=CommitmentKind(kind_val),
                    sensitivity=CommitmentSensitivity(sens_val),
                    reason=str(item.get("reason", "")).strip(),
                    suggested_text=str(item.get("suggestedText", "")).strip(),
                    dedupe_key=str(item.get("dedupeKey", "")).strip(),
                    confidence=float(item.get("confidence", 0.0)),
                    due_window_earliest=earliest,
                    due_window_latest=due.get("latest") if isinstance(due, dict) else None,
                    due_window_timezone=due.get("timezone") if isinstance(due, dict) else None,
                )
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Commitment extraction: skipping malformed candidate: %s", e)

    return ExtractionBatchResult(candidates=candidates[:3])


def validate_candidates(
    candidates: list[CommitmentCandidate],
    config: CommitmentConfig,
    now_ms: int,
    min_due_ms: int,
) -> list[CommitmentCandidate]:
    """Filter candidates by confidence threshold and due window validity."""
    valid: list[CommitmentCandidate] = []
    for c in candidates:
        threshold = (
            config.care_confidence_threshold
            if c.kind == CommitmentKind.CARE_CHECK_IN or c.sensitivity == CommitmentSensitivity.CARE
            else config.confidence_threshold
        )
        if c.confidence < threshold:
            continue

        earliest_ms = _parse_iso_to_ms(c.due_window_earliest)
        if earliest_ms is None or earliest_ms <= now_ms:
            continue

        valid.append(c)

    return valid


def _parse_iso_to_ms(iso: str) -> int | None:
    """Parse ISO timestamp to epoch ms."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


class CommitmentExtractor:
    """Stateless commitment extractor powered by LLM."""

    def __init__(self, config: CommitmentConfig | None = None) -> None:
        self.config = config or CommitmentConfig()

    async def extract(
        self,
        messages: Sequence[dict[str, str]],
        llm_func: LLMFunc,
        *,
        existing_pending: Sequence[dict[str, str]] | None = None,
        timezone: str = "UTC",
    ) -> list[CommitmentCandidate]:
        """Extract commitment candidates from a conversation.

        Returns validated candidates that pass confidence thresholds.
        """
        if not self.config.enabled:
            return []

        if len(messages) < self.config.debounce_turns:
            return []

        now = datetime.now(UTC)
        now_iso = now.isoformat()
        now_ms = int(now.timestamp() * 1000)
        language = _detect_language(messages)

        prompt = build_extraction_prompt(
            messages,
            now_iso=now_iso,
            timezone=timezone,
            existing_pending=existing_pending,
            language=language,
        )

        try:
            raw = await llm_func(_EXTRACTION_PROMPT, prompt)
            result = _parse_response(raw)
        except Exception as e:
            logger.warning("Commitment extraction LLM call failed: %s", e)
            return []

        valid = validate_candidates(
            result.candidates,
            self.config,
            now_ms=now_ms,
            min_due_ms=now_ms,
        )

        if valid:
            logger.info(
                "Commitment extraction: %d candidates → %d valid",
                len(result.candidates),
                len(valid),
            )

        return valid


async def extract_commitments(
    messages: Sequence[dict[str, str]],
    llm_func: LLMFunc,
    config: CommitmentConfig | None = None,
    *,
    existing_pending: Sequence[dict[str, str]] | None = None,
    timezone: str = "UTC",
) -> list[CommitmentCandidate]:
    """Convenience function for single-shot extraction."""
    extractor = CommitmentExtractor(config=config)
    return await extractor.extract(
        messages,
        llm_func,
        existing_pending=existing_pending,
        timezone=timezone,
    )
