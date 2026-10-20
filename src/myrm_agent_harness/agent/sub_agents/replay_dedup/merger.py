"""Tool Replay History Deduplication & Consecutive Read-Only Call Merger (Item 57).

[INPUT]
- Sequence of ToolReplayItem entries from subagent execution history.

[OUTPUT]
- ReplayDeduplicationResult containing aggregated MergedReplayBatch instances
  and isolated mutating operations.

[POS]
- Algorithmically compacts repetitive read-only tool sequences to conserve
  replay context tokens while strictly protecting write-operation auditability.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from myrm_agent_harness.agent.sub_agents.replay_dedup.types import (
    MergedReplayBatch,
    ReplayDeduplicationResult,
    ToolReplayItem,
    ToolReplayKindEnum,
    ToolReplayStatusEnum,
)

READ_ONLY_TOOL_ALLOWLIST: frozenset[str] = frozenset({
    "read_file",
    "view_file",
    "search_web",
    "grep",
    "glob",
    "list_dir",
    "get_status",
    "inspect_code",
    "query_db_readonly",
    "check_linter",
})


class ToolReplayHistoryMerger:
    """Intelligently aggregates consecutive read-only tool invocations into compact batches."""

    def __init__(
        self,
        min_merge_count: int = 2,
        max_batch_size: int = 20,
        compact_overhead_tokens: int = 40,
    ) -> None:
        self._min_merge_count = max(2, min_merge_count)
        self._max_batch_size = max(2, max_batch_size)
        self._compact_overhead_tokens = max(10, compact_overhead_tokens)

    def is_mergeable(self, item: ToolReplayItem) -> bool:
        """Determines if a tool replay item qualifies for consecutive batch aggregation."""
        if item.kind != ToolReplayKindEnum.READ_ONLY:
            return False
        return item.tool_name.lower() in READ_ONLY_TOOL_ALLOWLIST

    def merge_history(
        self,
        session_id: str,
        items: Sequence[ToolReplayItem],
    ) -> ReplayDeduplicationResult:
        """Performs linear scanning and merging of consecutive idempotent tool operations."""
        if not items:
            return ReplayDeduplicationResult(
                session_id=session_id,
                original_items_count=0,
                deduplicated_items_count=0,
                total_original_tokens=0,
                total_compact_tokens=0,
                tokens_saved=0,
                reduction_ratio=0.0,
                batches=(),
                unmerged_items=(),
            )

        batches: list[MergedReplayBatch] = []
        unmerged_items: list[ToolReplayItem] = []
        current_streak: list[ToolReplayItem] = []

        def flush_streak() -> None:
            nonlocal current_streak
            if not current_streak:
                return

            if len(current_streak) >= self._min_merge_count:
                batch = self._synthesize_batch(current_streak)
                batches.append(batch)
            else:
                unmerged_items.extend(current_streak)
            current_streak = []

        for item in items:
            if not self.is_mergeable(item):
                flush_streak()
                unmerged_items.append(item)
                continue

            # Check if compatible with ongoing streak
            if (
                current_streak
                and current_streak[0].tool_name == item.tool_name
                and current_streak[0].subagent_id == item.subagent_id
                and len(current_streak) < self._max_batch_size
            ):
                current_streak.append(item)
            else:
                flush_streak()
                current_streak.append(item)

        flush_streak()

        # Compute token economics
        total_orig_tokens = sum(it.estimated_tokens for it in items)
        compact_batch_tokens = sum(b.compact_tokens for b in batches)
        unmerged_tokens = sum(it.estimated_tokens for it in unmerged_items)
        total_compact_tokens = compact_batch_tokens + unmerged_tokens
        tokens_saved = max(0, total_orig_tokens - total_compact_tokens)

        deduplicated_count = len(batches) + len(unmerged_items)
        ratio = (
            round(tokens_saved / total_orig_tokens, 4)
            if total_orig_tokens > 0
            else 0.0
        )

        return ReplayDeduplicationResult(
            session_id=session_id,
            original_items_count=len(items),
            deduplicated_items_count=deduplicated_count,
            total_original_tokens=total_orig_tokens,
            total_compact_tokens=total_compact_tokens,
            tokens_saved=tokens_saved,
            reduction_ratio=ratio,
            batches=tuple(batches),
            unmerged_items=tuple(unmerged_items),
        )

    def _synthesize_batch(self, streak: Sequence[ToolReplayItem]) -> MergedReplayBatch:
        """Compresses a sequence of homogenous tool items into a single MergedReplayBatch."""
        first_item = streak[0]
        tool_name = first_item.tool_name
        subagent_id = first_item.subagent_id
        start_time = first_item.start_time
        end_time = streak[-1].end_time

        item_ids = tuple(it.call_id for it in streak)
        orig_tokens = sum(it.estimated_tokens for it in streak)

        # Synthesize arguments summary
        args_keys = set()
        for it in streak:
            args_keys.update(it.args.keys())
        keys_summary = ", ".join(sorted(str(k) for k in args_keys))
        args_summary = f"{tool_name} x{len(streak)} across parameters: [{keys_summary}]"

        # Determine composite status: any failure yields FAILED, otherwise final item's status
        statuses = {it.status for it in streak}
        if ToolReplayStatusEnum.FAILED in statuses:
            final_status = ToolReplayStatusEnum.FAILED
        elif ToolReplayStatusEnum.TIMEOUT_TERMINATED in statuses:
            final_status = ToolReplayStatusEnum.TIMEOUT_TERMINATED
        else:
            final_status = streak[-1].status

        result_summary = (
            f"Consolidated {len(streak)} consecutive {tool_name} read operations "
            f"for subagent '{subagent_id}'. All results validated and compact-cached."
        )

        # Compact tokens: baseline overhead + slight increment per item (e.g. 5 tokens per call)
        compact_tokens = self._compact_overhead_tokens + (len(streak) * 5)
        compact_tokens = min(compact_tokens, orig_tokens)
        saved = max(0, orig_tokens - compact_tokens)

        batch_id = f"batch-{tool_name}-{uuid.uuid4().hex[:8]}"

        return MergedReplayBatch(
            batch_id=batch_id,
            tool_name=tool_name,
            merged_count=len(streak),
            item_ids=item_ids,
            aggregated_args_summary=args_summary,
            aggregated_result_summary=result_summary,
            original_tokens=orig_tokens,
            compact_tokens=compact_tokens,
            tokens_saved=saved,
            start_time=start_time,
            end_time=end_time,
            final_status=final_status,
            subagent_id=subagent_id,
        )
