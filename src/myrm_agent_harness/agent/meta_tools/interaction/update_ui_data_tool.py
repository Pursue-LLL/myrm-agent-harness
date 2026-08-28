"""Incremental UI data model updates (A2UI).

[INPUT]
- langchain_core.tools::tool
- myrm_agent_harness.agent.artifacts::UIDataUpdate, register_ui_data_update

[OUTPUT]
- update_ui_data_tool: LangChain tool that pushes UIDataUpdate without re-sending the full UI.

[POS]
Agent meta-tool for progressive UI data refresh after render_ui_tool. Requires artifact context.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from myrm_agent_harness.agent.artifacts import UIDataUpdate, register_ui_data_update

logger = logging.getLogger(__name__)


def _dispatch_ui_data_update_event(update: UIDataUpdate) -> None:
    """Push data_update during tool execution so SSE clients see updates before post_run."""
    try:
        from langchain_core.callbacks.manager import dispatch_custom_event

        dispatch_custom_event(
            "ui_update",
            {
                "subtype": "data_update",
                "data": update.model_dump(),
            },
        )
    except Exception as exc:
        logger.warning("Failed to dispatch ui_update data_update event: %s", exc)


_UPDATE_UI_DATA_DOC = """Push incremental data updates to an active interactive UI without re-rendering the layout.

Use after a prior render_ui_tool call when only data fields change (e.g. status updates, table rows, progress values).
Do not re-send the full component graph — provide top-level data key patches (nested plain objects deep-merge; arrays and primitives replace target keys).

Args:
    surface_id: The surface_id returned from the prior render_ui_tool execution.
    updates: Key-value dictionary of data model patches (nested dict values deep-merge into active surface data).

Returns:
    Confirmation message upon success, or fail-closed error if the surface context is invalid.
"""


def update_ui_data(surface_id: str, updates: dict[str, object]) -> str:
    """Push incremental updates to an existing interactive UI data model."""
    normalized_surface_id = surface_id.strip()
    if not normalized_surface_id:
        return "Failed to update UI data: surface_id must not be empty."

    if not updates:
        return "Failed to update UI data: updates must not be empty."

    data_update = UIDataUpdate(surface_id=normalized_surface_id, updates=dict(updates))

    if not register_ui_data_update(data_update):
        return (
            "Failed to update UI data: UI registry is not initialized. "
            "Call update_ui_data only within an active artifact context after render_ui_tool."
        )

    logger.warning(
        "UI data update registered: surface_id=%s keys=%s",
        normalized_surface_id,
        list(updates.keys()),
    )
    _dispatch_ui_data_update_event(data_update)

    return f"已更新交互式界面数据（surface_id={normalized_surface_id}）。"


update_ui_data.__doc__ = _UPDATE_UI_DATA_DOC
update_ui_data_tool = tool("update_ui_data_tool")(update_ui_data)
