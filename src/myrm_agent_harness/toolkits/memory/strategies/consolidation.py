"""Cross-session memory consolidation — retrospective reflection on accumulated memories.

[INPUT]
- memory.config::ConsolidationConfig (POS: consolidation configuration)
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.types::AnyMemory (POS: memory data models)
- strategies.consolidation_models::* (POS: Domain models, DTOs, and protocol callback types for cross-session memory consolidation)
- strategies.consolidation_prompts::* (POS: Prompts and payload compression helpers for memory consolidation)
- strategies.consolidation_ops_executor::* (POS: Executes operations against memory primitives with transactional care, conflict routing, and deterministic three-state merge arbitration)
- strategies.named_entity_guard::NamedEntityGuard (POS: 确定性命名实体与关键技术标识符守卫)

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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.memory.strategies.consolidation_models import (
    _PROFILE_KEY_LAST_CONSOLIDATED,
    ConflictCallback,
    ConflictContext,
    ConsolidationAction,
    ConsolidationCompleteCallback,
    ConsolidationOp,
    ConsolidationResponse,
    ConsolidationStats,
    CorrectOp,
    MergeOp,
    UpdateContentOp,
)
from myrm_agent_harness.toolkits.memory.strategies.consolidation_ops_executor import (
    execute_operations,
    filter_and_guard_operations,
    record_consolidation_event,
)
from myrm_agent_harness.toolkits.memory.strategies.consolidation_prompts import (
    _SYSTEM_PROMPT,
    _build_id_map,
    _build_user_prompt,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.protocols.vector import FilterDict
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)

# Aliases for backward-compatibility with tests / internal references
_execute_operations = execute_operations
_record_consolidation_event = record_consolidation_event


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
    """Find similar existing memories so a single new memory can be consolidated."""
    try:
        from myrm_agent_harness.toolkits.memory.types import ClaimMemory

        results = await manager.search(memory.content, limit=max_similar + 1, track_access=False)
        similar = [r.memory for r in results if r.memory.id != memory.id and not isinstance(r.memory, ClaimMemory)][
            :max_similar
        ]
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
    on_complete: ConsolidationCompleteCallback | None = None,
) -> ConsolidationStats:
    """Execute a full consolidation cycle."""
    start = datetime.now(UTC)

    last = await get_last_consolidated_at(manager)
    if last is not None:
        elapsed_hours = (datetime.now(UTC) - last).total_seconds() / 3600
        if elapsed_hours < config.soft_lock_hours:
            logger.info(
                "Consolidation skipped: soft lock (%.1fh < %.1fh)",
                elapsed_hours,
                config.soft_lock_hours,
            )
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
        raw_response = await structured_llm.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        )
        if isinstance(raw_response, dict):
            response = ConsolidationResponse.model_validate(raw_response)
        elif isinstance(raw_response, ConsolidationResponse):
            response = raw_response
        else:
            raise TypeError(f"Unexpected response type from structured LLM: {type(raw_response)}")

        valid_ops, guard_patched_count = filter_and_guard_operations(response.operations, memories, id_map)
        parsed = ConsolidationResponse(operations=valid_ops, insights=response.insights)
    except Exception as e:
        logger.warning("Consolidation LLM call failed: %s", e)
        return ConsolidationStats(errors=1, input_count=input_count, enriched_count=enriched_count)

    if not parsed.operations and not parsed.insights:
        logger.info(
            "Consolidation: no operations needed (input=%d, enriched=%d)",
            input_count,
            enriched_count,
        )
        await _update_timestamp(manager, start)
        empty_stats = ConsolidationStats(input_count=input_count, enriched_count=enriched_count)
        if on_complete is not None:
            try:
                await on_complete(empty_stats)
            except Exception as exc:
                logger.warning("Consolidation complete hook failed (non-fatal): %s", exc)
        return empty_stats

    stats = (
        await execute_operations(parsed.operations, manager, id_map, on_conflict=on_conflict, config=config)
        if parsed.operations
        else ConsolidationStats()
    )
    elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
    stats.duration_ms = elapsed_ms
    stats.input_count = input_count
    stats.enriched_count = enriched_count
    stats.insights = tuple(parsed.insights)
    stats.guard_patched = guard_patched_count

    await record_consolidation_event(manager, stats)
    if parsed.insights:
        await _persist_insights(manager, parsed.insights)

    should_advance_timestamp = not stats.aborted and not (
        stats.errors > 0 and (stats.merged + stats.corrected + stats.updated == 0)
    )
    if should_advance_timestamp:
        await _update_timestamp(manager, start)
    else:
        logger.warning(
            "Consolidation skipped timestamp advancement (aborted=%s, errors=%d)",
            stats.aborted,
            stats.errors,
        )

    logger.info(
        "Consolidation complete: input=%d, enriched=%d, merged=%d, corrected=%d, updated=%d, errors=%d, guard_patched=%d, insights=%d (%.0fms)",
        input_count,
        enriched_count,
        stats.merged,
        stats.corrected,
        stats.updated,
        stats.errors,
        stats.guard_patched,
        len(parsed.insights),
        elapsed_ms,
    )
    if on_complete is not None:
        try:
            await on_complete(stats)
        except Exception as exc:
            logger.warning("Consolidation complete hook failed (non-fatal): %s", exc)
    return stats


_SCROLL_MULTIPLIER = 3


async def _fetch_incremental_memories(
    manager: MemoryManager, since: datetime | None, max_count: int
) -> list[AnyMemory]:
    """Fetch memories created after `since`, up to `max_count`."""
    from myrm_agent_harness.toolkits.memory._internal.storage import (
        doc_to_episodic,
        doc_to_semantic,
    )

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
                scroll_filters: FilterDict = {
                    "primary_namespace": manager.namespaces,
                }
                if manager.user_id is not None:
                    scroll_filters["user_id"] = manager.user_id
                docs, _ = await v.scroll(
                    collection,
                    limit=scroll_limit,
                    filters=scroll_filters,
                )
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


_MIN_INSIGHT_LENGTH = 10
_INSIGHT_IMPORTANCE_THRESHOLD = 0.6


async def _persist_insights(manager: MemoryManager, insights: list[str]) -> None:
    """Persist quality insights as SemanticMemory with implicit preference type."""
    if not manager.has_vector:
        return

    from myrm_agent_harness.toolkits.memory.types import SemanticMemory

    stored = 0
    for text in insights:
        text = text.strip()
        if len(text) < _MIN_INSIGHT_LENGTH:
            continue
        mem = SemanticMemory(
            user_id=manager.user_id if manager.user_id is not None else "default",
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


__all__ = [
    "ConflictCallback",
    "ConflictContext",
    "ConsolidationAction",
    "ConsolidationCompleteCallback",
    "ConsolidationOp",
    "ConsolidationResponse",
    "ConsolidationStats",
    "CorrectOp",
    "MergeOp",
    "UpdateContentOp",
    "_PROFILE_KEY_LAST_CONSOLIDATED",
    "_SYSTEM_PROMPT",
    "_build_id_map",
    "_build_user_prompt",
    "_execute_operations",
    "_record_consolidation_event",
    "execute_operations",
    "filter_and_guard_operations",
    "get_last_consolidated_at",
    "record_consolidation_event",
    "run_consolidation",
    "should_consolidate",
]
