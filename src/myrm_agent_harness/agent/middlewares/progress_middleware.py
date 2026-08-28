"""Progress middleware — inject todo blueprint into HumanMessage when todos exist.

[INPUT]
- progress.schemas::TodoStore (POS: active todos)
- langchain.agents.middleware::ModelRequest, wrap_model_call (POS: LC middleware)

[OUTPUT]
- progress_middleware: Injects non-persistent todo focus into last HumanMessage

[POS]
Surfaces active todos to the model without polluting persistent message history.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoItem, TodoStatus, TodoStore

logger = logging.getLogger(__name__)

_PROGRESS_BLOCK_PATTERN = re.compile(
    r"\n*\s*\[SYSTEM INSTRUCTION\]\s*\n## Task progress \(active todos\)[\s\S]*$",
    re.MULTILINE,
)


def _strip_previous_progress(content: str) -> str:
    """Remove any trailing progress injection block from previous turns."""
    return _PROGRESS_BLOCK_PATTERN.sub("", content).rstrip()


def _build_progress_injection(store: TodoStore, incomplete: list[TodoItem]) -> str:
    """Build compact and focus-preserving todo injection text."""
    lines: list[str] = [
        "[SYSTEM INSTRUCTION]",
        "## Task progress (active todos)",
        f"**Goal:** {store.goal or 'Multi-step task'}",
        "",
    ]

    completed_count = sum(1 for item in store.todos if item.status == TodoStatus.COMPLETED)
    cancelled_count = sum(1 for item in store.todos if item.status == TodoStatus.CANCELLED)

    # If there are completed/cancelled items and list is long (> 4 items), summarize completed
    if len(store.todos) > 4 and (completed_count > 0 or cancelled_count > 0):
        summary_parts: list[str] = []
        if completed_count > 0:
            summary_parts.append(f"{completed_count} completed")
        if cancelled_count > 0:
            summary_parts.append(f"{cancelled_count} cancelled")
        lines.append(f"[✓] {', '.join(summary_parts)}")

        # Show incomplete items (up to 4 items)
        max_visible_incomplete = 4
        for item in incomplete[:max_visible_incomplete]:
            marker = ">" if item.id == incomplete[0].id else "-"
            lines.append(f"{marker} [{item.status.value}] {item.id}: {item.content}")

        if len(incomplete) > max_visible_incomplete:
            remaining = len(incomplete) - max_visible_incomplete
            lines.append(f"... and {remaining} more pending task(s)")
    else:
        # Full list for short plans (<= 4 items)
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
    return "\n".join(lines)


def progress_middleware(
    get_todos_fn: Callable[[str | None], Awaitable[TodoStore | None]],
) -> Any:
    """Inject active todo focus into the last HumanMessage (non-persistent)."""

    @wrap_model_call(name="progress_middleware")  # type: ignore[arg-type]
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

        injection_text = _build_progress_injection(store, incomplete)

        new_messages = list(request.messages)
        last_human_idx = -1
        for i in range(len(new_messages) - 1, -1, -1):
            if isinstance(new_messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx != -1:
            last_msg = new_messages[last_human_idx]
            if isinstance(last_msg.content, str):
                cleaned_content = _strip_previous_progress(last_msg.content)
                new_messages[last_human_idx] = HumanMessage(
                    content=f"{cleaned_content}\n\n{injection_text}" if cleaned_content else injection_text,
                    id=last_msg.id,
                )
            elif isinstance(last_msg.content, list):
                cleaned_parts: list[dict[str, Any]] = []
                for part in last_msg.content:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                        cleaned_text = _strip_previous_progress(part["text"])
                        if cleaned_text:
                            cleaned_parts.append({**part, "text": cleaned_text})
                    else:
                        cleaned_parts.append(part)
                new_messages[last_human_idx] = HumanMessage(
                    content=[*cleaned_parts, {"type": "text", "text": f"\n\n{injection_text}"}],
                    id=last_msg.id,
                )
        else:
            new_messages.append(HumanMessage(content=injection_text))

        return await handler(request.override(messages=new_messages))

    return _middleware


__all__ = ["progress_middleware"]
