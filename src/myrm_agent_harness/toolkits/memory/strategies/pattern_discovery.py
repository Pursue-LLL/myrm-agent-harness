"""Cross-cycle pattern discovery — surface behavioral trends users haven't noticed.

[INPUT]
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.protocols.graph::GraphStoreProtocol (POS: graph store for claim collection)

[OUTPUT]
- PatternReport: Immutable result of a pattern discovery cycle.
- run_pattern_discovery: Analyze memories and insights to surface cross-cycle patterns.
- should_run_pattern_discovery: Gate check based on memory maturity.
- increment_consolidation_count: Track consolidation runs for gate check.
- get_recent_patterns: Retrieve patterns for Heartbeat SituationSection injection.

[POS]
Cross-cycle pattern discovery strategy. Runs weekly (server-layer scheduling),
analyzes accumulated memories, consolidation insights, and claim graph to find
behavioral patterns the user may not be aware of. Framework-layer pure strategy;
scheduling and persistence are server-layer responsibilities.

Closed-loop pipeline: high-confidence ESTABLISHED patterns are also promoted to
ProceduralRule (pending user approval) so the agent can apply learned behavioral
preferences automatically in future conversations.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)

_PROFILE_KEY_LAST_PATTERN_DISCOVERY = "_system.last_pattern_discovery_at"
_PROFILE_KEY_CONSOLIDATION_COUNT = "_system.consolidation_count"
_PROFILE_KEY_MEMORY_SET_HASH = "_system.pattern_discovery_memory_hash"
_MIN_MEMORY_COUNT = 50
_MIN_CONSOLIDATION_COUNT = 3

# Gate thresholds for promoting a pattern to a ProceduralRule.
# Only "established" patterns with high confidence become actionable rules.
_RULE_PROMOTION_MIN_CONFIDENCE = 0.8


class PatternDurability(StrEnum):
    """How stable a discovered pattern is over time."""

    EMERGING = "emerging"
    ESTABLISHED = "established"
    DECLINING = "declining"


class DiscoveredPattern(BaseModel):
    """A single behavioral or knowledge pattern found across memory cycles."""

    title: str = Field(description="Short pattern name (< 60 chars)")
    description: str = Field(description="What this pattern means for the user")
    evidence_summary: str = Field(description="Key memories or events supporting this pattern")
    durability: PatternDurability = Field(default=PatternDurability.EMERGING)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    actionable_suggestion: str = Field(
        default="",
        description="Optional proactive suggestion the agent can surface to the user",
    )


class PatternDiscoveryResponse(BaseModel):
    """Structured LLM output for pattern discovery."""

    patterns: list[DiscoveredPattern] = Field(default_factory=list)
    meta_observation: str = Field(
        default="",
        description="High-level observation about the user's overall behavior trajectory",
    )


@dataclass(frozen=True)
class PatternReport:
    """Immutable result of a pattern discovery cycle."""

    patterns: tuple[DiscoveredPattern, ...] = ()
    meta_observation: str = ""
    memory_count: int = 0
    insight_count: int = 0
    duration_ms: float = 0.0
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "patterns": [p.model_dump() for p in self.patterns],
            "meta_observation": self.meta_observation,
            "memory_count": self.memory_count,
            "insight_count": self.insight_count,
            "duration_ms": self.duration_ms,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }

    @property
    def has_patterns(self) -> bool:
        return len(self.patterns) > 0


async def should_run_pattern_discovery(manager: MemoryManager) -> bool:
    """Gate check: only run if memory system is mature enough.

    Conditions (all must be true):
    1. At least _MIN_MEMORY_COUNT memories exist
    2. Consolidation has run at least _MIN_CONSOLIDATION_COUNT times
    """
    if not manager.has_relational or not manager.has_vector:
        return False

    from myrm_agent_harness.toolkits.memory.types import MemoryType

    total = 0
    for mt in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
        with contextlib.suppress(Exception):
            total += await manager.count_memories(mt)

    if total < _MIN_MEMORY_COUNT:
        return False

    raw_count = await manager.get_profile_attribute(_PROFILE_KEY_CONSOLIDATION_COUNT)
    consolidation_count = int(raw_count) if raw_count else 0
    return consolidation_count >= _MIN_CONSOLIDATION_COUNT


async def increment_consolidation_count(manager: MemoryManager) -> None:
    """Increment the persistent consolidation counter after a successful consolidation."""
    if not manager.has_relational:
        return
    raw = await manager.get_profile_attribute(_PROFILE_KEY_CONSOLIDATION_COUNT)
    current = int(raw) if raw else 0
    await manager.set_profile_attribute(_PROFILE_KEY_CONSOLIDATION_COUNT, str(current + 1))


_SYSTEM_PROMPT = """You are a behavioral pattern analyst. Given a user's accumulated memories, consolidation insights, and knowledge claims, identify cross-cycle behavioral patterns the user may not be aware of.

