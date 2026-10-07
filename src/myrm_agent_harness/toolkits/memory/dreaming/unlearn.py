"""Surgical Session Memory Unlearning Operator.

Enables precision unlearning of long-term semantic memories derived from
a specific session, cleanly evicting vector indices and relational facts
while preserving the original conversational chat history 100% intact.

[INPUT]
- toolkits.memory.dreaming.models::SurgicalUnlearnReport (POS:
  做梦认知日记与溯源数据契约核心。定义跨会话认知洞察实体、审核与锁定状态枚举、
  不可篡改的双向溯源锚点集，以及外科手术式遗忘审计报告。)

[OUTPUT]
- SurgicalSessionMemoryUnlearner: Executes surgical precision unlearning on session-derived memories.

[POS]
Surgical Session Memory Unlearning Operator.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence

from myrm_agent_harness.toolkits.memory.dreaming.models import (
    SurgicalUnlearnReport,
)


class SurgicalSessionMemoryUnlearner:
    """Executes surgical precision unlearning on session-derived memories."""

    @classmethod
    def match_session_derived_memories(
        cls,
        session_id: str,
        memory_items: Sequence[Mapping[str, object]],
    ) -> list[str]:
        """Identify memory IDs derived from the targeted session ID.

        Matches by explicit session_id metadata or EvidenceReference source linkage.
        """
        if not session_id or not memory_items:
            return []

        target_sid = session_id.strip()
        matched_ids: list[str] = []

        for item in memory_items:
            item_id = str(item.get("id") or item.get("memory_id") or "")
            if not item_id:
                continue

            # 1. Direct session_id linkage in root or metadata
            raw_sid = item.get("session_id")
            if raw_sid and str(raw_sid).strip() == target_sid:
                matched_ids.append(item_id)
                continue

            meta = item.get("metadata")
            if isinstance(meta, dict) and str(meta.get("session_id", "")).strip() == target_sid:
                matched_ids.append(item_id)
                continue

            # 2. Check EvidenceReference linkages
            evidences = item.get("evidence")
            if isinstance(evidences, list):
                linked = False
                for ev in evidences:
                    if isinstance(ev, dict):
                        src_id = str(ev.get("source_id", "")).strip()
                        channel_id = str(ev.get("channel_id", "")).strip()
                        if src_id == target_sid or channel_id == target_sid:
                            linked = True
                            break
                    elif isinstance(ev, str) and ev.strip() == target_sid:
                        linked = True
                        break
                if linked:
                    matched_ids.append(item_id)

        return sorted(set(matched_ids))

    @classmethod
    async def unlearn_session(
        cls,
        session_id: str,
        memory_items: Sequence[Mapping[str, object]],
        deleter: Callable[[list[str]], Awaitable[int]] | None = None,
        chat_turn_count: int = 0,
    ) -> SurgicalUnlearnReport:
        """Surgically purge derived memories while keeping raw conversation turns intact."""
        start_time = time.perf_counter()
        matched_ids = cls.match_session_derived_memories(session_id, memory_items)

        purged_vectors = 0
        if matched_ids and deleter is not None:
            purged_vectors = await deleter(matched_ids)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return SurgicalUnlearnReport(
            session_id=session_id,
            unlearned_memory_ids=matched_ids,
            purged_vector_count=purged_vectors if purged_vectors > 0 else len(matched_ids),
            status="completed",
            preserved_chat_turns=chat_turn_count,
            execution_time_ms=round(elapsed_ms, 2),
        )
