"""Session key under which a streaming run's goal is stored.

[INPUT]
- agent.streaming.stream_executor::StreamContext (POS: per-run execution context)

[OUTPUT]
- goal_session_id: the goal lookup key of a run (chat id, else session id, else message id)

[POS]
Single source of the goal lookup key, shared by goal continuation and provider-window
parking so both always address the same goal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext


def goal_session_id(ctx: StreamContext) -> str:
    """Session key of the goal this run serves: chat id, else session id, else the message id."""
    return str(ctx.merged_context.get("chat_id", ctx.merged_context.get("session_id", ctx.message_id)))
