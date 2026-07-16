"""LLM-driven staleness review for memories that have exceeded their TTL.

[INPUT]
- memory.types::{BaseMemory, SemanticMemory, EpisodicMemory, MemoryStatus} (POS: memory data models)
- memory.strategies.forgetting::{ForgettableMemory} (POS: type alias)

[OUTPUT]
- StalenessReviewConfig: Configuration for staleness review thresholds
- StalenessDecision: Per-fact review decision (KEEP/EXTEND/REMOVE)
- StalenessReviewResult: Aggregate result of a review cycle
- select_stale_candidates: Pure function to find memories past their TTL
- StalenessReviewer: LLM-powered reviewer that judges whether stale facts are still valid

[POS]
Staleness review strategy. Identifies memories that have exceeded their LLM-estimated
validity window (expected_valid_days) and submits them for semantic review by an LLM.
The LLM decides KEEP (still valid), EXTEND (valid but needs new TTL), or REMOVE (outdated).
Protected memories (pinned, corrections, recently accessed) are excluded.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettableMemory
from myrm_agent_harness.toolkits.memory.types import MemoryStatus

logger = logging.getLogger(__name__)

LLMFunc = Callable[[str, str], Awaitable[str]]


class StalenessAction(StrEnum):
    KEEP = "keep"
    EXTEND = "extend"
    REMOVE = "remove"


@dataclass
class StalenessReviewConfig:
    min_candidates: int = 3
    max_candidates_per_cycle: int = 20
    max_removals_per_cycle: int = 5
    max_extension_days: int = 730
    keep_cooldown_days: int = 30
    protected_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"correction"})
    )
    recent_access_protection_days: int = 7


@dataclass
class StalenessDecision:
    memory_id: str
    action: StalenessAction
    reason: str = ""
    extend_by_days: int = 0


@dataclass
class StalenessReviewResult:
    candidates_found: int = 0
    reviewed_count: int = 0
    kept_count: int = 0
    extended_count: int = 0
    removed_count: int = 0
    removed_ids: list[str] = field(default_factory=list)
    extended_updates: list[tuple[str, int]] = field(default_factory=list)
    keep_cooldown_updates: list[tuple[str, int]] = field(default_factory=list)


def select_stale_candidates(
    memories: Sequence[ForgettableMemory],
    config: StalenessReviewConfig,
) -> list[ForgettableMemory]:
    """Select memories that have exceeded their expected_valid_days TTL.

    Only considers memories with a non-null expected_valid_days that have
    surpassed that window. Excludes pinned, archived, correction-chain, and
    recently-accessed memories.
    """
    now = datetime.now(UTC)
    recent_cutoff = now.timestamp() - config.recent_access_protection_days * 86400
    candidates: list[tuple[int, ForgettableMemory]] = []

    for mem in memories:
        evd = getattr(mem, "expected_valid_days", None)
        if not isinstance(evd, int) or evd <= 0:
            continue

        if getattr(mem, "pinned", False):
            continue
        if getattr(mem, "status", None) != MemoryStatus.ACTIVE:
            continue
        if getattr(mem, "correction_of", None) is not None:
            continue

        last_access = getattr(mem, "last_accessed_at", None)
        if last_access is not None:
            la_ts = last_access.timestamp() if last_access.tzinfo else last_access.replace(tzinfo=UTC).timestamp()
            if la_ts > recent_cutoff:
                continue

        created = mem.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_days = (now - created).days
        if age_days >= evd:
            candidates.append((age_days - evd, mem))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in candidates[:config.max_candidates_per_cycle]]


_STALENESS_REVIEW_SYSTEM = """You are a memory maintenance assistant. Your job is to review facts that have exceeded their expected validity period and decide whether each fact is still accurate.

For each fact, decide:
- "keep": The fact is still likely true (no action needed, will be reviewed again later)
- "extend": The fact is still true but needs a longer validity window. Provide extend_by_days (30-365)
- "remove": The fact is likely outdated or no longer accurate

