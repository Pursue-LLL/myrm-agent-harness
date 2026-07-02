"""Progress middleware — inject todo blueprint into HumanMessage when todos exist."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoStore

logger = logging.getLogger(__name__)


def progress_middleware(
    get_todos_fn: Callable[[str | None], Awaitable[TodoStore | None]],
) -> Any:
    """Inject active todo focus into the last HumanMessage (non-persistent)."""

    @wrap_model_call  # type: ignore[arg-type]
    async def _middleware(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        context = getattr(request.runtime, "context", None) if hasattr(request, "runtime") and request.runtime else None
        workspace_root = None
        if isinstance(context, dict):
            workspace_root = context.get("workspace_root")

        store = await get_todos_fn(str(workspace_root) if workspace_root else None)
        if not store or not store.todos:
            return await handler(request)

        incomplete = store.incomplete_todos()
        if not incomplete:
            return await handler(request)

        lines = [
            "[SYSTEM INSTRUCTION]",
            "## Task progress (active todos)",
            f"**Goal:** {store.goal or 'Multi-step task'}",
            "",
        ]
        for item in store.todos:
            marker = ">" if item.id == incomplete[0].id else "-"
            lines.append(f"{marker} [{item.status.value}] {item.id}: {item.content}")

        lines.extend(
            [
                "",
                f"Current focus: `{incomplete[0].id}` — {incomplete[0].content}",
                "Mark items completed with `todo_write(merge=true)` as you finish them.",
            ]
        )
        injection_text = "\n".join(lines)

        new_messages = list(request.messages)
        last_human_idx = -1
        for i in range(len(new_messages) - 1, -1, -1):
            if isinstance(new_messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx != -1:
            last_msg = new_messages[last_human_idx]
            if isinstance(last_msg.content, str):
                new_messages[last_human_idx] = HumanMessage(
                    content=f"{last_msg.content}\n\n{injection_text}",
                    id=last_msg.id,
                )
            elif isinstance(last_msg.content, list):
                new_messages[last_human_idx] = HumanMessage(
                    content=[*last_msg.content, {"type": "text", "text": f"\n\n{injection_text}"}],
                    id=last_msg.id,
                )
        else:
            new_messages.append(HumanMessage(content=injection_text))

        return await handler(request.override(messages=new_messages))

    return _middleware


__all__ = ["progress_middleware"]
