"""Checkpointer decorator that degrades an undecodable stored checkpoint into a fresh session.

[INPUT]
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: LangGraph checkpointer base class)
- pruning::HistoryPrunable (POS: structural type of a saver that can name and prune threads with superseded history)

[OUTPUT]
- LoadFallbackCheckpointer: forwards the async saver interface (incl. history pruning) to the wrapped saver;
  `aget_tuple` returns None instead of raising when the stored payload cannot be deserialized

[POS]
Wraps the SQLite saver the factory builds. A checkpoint written by an older release can reference classes that
no longer exist; failing the load would block the chat on every turn, so the run starts a fresh session instead.
Every async method the wrapped saver implements must be forwarded here — a method left out silently falls back to
the base class and raises NotImplementedError (`adelete_thread` is called when a chat's threads are cleared and when a `replace` turn rebuilds its thread).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointTuple
from langgraph.checkpoint.base import CheckpointMetadata as LGMetadata

from .pruning import HistoryPrunable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import ChannelVersions

logger = logging.getLogger(__name__)


def _is_undecodable_payload(exc: Exception) -> bool:
    """Whether the failure came from deserializing stored data rather than from the storage itself."""
    message = str(exc).lower()
    if "pickle" in message or "dill" in message:
        return True
    if "missing 2 required positional arguments" in message:
        return True

    tb = exc.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if "/dill/" in filename or "/pickle" in filename:
            return True
        tb = tb.tb_next
    return False


class LoadFallbackCheckpointer(BaseCheckpointSaver[str]):
    """Delegates to a wrapped saver; a checkpoint that cannot be decoded reads as "no checkpoint"."""

    def __init__(self, wrapped: BaseCheckpointSaver[str]) -> None:
        super().__init__()
        self._wrapped = wrapped

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: LGMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await self._wrapped.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, object]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await self._wrapped.aput_writes(config, writes, task_id, task_path=task_path)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        try:
            return await self._wrapped.aget_tuple(config)
        except Exception as exc:
            if not _is_undecodable_payload(exc):
                raise
            logger.warning(
                "Checkpoint load failed; starting fresh session (thread_id=%s): %s",
                config.get("configurable", {}).get("thread_id"),
                exc,
            )
            return None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, object] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        async for item in self._wrapped.alist(config, filter=filter, before=before, limit=limit):
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        await self._wrapped.adelete_thread(thread_id)

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        await self._wrapped.aprune(thread_ids, strategy=strategy)

    async def alist_prunable_thread_ids(self) -> list[str]:
        if not isinstance(self._wrapped, HistoryPrunable):
            raise NotImplementedError(f"{type(self._wrapped).__name__} cannot name threads with prunable history")
        return await self._wrapped.alist_prunable_thread_ids()

    def get_next_version(self, current: str | None, channel: None) -> str:
        return self._wrapped.get_next_version(current, channel)
