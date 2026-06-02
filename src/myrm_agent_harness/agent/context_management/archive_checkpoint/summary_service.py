"""Async lite-LLM archive summary scheduling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.context_management.tracking.task_metrics import get_task_metrics
from myrm_agent_harness.utils.token_estimation import (
    estimate_content_tokens,
)

from .store import ArchiveCheckpointStore
from .types import ArchiveCheckpointRecord

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.runnables.config import RunnableConfig

    from myrm_agent_harness.agent.context_management.infra.schemas import CacheTtlPruneConfig

logger = logging.getLogger(__name__)

ArchiveCheckpointNotifier = Callable[
    ["ArchiveCheckpointRecord", "RunnableConfig | None"],
    Awaitable[None],
]

_PENDING_KEYS: set[str] = set()
_PENDING_BY_CHAT: dict[str, int] = {}
_SEMAPHORE: asyncio.Semaphore | None = None
_TASKS: set[asyncio.Task[None]] = set()


def reset_archive_summary_pending_state() -> None:
    """Clear in-flight archive summary queue keys (test helper)."""
    _PENDING_KEYS.clear()
    _PENDING_BY_CHAT.clear()


class ArchiveSummaryService:
    """Bounded background archive summarization."""

    def __init__(
        self,
        *,
        config: CacheTtlPruneConfig,
        store: ArchiveCheckpointStore | None = None,
        on_checkpoint: ArchiveCheckpointNotifier | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._on_checkpoint = on_checkpoint

    def dispatch(
        self,
        *,
        tool_name: str,
        content: str,
        archive_path: str,
        chat_id: str | None,
        summarizer_llm: BaseChatModel | None,
        tool_call_id: str | None = None,
        runnable_config: RunnableConfig | None = None,
    ) -> None:
        if not chat_id:
            self._record_metric(chat_id, "skipped", "missing_chat_id")
            return
        if not self._config.archive_summary_enabled:
            self._record_metric(chat_id, "skipped", "disabled")
            return
        if self._store is None:
            self._record_metric(chat_id, "skipped", "store_unavailable")
            return
        if summarizer_llm is None:
            self._record_metric(chat_id, "skipped", "summarizer_unavailable")
            return

        original_tokens = estimate_content_tokens(content)
        if original_tokens < self._config.archive_summary_min_tokens:
            self._record_metric(chat_id, "skipped", "low_value_archive")
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._record_metric(chat_id, "skipped", "no_running_loop")
            return

        summary_key = f"{chat_id}\0{archive_path}"
        if summary_key in _PENDING_KEYS:
            self._record_metric(chat_id, "skipped", "duplicate_pending")
            return
        if len(_PENDING_KEYS) >= self._config.archive_summary_max_queue_size:
            self._record_metric(chat_id, "skipped", "queue_full")
            return
        chat_pending = _PENDING_BY_CHAT.get(chat_id, 0)
        if chat_pending >= self._config.archive_summary_max_tasks_per_chat:
            self._record_metric(chat_id, "skipped", "chat_queue_full")
            return

        _PENDING_KEYS.add(summary_key)
        _PENDING_BY_CHAT[chat_id] = chat_pending + 1
        self._record_metric(chat_id, "queued")

        async def _run() -> None:
            global _SEMAPHORE
            if _SEMAPHORE is None:
                concurrency = max(self._config.archive_summary_max_concurrency, 1)
                _SEMAPHORE = asyncio.Semaphore(concurrency)
            try:
                async with _SEMAPHORE:
                    record = await self._summarize_and_store(
                        tool_name=tool_name,
                        content=content,
                        archive_path=archive_path,
                        chat_id=chat_id,
                        summarizer_llm=summarizer_llm,
                        tool_call_id=tool_call_id,
                    )
                self._record_metric(chat_id, "succeeded")
                if self._on_checkpoint is not None:
                    await self._on_checkpoint(record, runnable_config)
            except Exception as exc:
                self._record_metric(chat_id, "failed")
                logger.warning(
                    "[ArchiveCheckpoint] Failed summary for %s: %s",
                    archive_path,
                    exc,
                )
            finally:
                _PENDING_KEYS.discard(summary_key)
                current = _PENDING_BY_CHAT.get(chat_id, 0)
                if current <= 1:
                    _PENDING_BY_CHAT.pop(chat_id, None)
                else:
                    _PENDING_BY_CHAT[chat_id] = current - 1

        task_name = f"archive_summary_{sha256(summary_key.encode()).hexdigest()[:12]}"
        task = asyncio.create_task(_run(), name=task_name)
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)

    async def _summarize_and_store(
        self,
        *,
        tool_name: str,
        content: str,
        archive_path: str,
        chat_id: str,
        summarizer_llm: BaseChatModel,
        tool_call_id: str | None,
    ) -> ArchiveCheckpointRecord:
        assert self._store is not None
        clipped = content[: self._config.archive_summary_max_input_chars]
        prompt = (
            "Summarize this tool output for later recall by an AI assistant. "
            "Keep key findings, errors, file paths, and numeric results. "
            f"Tool: {tool_name}. Archive path: {archive_path}.\n\n"
            f"{clipped}"
        )
        response = await summarizer_llm.ainvoke([HumanMessage(content=prompt)])
        raw = response.content
        summary = raw if isinstance(raw, str) else str(raw)
        if not summary.strip():
            raise RuntimeError("Archive summary returned empty content.")
        return await self._store.store_checkpoint(
            tool_name=tool_name,
            archive_path=archive_path,
            summary=summary,
            chat_id=chat_id,
            tool_call_id=tool_call_id,
        )

    def _record_metric(
        self,
        chat_id: str | None,
        outcome: Literal["queued", "succeeded", "failed", "skipped"],
        reason: str = "",
    ) -> None:
        if not chat_id:
            return
        metrics = get_task_metrics(chat_id)
        if metrics is None:
            return
        metrics.record_archive_summary_checkpoint(outcome, reason=reason)
