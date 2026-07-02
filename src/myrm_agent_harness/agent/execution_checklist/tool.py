"""Execution checklist tool — lightweight multi-step progress tracking.

[INPUT]
- execution_checklist.state::ExecutionChecklistState (POS: workspace-scoped checklist SSOT)

[OUTPUT]
- create_update_execution_checklist_tool(): LangChain StructuredTool factory

[POS]
Agent meta-tool for Path B checklist updates; workspace root resolved per invocation via session ContextVar.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.tools import tool

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

TOOL_NAME = "update_execution_checklist_tool"


def create_update_execution_checklist_tool(*, fallback_workspace_root: str | None = None) -> BaseTool:
    """Create checklist update tool; workspace root resolved per invocation."""
    from myrm_agent_harness.agent.execution_checklist.state import (
        CHECKLIST_WORKSPACE_METADATA_KEY,
        ExecutionChecklistState,
        normalize_checklist_items,
        read_checklist_sync,
        resolve_checklist_items,
        resolve_checklist_workspace_root,
        remember_checklist_workspace_root,
        save_checklist_to_workspace,
    )

    @tool(TOOL_NAME)
    async def update_execution_checklist_tool(todos: list[dict[str, object]]) -> str:
        """Update the session execution checklist for multi-step task tracking.

        Use for non-Goal tasks when you need a visible progress list without full planner planning.
        Send the FULL checklist when adding/removing/reordering items. Partial updates merge by id.

        Item fields:
        - content (required): task description
        - status: pending | in_progress | completed | cancelled
        - id (optional): stable item id

        Rules:
        - Keep exactly one in_progress item while work remains
        - Mark completed only after the work is actually done
        - Use for 3+ step tasks; skip for single-step or informational requests
        """
        workspace_root = resolve_checklist_workspace_root(fallback_workspace_root=fallback_workspace_root)
        if not workspace_root:
            return "Error: workspace root unavailable; cannot persist execution checklist"

        items = normalize_checklist_items(todos)
        if not items:
            return "Error: todos must contain at least one item with non-empty content"

        in_progress = [i for i in items if i.status == "in_progress"]
        if len(in_progress) > 1:
            return "Error: at most one item may be in_progress at a time"

        existing_state = read_checklist_sync(workspace_root)
        existing_items = existing_state.items if existing_state else []
        merged_items = resolve_checklist_items(existing_items, items)
        state = ExecutionChecklistState(items=merged_items)
        await save_checklist_to_workspace(workspace_root, state)
        remember_checklist_workspace_root(workspace_root)

        done = sum(1 for i in merged_items if i.status == "completed")
        return json.dumps(
            {
                "content": f"Checklist updated: {done}/{len(merged_items)} completed",
                "metadata": {CHECKLIST_WORKSPACE_METADATA_KEY: workspace_root},
            }
        )

    return update_execution_checklist_tool  # type: ignore[return-value]
