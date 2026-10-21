"""Post-compaction archive refetch loop guard.

[INPUT]
- tracking.task_metrics::get_task_metrics (POS: task-scoped metrics accessor)
- pipeline.base::BaseProcessor, ProcessorContext (POS: processor base)

[OUTPUT]
- PostCompactionRefetchGuardProcessor: inject one tail hint when archive refetch loops

[POS]
Pipeline processor that discourages repeated archive restores for the same path after compaction.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

_REFETCH_GUARD_METADATA_KEY = "post_compaction_refetch_guard_injected"
_LOOP_WINDOW = 6
_LOOP_THRESHOLD = 2


class PostCompactionRefetchGuardProcessor(BaseProcessor):
    """Inject a one-shot tail hint when archive refetch loops are detected."""

    @property
    def name(self) -> str:
        return "post_compaction_refetch_guard"

    async def should_process(self, context: ProcessorContext) -> bool:
        if context.tokens_saved <= 0 or context.chat_id is None:
            return False
        return context.metadata.get(_REFETCH_GUARD_METADATA_KEY) is not True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        chat_id = context.chat_id
        if chat_id is None:
            return context

        from myrm_agent_harness.agent.context_management.tracking.task_metrics import get_task_metrics

        metrics = get_task_metrics(chat_id)
        if metrics is None:
            return context

        recent = metrics.refetch_events[-_LOOP_WINDOW:]
        archive_counts: dict[str, int] = {}
        for event in recent:
            if event.reason != "archive_reference_read":
                continue
            archive_path = event.archive_path.strip()
            if not archive_path:
                continue
            archive_counts[archive_path] = archive_counts.get(archive_path, 0) + 1

        repeated_paths = [path for path, count in archive_counts.items() if count >= _LOOP_THRESHOLD]
        if not repeated_paths:
            return context

        sample_path = repeated_paths[0]
        hint = (
            "[Context recovery hint] Repeated archive restores were detected for the same path. "
            f"Prefer the existing summary or a single targeted range read for `{sample_path}` "
            "instead of restoring the same archive again."
        )
        context.messages = [*context.messages, SystemMessage(content=hint)]
        context.metadata[_REFETCH_GUARD_METADATA_KEY] = True
        logger.info("[PostCompactionRefetchGuard] injected hint for %s", sample_path)
        return context
