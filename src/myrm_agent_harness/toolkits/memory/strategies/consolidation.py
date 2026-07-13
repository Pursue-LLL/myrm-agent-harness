"""Cross-session memory consolidation — retrospective reflection on accumulated memories.


[INPUT]
- memory.config::ConsolidationConfig (POS: consolidation configuration)
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.types::AnyMemory (POS: memory data models)

[OUTPUT]
- run_consolidation: Cross-session consolidation (contradiction detection, redundancy merge, insight generation)
- ConsolidationStats: Consolidation result statistics

[POS]
Cross-session memory consolidation strategy. Analyzes recent memories via LLM to detect
contradictions and redundancies. Executes merge/correct/update and generates 0-3 insights
at near-zero marginal cost. Triggered by end_session() on configured intervals.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.types import AnyMemory, ConflictResolution

logger = logging.getLogger(__name__)

LLMFunc = Callable[[str, str], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ConflictContext:
    """Context passed to the conflict callback when a high-importance correction is uncertain."""

    old_memory_id: str
    old_content: str
    new_content: str
    accuracy_score: float
    importance: float
    merge_suggestion: str


ConflictCallback = Callable[[ConflictContext], Awaitable["ConflictResolution"]]

_PROFILE_KEY_LAST_CONSOLIDATED = "_system.last_consolidated_at"


class ConsolidationAction(StrEnum):
    MERGE = "merge"
    CORRECT = "correct"
    UPDATE_CONTENT = "update_content"


class MergeOp(BaseModel):
    action: str = ConsolidationAction.MERGE
    source_ids: list[str]
    merged_content: str
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    accuracy_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Score (0-1): Does the merged memory accurately reflect the underlying truth without hallucination?",
    )
    anti_fragmentation_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Score (0-1): Does this operation combine fragmented pieces into a cohesive whole?",
    )
    redundancy_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Score (0-1): Does this operation successfully eliminate duplicate or overlapping information?",
    )
    reasoning: str = Field(default="", description="Reasoning for the scores.")


class CorrectOp(BaseModel):
    action: str = ConsolidationAction.CORRECT
    memory_id: str
    corrected_content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    accuracy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    anti_fragmentation_score: float = Field(default=1.0, ge=0.0, le=1.0)
    redundancy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


class UpdateContentOp(BaseModel):
    action: str = ConsolidationAction.UPDATE_CONTENT
    memory_id: str
    new_content: str
    importance: float | None = None
    accuracy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    anti_fragmentation_score: float = Field(default=1.0, ge=0.0, le=1.0)
    redundancy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


ConsolidationOp = MergeOp | CorrectOp | UpdateContentOp


class ConsolidationStats(BaseModel):
    merged: int = 0
    corrected: int = 0
    updated: int = 0
    errors: int = 0
    routed_to_user: int = 0
    total_processed: int = 0
    duration_ms: float = 0.0
    input_count: int = 0
    enriched_count: int = 0
    insights: tuple[str, ...] = ()
    affected_ids: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """You are a memory consolidation agent. Analyze the user's memories (semantic facts, episodic events, and procedural rules) and identify:

1. **Contradictions**: Memories that conflict (e.g., "prefers Python" vs "prefers Rust")
2. **Redundancies**: Multiple memories expressing the same fact → merge into one
3. **Date conversion**: Relative dates ("yesterday", "last week") → absolute dates (YYYY-MM-DD)
4. **Enrichment**: Fragmented memories that can be combined into a richer single memory
5. **Stale corrections**: When multiple corrections exist on the same topic (indicated by `corrects:` or similar `source_error`), keep the newest correction and demote older ones via update_content (set importance to 0.05)

## Rubric (Class-First 评分标准)
Before proposing any consolidation operation, strictly evaluate it against these dimensions:
1. **准确性 (Accuracy)**: Does the merged/updated memory accurately reflect the underlying truth without hallucination?
2. **防碎片化 (Anti-fragmentation)**: Does this operation combine fragmented pieces into a cohesive, complete whole?
3. **冗余度 (Redundancy)**: Does this operation successfully eliminate duplicate or overlapping information?