## Rules
1. Be CONSERVATIVE: when uncertain, prefer "keep" over "remove"
2. Consider: would this fact mislead the AI assistant if used in conversation?
3. Facts about learning/studying something are likely outdated after their TTL
4. Facts about current projects/tools may have changed
5. Stable preferences and habits are usually still valid

## Output
JSON array with one entry per fact:
[{"id":"<fact_id>","action":"keep|extend|remove","reason":"brief explanation","extend_by_days":<int or 0>}]"""


class StalenessReviewer:
    """Reviews stale memory candidates via LLM to determine KEEP/EXTEND/REMOVE."""

    def __init__(
        self,
        llm_func: LLMFunc,
        config: StalenessReviewConfig | None = None,
    ) -> None:
        self._llm = llm_func
        self._config = config or StalenessReviewConfig()

    async def review(
        self, candidates: Sequence[ForgettableMemory]
    ) -> StalenessReviewResult:
        """Review stale candidates and return decisions."""
        cfg = self._config
        result = StalenessReviewResult(candidates_found=len(candidates))

        if len(candidates) < cfg.min_candidates:
            return result

        facts_for_review = []
        for mem in candidates:
            created = mem.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - created).days
            facts_for_review.append({
                "id": mem.id,
                "content": mem.content[:200],
                "age_days": age_days,
                "expected_valid_days": getattr(mem, "expected_valid_days", None),
                "importance": getattr(mem, "importance", 0.5),
                "access_count": mem.access_count,
            })

        prompt = (
            f"Review these {len(facts_for_review)} facts that have exceeded their expected validity:\n\n"
            f"{json.dumps(facts_for_review, indent=2, ensure_ascii=False)}\n\n"
            "Return ONLY a valid JSON array with your decisions."
        )

        try:
            raw = await self._llm(_STALENESS_REVIEW_SYSTEM, prompt)
            decisions = self._parse_decisions(raw, {m.id for m in candidates})
        except Exception as exc:
            logger.warning("Staleness review LLM call failed: %s", exc)
            return result

        result.reviewed_count = len(decisions)
        remove_ids: set[str] = set()

        id_to_evd: dict[str, int] = {
            m.id: getattr(m, "expected_valid_days", 0) or 0
            for m in candidates
        }

        for decision in decisions:
            if decision.action == StalenessAction.REMOVE:
                remove_ids.add(decision.memory_id)
            elif decision.action == StalenessAction.EXTEND:
                result.extended_count += 1
                result.extended_updates.append(
                    (decision.memory_id, decision.extend_by_days)
                )
            else:
                result.kept_count += 1
                new_evd = id_to_evd.get(decision.memory_id, 0) + cfg.keep_cooldown_days
                result.keep_cooldown_updates.append((decision.memory_id, new_evd))

        if len(remove_ids) > cfg.max_removals_per_cycle:
            remove_ids = set(list(remove_ids)[:cfg.max_removals_per_cycle])

        result.removed_count = len(remove_ids)
        result.removed_ids = list(remove_ids)
        return result

    def _parse_decisions(
        self, raw: str, valid_ids: set[str]
    ) -> list[StalenessDecision]:
        """Parse LLM response into typed decisions."""
        import re

        raw = raw.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group(0)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Staleness review: failed to parse LLM response")
            return []

        if not isinstance(data, list):
            return []

        decisions: list[StalenessDecision] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            mid = item.get("id", "")
            if mid not in valid_ids:
                continue
            action_str = item.get("action", "keep")
            try:
                action = StalenessAction(action_str)
            except ValueError:
                action = StalenessAction.KEEP

            extend_by = 0
            if action == StalenessAction.EXTEND:
                raw_ext = item.get("extend_by_days", 90)
                if isinstance(raw_ext, (int, float)) and not isinstance(raw_ext, bool):
                    extend_by = min(int(raw_ext), self._config.max_extension_days)
                else:
                    extend_by = 90

            decisions.append(StalenessDecision(
                memory_id=mid,
                action=action,
                reason=str(item.get("reason", "")),
                extend_by_days=extend_by,
            ))
        return decisions
