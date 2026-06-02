"""P2P teammate message meta-tool for sibling subagents.

[INPUT]
- coordination.mailbox::{get_teammate_mailbox, emit_teammate_message_sse} (POS: Session mailbox + SSE)
- middlewares._session_context::{get_subagent_task_id, get_approval_session} (POS: Subagent runtime context)

[OUTPUT]
- create_send_teammate_message_tool: LangChain tool for sibling P2P send

[POS]
LLM-callable send path for teammate mailbox. Emits GUI SSE on successful accept.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.coordination.mailbox import (
    emit_teammate_message_sse,
    get_teammate_mailbox,
)
from myrm_agent_harness.agent.coordination.types import TeammateMessage
from myrm_agent_harness.agent.middlewares._session_context import (
    get_approval_session,
    get_subagent_task_id,
    get_workspace_root,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent

_MAX_BODY_CHARS = 4000


def create_send_teammate_message_tool(parent_agent: BaseAgent) -> BaseTool:
    """Create send_teammate_message for direct sibling subagent communication."""

    class SendTeammateInput(BaseModel):
        target_task_id: str = Field(description="Recipient subagent task_id from active_teammates roster")
        body: str = Field(
            description="Message body for the teammate (keep concise; avoid dumping full logs)",
            max_length=_MAX_BODY_CHARS,
        )

    @tool(
        "send_teammate_message_tool",
        description=(
            "Send a direct message to another running subagent (P2P mailbox). "
            "Use target_task_id from active_teammates. Does not broadcast to all agents."
        ),
        args_schema=SendTeammateInput,
    )
    async def send_teammate_message_func(target_task_id: str, body: str) -> dict[str, Any]:
        from_task_id = get_subagent_task_id()
        if not from_task_id:
            return {
                "success": False,
                "error": "send_teammate_message is only available inside a subagent context",
            }

        session_id = get_approval_session() or ""
        if not session_id:
            return {"success": False, "error": "Missing session_id for teammate mailbox"}

        workspace = get_workspace_root() or None
        mailbox = await get_teammate_mailbox(session_id, workspace)

        agent_type = "unknown"
        for child in parent_agent.list_children():
            if child.get("task_id") == from_task_id:
                agent_type = str(child.get("agent_type", "unknown"))
                break

        roster = mailbox.list_active_roster(exclude_task_id=from_task_id)
        active_ids = {entry["task_id"] for entry in roster}
        if target_task_id not in active_ids:
            return {
                "success": False,
                "error": (
                    "target_task_id is not in active_teammates roster; "
                    "use a running sibling task_id from active_teammates"
                ),
                "active_teammates": roster,
            }

        message = TeammateMessage(
            message_id=uuid4().hex,
            session_id=session_id,
            from_task_id=from_task_id,
            to_task_id=target_task_id,
            from_agent_type=agent_type,
            body=body.strip(),
            created_at=time.time(),
        )
        send_result = await mailbox.send(message)
        if send_result.accepted:
            await emit_teammate_message_sse(message)
        return {
            "success": send_result.accepted,
            "error": send_result.error,
            "message_id": message.message_id,
            "to_task_id": target_task_id,
            "active_teammates": roster,
        }

    return send_teammate_message_func