Focus on:
1. **Recurring work habits** — repeated actions, schedules, or routines visible across multiple sessions
2. **Knowledge evolution** — topics where the user's understanding has shifted over time
3. **Unresolved threads** — questions, concerns, or tasks that appear repeatedly without closure
4. **Preference drift** — changes in tool choices, frameworks, or approaches over time
5. **Blind spots** — important areas that appear in context but the user never directly addresses

## Rules
- Only report patterns supported by multiple memories (not single observations).
- Be specific: cite time ranges, frequencies, or concrete examples from the evidence.
- Mark durability: "emerging" (seen in recent 1-2 cycles), "established" (3+ cycles), "declining" (was active, now fading).
- Provide actionable suggestions where appropriate (the agent will present these proactively).
- Keep the original language of the memories (Chinese stays Chinese, English stays English).
- Maximum 5 patterns per analysis.
- Do NOT invent patterns not supported by the evidence.

## Output
A structured JSON with `patterns` (list of DiscoveredPattern) and `meta_observation` (one-sentence overall trajectory).
"""


def _build_discovery_prompt(
    memories: Sequence[AnyMemory],
    insights: Sequence[str],
    claims: Sequence[str],
    today: str,
) -> str:
    lines = [f"Analysis date: {today}", ""]

    lines.append("## Recent Memories (sorted by recency)")
    for mem in memories[:100]:
        created = mem.created_at.strftime("%Y-%m-%d")
        lines.append(f"- [{created}] ({mem.memory_type}) {mem.content[:200]}")
    lines.append("")

    if insights:
        lines.append("## Consolidation Insights (from past maintenance cycles)")
        for ins in insights:
            lines.append(f"- {ins}")
        lines.append("")

    if claims:
        lines.append("## Knowledge Claims (from claim graph)")
        for cl in claims[:30]:
            lines.append(f"- {cl}")
        lines.append("")

    lines.append("Analyze these memories and identify cross-cycle behavioral patterns.")
    return "\n".join(lines)


async def _collect_insights(manager: MemoryManager, limit: int = 30) -> list[str]:
    """Collect consolidation insights stored as semantic memories tagged 'consolidation-insight'."""
    try:
        results = await manager.search(
            "consolidation insight pattern observation",
            limit=limit,
        )
        return [r.memory.content for r in results if "consolidation-insight" in getattr(r.memory, "tags", [])]
    except Exception as exc:
        logger.warning("Pattern discovery: failed to collect insights: %s", exc)
        return []


async def _collect_claims(manager: MemoryManager, limit: int = 30) -> list[str]:
    """Collect high-level claims from the claim graph if available."""
    if not manager.has_graph:
        return []
    try:
        graph = manager._graph
        if graph is None:
            return []
        nodes = await graph.find_nodes(labels=["Claim"], filters={}, limit=limit)
        return [str(n.properties.get("content", "")) for n in nodes if n.properties.get("content")]
    except Exception as exc:
        logger.warning("Pattern discovery: failed to collect claims: %s", exc)
        return []


def _compute_memory_set_hash(memories: Sequence[AnyMemory]) -> str:
    """Deterministic hash of the memory ID set for change detection."""
    ids = sorted(m.id for m in memories)
    return hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]


async def run_pattern_discovery(
    manager: MemoryManager,
    llm: BaseChatModel,
) -> PatternReport:
    """Execute a pattern discovery cycle.

    1. Gate check (memory count + consolidation count)
    2. Collect recent memories; skip if memory set unchanged since last run
    3. Collect consolidation insights, claims
    4. LLM analysis → structured patterns
    5. Persist patterns as episodic events + update timestamp + hash
    """
    start = datetime.now(UTC)

    if not await should_run_pattern_discovery(manager):
        return PatternReport(skipped=True, skip_reason="memory system not yet mature enough")

    from myrm_agent_harness.toolkits.memory.types import MemoryType

    all_memories: list[AnyMemory] = []
    for mt in (MemoryType.SEMANTIC, MemoryType.EPISODIC):
        try:
            mems = await manager.list_memories(mt, limit=200)
            all_memories.extend(mems)
        except Exception as exc:
            logger.warning("Pattern discovery: failed to list %s: %s", mt.value, exc)

    all_memories.sort(key=lambda m: m.created_at, reverse=True)
    memory_count = len(all_memories)

    current_hash = _compute_memory_set_hash(all_memories)
    if manager.has_relational:
        prev_hash = await manager.get_profile_attribute(_PROFILE_KEY_MEMORY_SET_HASH)
        if prev_hash and prev_hash == current_hash:
            logger.info("Pattern discovery: memory set unchanged, skipping LLM call")
            return PatternReport(
                memory_count=memory_count,
                skipped=True,
                skip_reason="memory set unchanged since last discovery",
            )

    insights = await _collect_insights(manager)
    claims = await _collect_claims(manager)

    today = start.strftime("%Y-%m-%d")
    user_prompt = _build_discovery_prompt(all_memories, insights, claims, today)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured_llm = llm.with_structured_output(PatternDiscoveryResponse)
        response: PatternDiscoveryResponse = await structured_llm.ainvoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
        )
    except Exception as exc:
        logger.warning("Pattern discovery LLM call failed: %s", exc)
        elapsed = (datetime.now(UTC) - start).total_seconds() * 1000
        return PatternReport(
            memory_count=memory_count,
            insight_count=len(insights),
            duration_ms=elapsed,
            skipped=True,
            skip_reason=f"LLM call failed: {exc}",
        )

    valid_patterns = [p for p in response.patterns if p.confidence >= 0.5][:5]

    if valid_patterns:
        await _persist_patterns(manager, valid_patterns, response.meta_observation)

    await _update_discovery_timestamp(manager, start)
    if manager.has_relational:
        with contextlib.suppress(Exception):
            await manager.set_profile_attribute(_PROFILE_KEY_MEMORY_SET_HASH, current_hash)

    elapsed = (datetime.now(UTC) - start).total_seconds() * 1000
    report = PatternReport(
        patterns=tuple(valid_patterns),
        meta_observation=response.meta_observation,
        memory_count=memory_count,
        insight_count=len(insights),
        duration_ms=elapsed,
    )

    logger.info(
        "Pattern discovery complete: patterns=%d memory_count=%d insights=%d (%.0fms)",
        len(valid_patterns),
        memory_count,
        len(insights),
        elapsed,
    )
    return report


def _is_promotable_to_rule(pattern: DiscoveredPattern) -> bool:
    """Return True if a pattern meets the threshold for ProceduralRule promotion.

    Promotion criteria (all must be satisfied):
    - durability == ESTABLISHED: pattern has been observed across 3+ cycles
    - confidence >= 0.8: LLM is highly confident in the pattern
    - actionable_suggestion is non-empty: there is a concrete action to encode
    - pattern type is habit/preference (description + actionable_suggestion are action-oriented)

    Patterns about "knowledge evolution", "unresolved threads", or "blind spots"
    typically lack a concrete trigger→action mapping and are excluded via the
    actionable_suggestion gate.
    """
    return (
        pattern.durability == PatternDurability.ESTABLISHED
        and pattern.confidence >= _RULE_PROMOTION_MIN_CONFIDENCE
        and bool(pattern.actionable_suggestion.strip())
    )


async def _promote_patterns_to_rules(
    manager: MemoryManager,
    patterns: list[DiscoveredPattern],
) -> int:
    """Promote qualifying patterns to ProceduralRule (pending approval).

    Uses manager.store() without _bypass_approval so the write_service routes
    the rule through the standard Pending review queue when approval_required=True.
    Returns the count of rules successfully queued for promotion.
    """
    if not manager.has_relational:
        return 0

    from myrm_agent_harness.toolkits.memory.types import ProceduralMemory, RuleSource

    promotable = [p for p in patterns if _is_promotable_to_rule(p)]
    if not promotable:
        return 0

    promoted = 0
    for pattern in promotable:
        try:
            rule = ProceduralMemory(
                content=pattern.title,
                trigger=pattern.description,
                action=pattern.actionable_suggestion,
                reasoning=pattern.evidence_summary,
                source=RuleSource.AGENT_SELF,
                priority=10,
            )
            await manager.store(rule)
            promoted += 1
            logger.info(
                "Pattern promoted to ProceduralRule (pending approval): %r (confidence=%.2f)",
                pattern.title,
                pattern.confidence,
            )
        except Exception as exc:
            logger.warning(
                "Failed to promote pattern %r to ProceduralRule: %s",
                pattern.title,
                exc,
            )

    return promoted


async def _persist_patterns(
    manager: MemoryManager,
    patterns: list[DiscoveredPattern],
    meta_observation: str,
) -> None:
    """Store discovered patterns as episodic memory events for auditability and Heartbeat injection.

    Also promotes high-confidence ESTABLISHED patterns to ProceduralRule via the
    standard Pending approval queue, closing the loop between pattern discovery and
    actionable agent behavior.
    """
    if not manager.has_vector:
        return

    summary_parts = []
    for p in patterns:
        suggestion = f" Suggestion: {p.actionable_suggestion}" if p.actionable_suggestion else ""
        summary_parts.append(f"[{p.durability.value}] {p.title}: {p.description}{suggestion}")

    if meta_observation:
        summary_parts.append(f"Overall: {meta_observation}")

    content = "\n".join(summary_parts)
    try:
        await manager.add_event(
            content=content,
            event_type="pattern_discovery",
            related_entities=["memory_system", "behavioral_patterns"],
        )
    except Exception as exc:
        logger.warning("Failed to persist pattern discovery event: %s", exc)

    promoted = await _promote_patterns_to_rules(manager, patterns)
    if promoted:
        logger.info("Pattern discovery: %d pattern(s) queued for ProceduralRule promotion", promoted)


async def _update_discovery_timestamp(manager: MemoryManager, ts: datetime) -> None:
    """Record when pattern discovery last ran."""
    if not manager.has_relational:
        return
    try:
        await manager.set_profile_attribute(_PROFILE_KEY_LAST_PATTERN_DISCOVERY, ts.isoformat())
    except Exception as exc:
        logger.warning("Failed to update pattern discovery timestamp: %s", exc)


async def get_last_pattern_discovery_at(manager: MemoryManager) -> datetime | None:
    """Read the last pattern discovery timestamp."""
    if not manager.has_relational:
        return None
    raw = await manager.get_profile_attribute(_PROFILE_KEY_LAST_PATTERN_DISCOVERY)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


async def get_recent_patterns(manager: MemoryManager, limit: int = 5) -> list[str]:
    """Retrieve recently discovered patterns for Heartbeat injection.

    Filters episodic events by event_type=pattern_discovery via vector scroll,
    avoiding unreliable semantic search.
    """
    if not manager.has_vector:
        return []
    try:
        vector = manager._vector
        if vector is None:
            return []
        docs, _ = await vector.scroll(
            manager._config.episodic_collection,
            limit=limit,
            filters={"event_type": "pattern_discovery"},
        )
        return [d.content for d in docs if d.content]
    except Exception:
        return []
