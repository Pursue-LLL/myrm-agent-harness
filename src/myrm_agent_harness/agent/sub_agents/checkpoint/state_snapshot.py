"""Checkpoint state extraction — build a resumable snapshot of an agent run.

[INPUT]
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: LangGraph checkpointer)
- runtime.checkpointing::read_checkpoint_messages (POS: Checkpointer read-side payload contract)
- agent.types::AgentRunStatistics (POS: Agent run statistics)
- toolkits.code_execution.workspace.storage_root_bind::WORKSPACE_BIND_CTX_KEY (POS: Binds aggregate workspace storage root inside an asyncio Task so lazy helpers align with `setup_workspace`.)

[OUTPUT]
- serialize_message: Serialize a LangChain message to a plain dict.
- sanitize_persistable_context: Copy a runtime context into a JSON/pickle-safe shape (drops the non-serializable workspace bind token).
- project_run_statistics: Project run statistics into the checkpoint payload shape and derive progress; the single projection shared by every checkpoint writer.
- extract_checkpoint_state: Extract complete execution state for checkpoint save.

[POS]
Snapshot builder for checkpoint persistence. Reads the thread's message history through the
shared checkpoint read contract, projects run statistics, and strips the non-serializable
workspace bind token so the payload can be persisted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    WORKSPACE_BIND_CTX_KEY,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.agent.types import AgentRunStatistics

logger = get_agent_logger(__name__)


def serialize_message(msg: object) -> dict[str, object]:
    """Serialize a LangChain message to a plain dict."""
    if hasattr(msg, "model_dump"):
        return cast("dict[str, object]", msg.model_dump())
    if hasattr(msg, "to_json"):
        return cast("dict[str, object]", msg.to_json())
    return {"type": "unknown", "content": str(msg)}


def sanitize_persistable_context(
    context: dict[str, object] | None,
) -> dict[str, object]:
    """Copy a runtime context into a persistable shape.

    ``merged_context`` can still carry the workspace bind undo token: it is popped at run
    cleanup, so an interrupted run leaves it in place. The token is not serializable by
    JSON, pickle, or dill, which makes every checkpoint write fail; all checkpoint writers
    therefore strip it here rather than each re-deriving the rule.
    """
    sanitized = dict(context or {})
    sanitized.pop(WORKSPACE_BIND_CTX_KEY, None)
    return sanitized


def project_run_statistics(stats: AgentRunStatistics) -> tuple[dict[str, object], float]:
    """Project run statistics into the checkpoint payload shape and derive progress.

    Returns ``(stats_dict, progress)``. Callers that persist or report run statistics share
    this projection so the payload keys stay identical across every checkpoint writer.
    """
    last_call_usage = stats.token_usage.to_dict() if stats.token_usage else {}
    projected: dict[str, object] = {
        "token_usage": last_call_usage,
        "duration_seconds": stats.total_duration_seconds,
        "status": (
            stats.completion_status.value if stats.completion_status else "unknown"
        ),
    }
    progress = 1.0 if stats.completion_status else 0.5
    return projected, progress


async def extract_checkpoint_state(
    checkpointer: BaseCheckpointSaver[str] | None,
    last_context: dict[str, object] | None,
    last_run_stats: AgentRunStatistics | None,
    thread_id: str,
) -> dict[str, object]:
    """Extract complete execution state for checkpoint save.

    Used by ``BaseAgent.get_checkpoint_state()`` and subagent checkpoint extraction.

    Args:
        checkpointer: LangGraph BaseCheckpointSaver (or None).
        last_context: Agent's last runtime context dict.
        last_run_stats: Most recent run statistics.
        thread_id: LangGraph thread ID for checkpointer lookup.

    Returns:
        Dict with keys: messages, context, stats, progress, last_tool.
    """
    messages: list[dict[str, object]] = []
    context = sanitize_persistable_context(last_context)
    stats: dict[str, object] = {}
    progress = 0.0
    last_tool: str | None = None

    from myrm_agent_harness.runtime.checkpointing import read_checkpoint_messages

    raw_checkpoint_messages = await read_checkpoint_messages(checkpointer, thread_id)
    if raw_checkpoint_messages:
        messages = [serialize_message(msg) for msg in raw_checkpoint_messages]

        for msg in reversed(messages):
            if msg.get("type") == "ai" and msg.get("tool_calls"):
                tool_calls = msg.get("tool_calls", [])
                if tool_calls and isinstance(tool_calls, list):
                    last_tool = tool_calls[-1].get("name")
                    break

        logger.debug(
            "Extracted %d messages from checkpointer (last_tool=%s)",
            len(messages),
            last_tool,
        )

    if last_run_stats:
        stats, progress = project_run_statistics(last_run_stats)

    return {
        "messages": messages,
        "context": context,
        "stats": stats,
        "progress": progress,
        "last_tool": last_tool,
    }