## Rules
- Only output actions when there is clear evidence. Do NOT fabricate connections.
- Preserve all unique information when merging. Never discard details.
- Use absolute dates based on today's date provided below.
- Keep the original language (Chinese stays Chinese, English stays English).
- For procedural rules (type=procedural), use ONLY update_content (NOT merge or correct, since rules have structured trigger/action fields).
- Memories tagged [NEW] are recently added. Pay special attention to contradictions between [NEW] and existing memories.

## Output
Output a structured JSON object containing `operations` and `insights`.
"""


def _build_user_prompt(
    memories: Sequence[AnyMemory], today: str, id_map: dict[str, str], new_ids: frozenset[str] | None = None
) -> str:
    """Build user prompt with short IDs to save tokens (~28 tokens per memory).

    When *new_ids* is provided, memories whose ID is in the set are tagged
    ``[NEW]`` to help the LLM distinguish freshly added entries from existing ones.
    """
    reverse_map = {v: k for k, v in id_map.items()}
    lines = [f"Today's date: {today}", "", "## Memories to analyze", ""]
    for mem in memories:
        short_id = reverse_map.get(mem.id, mem.id[:8])
        tag = " [NEW]" if new_ids and mem.id in new_ids else ""
        meta_parts = [f"type={mem.memory_type}"]
        if hasattr(mem, "importance"):
            meta_parts.append(f"importance={mem.importance:.1f}")
        if hasattr(mem, "confidence"):
            meta_parts.append(f"confidence={mem.confidence:.1f}")
        meta_parts.append(f"created={mem.created_at.strftime('%Y-%m-%d %H:%M')}")
        correction_of = getattr(mem, "correction_of", None)
        if correction_of:
            corrects_short = reverse_map.get(correction_of, correction_of[:8])
            meta_parts.append(f"corrects:{corrects_short}")
        lines.append(f"[{short_id}]{tag} ({', '.join(meta_parts)})")
        if hasattr(mem, "trigger") and hasattr(mem, "action"):
            lines.append(f"  trigger: {mem.trigger}")
            lines.append(f"  action: {mem.action}")
        else:
            lines.append(f"  {mem.content}")
        source_error = getattr(mem, "source_error", None)
        if source_error:
            lines.append(f"  source_error: {source_error}")
        lines.append("")
    lines.append("Analyze these memories and output a JSON object with operations and insights.")
    return "\n".join(lines)


def _build_id_map(memories: Sequence[AnyMemory]) -> dict[str, str]:
    """Build short_id → full_id mapping. Uses first 8 chars, extends on collision."""
    id_map: dict[str, str] = {}
    used_shorts: set[str] = set()
    for mem in memories:
        short = mem.id[:8]
        length = 8
        while short in used_shorts and length < len(mem.id):
            length += 4
            short = mem.id[:length]
        id_map[short] = mem.id
        used_shorts.add(short)
    return id_map


class ConsolidationResponse(BaseModel):
    """Parsed LLM consolidation response containing operations and insights."""

    operations: list[ConsolidationOp] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)


async def _execute_operations(
    ops: list[ConsolidationOp],
    manager: MemoryManager,
    id_map: dict[str, str] | None = None,
    *,
    on_conflict: ConflictCallback | None = None,
    config: ConsolidationConfig | None = None,
) -> ConsolidationStats:
    from myrm_agent_harness.toolkits.memory.types import ConflictResolution, SemanticMemory

    stats = ConsolidationStats(total_processed=len(ops))
    resolve = (lambda sid: id_map.get(sid, sid)) if id_map else (lambda sid: sid)

    importance_thr = config.conflict_importance_threshold if config else 0.6
    confidence_thr = config.conflict_confidence_threshold if config else 0.85

    for op in ops:
        try:
            if isinstance(op, MergeOp):
                new_mem = SemanticMemory(
                    user_id=manager.user_id,
                    content=op.merged_content,
                    importance=op.importance,
                    confidence=0.9,
                    metadata={"consolidation_source": ",".join(op.source_ids)},
                )
                stored = await manager.store(new_mem, _bypass_approval=True)
                merged_id = stored.id if hasattr(stored, "id") else new_mem.id
                stats.affected_ids.append(merged_id)
                for short_id in op.source_ids:
                    full_id = resolve(short_id)
                    try:
                        await manager.update_memory(full_id, importance=0.05, metadata={"consolidated": True})
                        stats.affected_ids.append(full_id)
                    except Exception as e:
                        logger.warning("Consolidation demote failed for %s: %s", full_id, e)
                stats.merged += 1

            elif isinstance(op, CorrectOp):
                full_id = resolve(op.memory_id)
                existing = await manager.get_memory(full_id)
                if getattr(existing, "is_user_locked", False):
                    logger.info("Consolidation: skipped locked rule %s", full_id)
                    continue

                should_route = (
                    on_conflict is not None
                    and op.importance >= importance_thr
                    and op.accuracy_score < confidence_thr
                )

                if should_route:
                    ctx = ConflictContext(
                        old_memory_id=full_id,
                        old_content=getattr(existing, "content", ""),
                        new_content=op.corrected_content,
                        accuracy_score=op.accuracy_score,
                        importance=op.importance,
                        merge_suggestion=op.corrected_content,
                    )
                    resolution = await on_conflict(ctx)
                    if resolution == ConflictResolution.PENDING:
                        stats.routed_to_user += 1
                        continue
                    if resolution == ConflictResolution.KEEP_OLD:
                        continue
                    if resolution == ConflictResolution.DISCARD_BOTH:
                        await manager.update_memory(full_id, importance=0.01)
                        stats.affected_ids.append(full_id)
                        stats.corrected += 1
                        continue
                    # KEEP_NEW or MERGE: proceed to execute the correction below

                if isinstance(existing, SemanticMemory):
                    correction = await manager.correct_memory(full_id, op.corrected_content)
                    stats.corrected += 1
                    stats.affected_ids.append(full_id)
                    stats.affected_ids.append(correction.id)
                else:
                    await manager.update_memory(full_id, content=op.corrected_content)
                    stats.updated += 1
                    stats.affected_ids.append(full_id)

            elif isinstance(op, UpdateContentOp):
                full_id = resolve(op.memory_id)
                existing = await manager.get_memory(full_id)
                if getattr(existing, "is_user_locked", False):
                    logger.info("Consolidation: skipped locked rule %s", full_id)
                    continue
                await manager.update_memory(full_id, content=op.new_content, importance=op.importance)
                stats.affected_ids.append(full_id)
                stats.updated += 1

        except Exception as e:
            logger.warning("Consolidation op failed: %s: %s", type(e).__name__, e)
            stats.errors += 1

    return stats


async def get_last_consolidated_at(manager: MemoryManager) -> datetime | None:
    """Read the last consolidation timestamp from Profile store."""
    if not manager.has_relational:
        return None
    raw = await manager.get_profile_attribute(_PROFILE_KEY_LAST_CONSOLIDATED)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


async def should_consolidate(manager: MemoryManager, config: ConsolidationConfig) -> bool:
    """Check whether consolidation should run based on time gates."""
    if not config.enabled:
        return False
    last = await get_last_consolidated_at(manager)
    if last is None:
        return True
    elapsed_hours = (datetime.now(UTC) - last).total_seconds() / 3600
    return elapsed_hours >= config.interval_hours


async def _enrich_with_similar(memory: AnyMemory, manager: MemoryManager, max_similar: int = 3) -> list[AnyMemory]:
    """Find similar existing memories so a single new memory can be consolidated.

    Searches the memory store for candidates semantically related to *memory*,
    filters out the memory itself, and returns [memory] + top-N matches.
    When no candidates are found the original memory is returned alone.
    """
    try:
        results = await manager.search(memory.content, limit=max_similar + 1, track_access=False)
        similar = [r.memory for r in results if r.memory.id != memory.id][:max_similar]
        if not similar:
            return [memory]
        return [memory, *similar]
    except Exception as e:
        logger.warning("Enrich-with-similar search failed: %s", e)
        return [memory]


async def run_consolidation(
    manager: MemoryManager,
    llm: BaseChatModel,
    config: ConsolidationConfig,
    *,
    on_conflict: ConflictCallback | None = None,
) -> ConsolidationStats:
    """Execute a full consolidation cycle.

    1. Soft-lock check (skip if consolidated within soft_lock_hours)
    2. Fetch incremental memories (created after last consolidation)
    3. If only 1 new memory, enrich with similar existing memories
    4. LLM analysis → structured operations
    5. Execute operations via MemoryManager primitives (conflicts routed via on_conflict)
    6. Record consolidation event + update timestamp
    """
    start = datetime.now(UTC)

    last = await get_last_consolidated_at(manager)
    if last is not None:
        elapsed_hours = (datetime.now(UTC) - last).total_seconds() / 3600
        if elapsed_hours < config.soft_lock_hours:
            logger.info("Consolidation skipped: soft lock (%.1fh < %.1fh)", elapsed_hours, config.soft_lock_hours)
            return ConsolidationStats()

    incremental = await _fetch_incremental_memories(manager, last, config.max_memories)
    new_ids: frozenset[str] | None = None

    enriched_count = 0
    if len(incremental) == 1:
        new_ids = frozenset(m.id for m in incremental)
        memories = await _enrich_with_similar(incremental[0], manager, max_similar=config.enrich_max_similar)
        enriched_count = len(memories) - 1
    else:
        memories = incremental

    if len(memories) < 2:
        logger.info("Consolidation skipped: insufficient memories (%d)", len(memories))
        await _update_timestamp(manager, start)
        return ConsolidationStats()

    input_count = len(memories)
    id_map = _build_id_map(memories)
    today = start.strftime("%Y-%m-%d")
    user_prompt = _build_user_prompt(memories, today, id_map, new_ids=new_ids)

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        structured_llm = llm.with_structured_output(ConsolidationResponse)
        response: ConsolidationResponse = await structured_llm.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        )

        # Filter operations by Rubric score
        valid_ops = []
        for op in response.operations:
            total_score = (op.accuracy_score * 0.4) + (op.anti_fragmentation_score * 0.3) + (op.redundancy_score * 0.3)
            if total_score >= 0.7:
                valid_ops.append(op)
            else:
                logger.info(
                    "Consolidation op %s rejected by Rubric (Score: %.2f). Reason: %s",
                    op.action, total_score, op.reasoning,
                )

        parsed = ConsolidationResponse(operations=valid_ops, insights=response.insights)
    except Exception as e:
        logger.warning("Consolidation LLM call failed: %s", e)
        return ConsolidationStats(errors=1, input_count=input_count, enriched_count=enriched_count)

    if not parsed.operations and not parsed.insights:
        logger.info("Consolidation: no operations needed (input=%d, enriched=%d)", input_count, enriched_count)
        await _update_timestamp(manager, start)
        return ConsolidationStats(input_count=input_count, enriched_count=enriched_count)

    stats = (
        await _execute_operations(parsed.operations, manager, id_map, on_conflict=on_conflict, config=config)
        if parsed.operations
        else ConsolidationStats()
    )
    elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
    stats.duration_ms = elapsed_ms
    stats.input_count = input_count
    stats.enriched_count = enriched_count
    stats.insights = parsed.insights

    await _record_consolidation_event(manager, stats)
    if parsed.insights:
        await _persist_insights(manager, parsed.insights)
    await _update_timestamp(manager, start)

    logger.info(
        "Consolidation complete: input=%d, enriched=%d, merged=%d, corrected=%d, updated=%d, errors=%d, insights=%d (%.0fms)",
        input_count,
        enriched_count,
        stats.merged,
        stats.corrected,
        stats.updated,
        stats.errors,
        len(parsed.insights),
        elapsed_ms,
    )
    return stats


_SCROLL_MULTIPLIER = 3


async def _fetch_incremental_memories(
    manager: MemoryManager, since: datetime | None, max_count: int
) -> list[AnyMemory]:
    """Fetch memories created after `since`, up to `max_count`.

    Scrolls max_count * 3 documents per collection to compensate for
    non-chronological scroll ordering in vector stores, then filters
    in-memory by created_at.
    """
    from myrm_agent_harness.toolkits.memory._internal.storage import doc_to_episodic, doc_to_semantic

    all_memories: list[AnyMemory] = []
    scroll_limit = max_count * _SCROLL_MULTIPLIER

    if manager.has_vector:
        v, _ = manager._vec()
        cfg = manager.config
        for collection, converter in (
            (cfg.semantic_collection, doc_to_semantic),
            (cfg.episodic_collection, doc_to_episodic),
        ):
            try:
                docs, _ = await v.scroll(collection, limit=scroll_limit, filters={"user_id": manager.user_id})
                for doc in docs:
                    mem = converter(doc)
                    if hasattr(mem, "event_type") and mem.event_type == "consolidation":
                        continue
                    if since is None or mem.created_at > since:
                        all_memories.append(mem)
            except Exception as e:
                logger.warning("Consolidation fetch from %s failed: %s", collection, e)

    if manager.has_relational:
        try:
            rules = await manager._rel().list_rules(
                active_only=True, limit=scroll_limit, namespaces=manager._namespaces
            )
            for rule in rules:
                if since is None or rule.created_at > since:
                    all_memories.append(rule)
        except Exception as e:
            logger.warning("Consolidation fetch procedural rules failed: %s", e)

    all_memories.sort(key=lambda m: m.created_at)
    return all_memories[:max_count]


async def _update_timestamp(manager: MemoryManager, ts: datetime) -> None:
    """Persist the consolidation timestamp as a Profile attribute."""
    if not manager.has_relational:
        return
    try:
        rel = manager._rel()
        await rel.set_profile(_PROFILE_KEY_LAST_CONSOLIDATED, ts.isoformat())
    except Exception as e:
        logger.warning("Failed to update consolidation timestamp: %s", e)


async def _record_consolidation_event(manager: MemoryManager, stats: ConsolidationStats) -> None:
    """Store a consolidation summary as an EpisodicMemory for auditability.

    Embeds affected_ids into the event content so rollback can discover which
    memories were touched by this consolidation cycle.
    """
    if not manager.has_vector:
        return
    ids_csv = ",".join(stats.affected_ids) if stats.affected_ids else ""
    summary = (
        f"Memory consolidation: input {stats.input_count}, enriched {stats.enriched_count}, "
        f"merged {stats.merged}, corrected {stats.corrected}, "
        f"updated {stats.updated}, errors {stats.errors} ({stats.duration_ms:.0f}ms)"
    )
    if ids_csv:
        summary += f"\n[affected_ids:{ids_csv}]"
    try:
        await manager.add_event(content=summary, event_type="consolidation", related_entities=["memory_system"])
    except Exception as e:
        logger.warning("Failed to record consolidation event: %s", e)


_MIN_INSIGHT_LENGTH = 10
_INSIGHT_IMPORTANCE_THRESHOLD = 0.6


async def _persist_insights(manager: MemoryManager, insights: tuple[str, ...]) -> None:
    """Persist quality insights as SemanticMemory with implicit preference type.

    This activates insights that would otherwise be discarded — they flow
    into get_learned_context() via the preference query channel, enabling
    the agent to proactively reflect cross-memory observations.

    Quality gate: only insights with meaningful content (>10 chars) are stored.
    """
    if not manager.has_vector:
        return

    from myrm_agent_harness.toolkits.memory.types import SemanticMemory

    stored = 0
    for text in insights:
        text = text.strip()
        if len(text) < _MIN_INSIGHT_LENGTH:
            continue
        mem = SemanticMemory(
            user_id=manager.user_id,
            content=text,
            importance=_INSIGHT_IMPORTANCE_THRESHOLD,
            confidence=0.8,
            preference_type="implicit",
            preference_strength=0.6,
            tags=["consolidation-insight"],
        )
        try:
            await manager.store(mem, _bypass_approval=True)
            stored += 1
        except Exception as e:
            logger.warning("Failed to persist consolidation insight: %s", e)

    if stored:
        logger.info("Persisted %d consolidation insights as implicit preferences", stored)
