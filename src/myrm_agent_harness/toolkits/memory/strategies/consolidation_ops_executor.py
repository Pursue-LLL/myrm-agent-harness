"""Atomic operation execution and audit logging for memory consolidation.

[INPUT]
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.config::ConsolidationConfig (POS: consolidation configuration)
- strategies.consolidation_models::* (POS: consolidation operations and data contracts)

[OUTPUT]
- execute_operations: Executes atomic merge/correct/update operations against memory storage
- record_consolidation_event: Stores audit trail of consolidation into episodic memory

[POS]
Executes operations against memory primitives with transactional care, conflict routing,
and deterministic three-state merge arbitration.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryProtectedError
from myrm_agent_harness.toolkits.memory.strategies.consolidation_models import (
    ConflictCallback,
    ConflictContext,
    ConsolidationOp,
    ConsolidationStats,
    CorrectOp,
    MergeOp,
    UpdateContentOp,
)
from myrm_agent_harness.toolkits.memory.strategies.merger import (
    DeterministicThreeStateMerger,
    MergeState,
)
from myrm_agent_harness.toolkits.memory.strategies.named_entity_guard import (
    NamedEntityGuard,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import ConsolidationConfig
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.types import AnyMemory

logger = logging.getLogger(__name__)


def filter_and_guard_operations(
    raw_ops: Sequence[ConsolidationOp],
    memories: Sequence[AnyMemory],
    id_map: dict[str, str],
) -> tuple[list[ConsolidationOp], int]:
    """Filter operations by Rubric score and deterministic NamedEntityGuard verification & self-healing."""
    valid_ops: list[ConsolidationOp] = []
    guard_patched_count = 0
    entity_guard = NamedEntityGuard()
    content_by_id: dict[str, str] = {m.id: m.content for m in memories}
    for short_id, full_id in id_map.items():
        if full_id in content_by_id:
            content_by_id[short_id] = content_by_id[full_id]

    for op in raw_ops:
        total_score = (op.accuracy_score * 0.4) + (op.anti_fragmentation_score * 0.3) + (op.redundancy_score * 0.3)
        if total_score < 0.7:
            logger.info(
                "Consolidation op %s rejected by Rubric (Score: %.2f). Reason: %s",
                op.action,
                total_score,
                op.reasoning,
            )
            continue

        source_texts: list[str] = []
        consolidated_text = ""
        if isinstance(op, MergeOp):
            source_texts = [content_by_id[sid] for sid in op.source_ids if sid in content_by_id]
            consolidated_text = op.merged_content
            if not source_texts or len(source_texts) < 2:
                logger.warning(
                    "MergeOp rejected: insufficient valid source_ids in active memories (found %d, requested %s)",
                    len(source_texts),
                    op.source_ids,
                )
                continue
        elif isinstance(op, CorrectOp):
            source_texts = [content_by_id[op.memory_id]] if op.memory_id in content_by_id else []
            consolidated_text = op.corrected_content
            if not source_texts:
                logger.warning(
                    "CorrectOp rejected: target memory_id not found in active memories: %s",
                    op.memory_id,
                )
                continue
        elif isinstance(op, UpdateContentOp):
            source_texts = [content_by_id[op.memory_id]] if op.memory_id in content_by_id else []
            consolidated_text = op.new_content
            if not source_texts:
                logger.warning(
                    "UpdateContentOp rejected: target memory_id not found in active memories: %s",
                    op.memory_id,
                )
                continue

        guard_verdict = entity_guard.verify_consolidation(
            source_texts=source_texts,
            consolidated_text=consolidated_text,
            op_action=op.action,
            reasoning=op.reasoning,
        )

        if not guard_verdict.is_valid:
            # Deterministic self-healing for MergeOp: append missing critical entities
            if isinstance(op, MergeOp) and guard_verdict.missing_entities:
                patched_content = entity_guard.patch_with_missing_entities(
                    op.merged_content, guard_verdict.missing_entities
                )
                re_verdict = entity_guard.verify_consolidation(
                    source_texts=source_texts,
                    consolidated_text=patched_content,
                    op_action=op.action,
                    reasoning=op.reasoning,
                )
                if re_verdict.is_valid:
                    logger.info(
                        "Consolidation MergeOp auto-patched with %d missing technical entities: %s",
                        len(guard_verdict.missing_entities),
                        guard_verdict.rejection_code,
                    )
                    op = op.model_copy(update={"merged_content": patched_content})
                    valid_ops.append(op)
                    guard_patched_count += 1
                    continue

            logger.warning(
                "Consolidation op %s rejected by NamedEntityGuard (%s). Reason: %s",
                op.action,
                guard_verdict.rejection_code,
                guard_verdict.reason,
            )
            continue

        valid_ops.append(op)

    return valid_ops, guard_patched_count


async def execute_operations(
    ops: list[ConsolidationOp],
    manager: MemoryManager,
    id_map: dict[str, str] | None = None,
    *,
    on_conflict: ConflictCallback | None = None,
    config: ConsolidationConfig | None = None,
) -> ConsolidationStats:
    """Execute atomic consolidation operations against memory store."""
    from myrm_agent_harness.toolkits.memory.types import (
        ConflictResolution,
        MemoryType,
        SemanticMemory,
    )

    stats = ConsolidationStats(total_processed=len(ops))

    def resolve(sid: str) -> str:
        if id_map is not None:
            return id_map.get(sid, sid)
        return sid

    importance_thr = config.conflict_importance_threshold if config else 0.6
    confidence_thr = config.conflict_confidence_threshold if config else 0.85

    for op in ops:
        try:
            if isinstance(op, MergeOp):
                new_mem = SemanticMemory(
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
                        await manager.update_memory(
                            full_id,
                            importance=0.05,
                            metadata={"consolidated": True},
                            allow_protected=False,
                        )
                        stats.affected_ids.append(full_id)
                    except MemoryProtectedError:
                        logger.info("Consolidation demote skipped protected memory %s", full_id)
                    except Exception as e:
                        logger.warning("Consolidation demote failed for %s: %s", full_id, e)
                stats.merged += 1

            elif isinstance(op, CorrectOp):
                full_id = resolve(op.memory_id)
                existing = await manager.get_memory(full_id)
                if existing is None:
                    logger.warning("Consolidation: memory %s not found", full_id)
                    continue
                if getattr(existing, "is_user_protected", False):
                    logger.info("Consolidation: skipped user-protected memory %s", full_id)
                    continue

                should_route = (
                    on_conflict is not None and op.importance >= importance_thr and op.accuracy_score < confidence_thr
                )

                if should_route:
                    assert on_conflict is not None
                    ctx = ConflictContext(
                        old_memory_id=full_id,
                        old_content=getattr(existing, "content", ""),
                        new_content=op.corrected_content,
                        accuracy_score=op.accuracy_score,
                        importance=op.importance,
                        merge_suggestion=op.corrected_content,
                        memory_type=getattr(existing, "memory_type", MemoryType.SEMANTIC),
                    )
                    resolution = await on_conflict(ctx)
                    if resolution == ConflictResolution.PENDING:
                        stats.routed_to_user += 1
                        continue
                    if resolution == ConflictResolution.KEEP_OLD:
                        continue
                    if resolution == ConflictResolution.DISCARD_BOTH:
                        await manager.update_memory(full_id, importance=0.01, allow_protected=False)
                        stats.affected_ids.append(full_id)
                        stats.corrected += 1
                        continue
                    # KEEP_NEW or MERGE: proceed to execute the correction below

                merger = DeterministicThreeStateMerger()
                merge_dec = merger.evaluate(
                    existing=existing,
                    candidate_content=op.corrected_content,
                    candidate_evidence=getattr(existing, "evidence", []),
                )

                if merge_dec.state == MergeState.CONFLICT:
                    logger.info(
                        "Consolidation: conflict detected for %s; retaining both with decayed confidence",
                        full_id,
                    )
                    if isinstance(existing, SemanticMemory):
                        await manager.update_memory(
                            full_id,
                            confidence=merge_dec.updated_confidence or 0.35,
                            allow_protected=False,
                        )
                        counterpart = SemanticMemory(
                            content=op.corrected_content,
                            importance=op.importance,
                            confidence=merge_dec.candidate_confidence or 0.35,
                            scope=existing.scope,
                        )
                        stored = await manager.store(counterpart, _bypass_approval=True)
                        stats.affected_ids.append(full_id)
                        stats.affected_ids.append(stored.id)
                        stats.updated += 1
                        continue

                if merge_dec.state == MergeState.CONFIRM:
                    if isinstance(existing, SemanticMemory) and merge_dec.updated_confidence is not None:
                        await manager.update_memory(
                            full_id,
                            confidence=merge_dec.updated_confidence,
                            allow_protected=False,
                        )
                    stats.affected_ids.append(full_id)
                    stats.updated += 1
                    continue

                if merge_dec.state == MergeState.SUPPLEMENT and merge_dec.merged_content:
                    await manager.update_memory(
                        full_id,
                        content=merge_dec.merged_content,
                        allow_protected=False,
                    )
                    stats.affected_ids.append(full_id)
                    stats.updated += 1
                    continue

                if isinstance(existing, SemanticMemory):
                    correction = await manager.correct_memory(full_id, op.corrected_content, allow_protected=False)
                    stats.corrected += 1
                    stats.affected_ids.append(full_id)
                    stats.affected_ids.append(correction.id)
                else:
                    await manager.update_memory(full_id, content=op.corrected_content, allow_protected=False)
                    stats.updated += 1
                    stats.affected_ids.append(full_id)

            elif isinstance(op, UpdateContentOp):
                full_id = resolve(op.memory_id)
                await manager.update_memory(
                    full_id,
                    content=op.new_content,
                    importance=op.importance,
                    allow_protected=False,
                )
                stats.affected_ids.append(full_id)
                stats.updated += 1

        except MemoryProtectedError:
            logger.info("Consolidation op skipped: the memory is user-protected")
        except Exception as e:
            logger.warning("Consolidation op failed: %s: %s", type(e).__name__, e)
            stats.errors += 1

    return stats


async def record_consolidation_event(manager: MemoryManager, stats: ConsolidationStats) -> None:
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
        await manager.add_event(
            content=summary,
            event_type="consolidation",
            related_entities=["memory_system"],
        )
    except Exception as e:
        logger.warning("Failed to record consolidation event: %s", e)


__all__ = [
    "execute_operations",
    "filter_and_guard_operations",
    "record_consolidation_event",
]
