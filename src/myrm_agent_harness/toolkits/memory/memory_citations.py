"""Memory citation event helpers.

[INPUT]
- agent.streaming.types::AgentEventType (POS: Agent stream event type names)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: Runtime tool progress event sink)
- toolkits.memory.types::MemoryType (POS: Memory domain type enum)

[OUTPUT]
- cited_memory_ref: Build a UI-safe citation reference from a recalled memory.
- emit_cited_memory_ids: Emit memory citation and retrieval trace metadata for frontend stream consumers.
- emit_sources: Emit standard source metadata for frontend stream consumers.

[POS]
Memory citation bridge. Converts recalled memory objects and retrieval traces into lightweight SSE metadata without coupling the
memory manager to server/frontend persistence details.
"""

from __future__ import annotations

import logging
from datetime import datetime

from myrm_agent_harness.toolkits.memory.observability import MemoryRetrievalTrace
from myrm_agent_harness.toolkits.memory.types import MemoryType

logger = logging.getLogger(__name__)
MAX_CITATION_CONTENT_CHARS = 1500


def cited_memory_ref(memory: object, memory_type: MemoryType, score: float) -> dict[str, object]:
    """Build a UI-safe citation reference from a recalled memory."""
    scope = getattr(memory, "scope", None)
    namespaces = getattr(scope, "namespaces", []) if scope is not None else []
    created_at = getattr(memory, "created_at", None)
    ref: dict[str, object] = {
        "id": str(getattr(memory, "id", "")),
        "memory_type": memory_type.value,
        "content": _bounded_text(getattr(memory, "content", "")),
        "score": round(score, 4),
        "primary_namespace": str(getattr(scope, "primary_namespace", "")) if scope is not None else "",
        "namespaces": [namespace for namespace in namespaces if isinstance(namespace, str)]
        if isinstance(namespaces, list)
        else [],
    }
    _copy_optional_str(ref, "source_chat_id", getattr(memory, "source_chat_id", None))
    _copy_optional_str(ref, "source_message_id", getattr(memory, "source_message_id", None))
    if isinstance(created_at, datetime):
        ref["created_at"] = created_at.isoformat()
    return ref


async def emit_cited_memory_ids(
    memory_ids: list[str],
    memory_refs: list[dict[str, object]] | None = None,
    *,
    tool_name: str = "memory_recall_tool",
    retrieval_trace: MemoryRetrievalTrace | None = None,
) -> None:
    """Push cited memory metadata to the SSE output queue for frontend consumption."""
    try:
        from myrm_agent_harness.core.events.types import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

        sink = get_tool_progress_sink()
        if sink is None:
            return
        payload: dict[str, object] = {
            "type": AgentEventType.TOOL_END.value,
            "tool_name": tool_name,
            "cited_memory_ids": memory_ids,
            "cited_memory_refs": memory_refs or [],
        }
        if retrieval_trace is not None:
            payload["memory_retrieval_trace"] = retrieval_trace.model_dump(mode="json")
        await sink.emit(payload)
    except Exception as exc:
        logger.debug("Failed to emit cited_memory_ids: %s", exc)


async def emit_sources(sources: list[dict[str, object]]) -> None:
    """Push standard source metadata to the SSE output queue for frontend consumption."""
    if not sources:
        return
    try:
        from myrm_agent_harness.core.events.types import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

        sink = get_tool_progress_sink()
        if sink is None:
            return
        await sink.emit({"type": AgentEventType.SOURCES.value, "data": sources})
    except Exception as exc:
        logger.debug("Failed to emit sources: %s", exc)


def _copy_optional_str(target: dict[str, object], key: str, value: object) -> None:
    if isinstance(value, str) and value:
        target[key] = value


def _bounded_text(value: object) -> str:
    text = str(value)
    if len(text) <= MAX_CITATION_CONTENT_CHARS:
        return text
    return f"{text[:MAX_CITATION_CONTENT_CHARS]}..."
