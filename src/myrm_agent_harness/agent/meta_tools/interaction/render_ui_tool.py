"""Declarative UI rendering tool (A2UI).

[INPUT]
- langchain_core.tools::tool
- myrm_agent_harness.agent.artifacts::UIArtifact, get_ui_registry
- myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec::A2UI_REFERENCE_REL_PATH, format_action_reference_error, format_adjacency_error, format_allowed_types_line, format_validation_error, normalize_component_dicts, validate_action_references, validate_ui_adjacency (POS: A2UI spec SSOT helpers)

[OUTPUT]
- render_ui_tool: LangChain tool that creates a UIArtifact from declarative JSON.

[POS]
Agent meta-tool emitting interactive UI via UIArtifact. Requires agent artifact context.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.tools import tool

from myrm_agent_harness.agent.artifacts import UIArtifact, register_ui_artifact
from myrm_agent_harness.agent.artifacts.ui_artifact import (
    UIAction,
    UIComponent,
    UIComponentType,
)
from myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec import (
    A2UI_REFERENCE_REL_PATH,
    format_action_reference_error,
    format_adjacency_error,
    format_allowed_types_line,
    format_validation_error,
    normalize_component_dicts,
    validate_action_references,
    validate_ui_adjacency,
)

logger = logging.getLogger(__name__)

_ALLOWED_TYPES_LINE = format_allowed_types_line()


def _dispatch_ui_update_event(ui_artifact: UIArtifact) -> None:
    """Push ui_update during tool execution so SSE clients see UI before post_run."""
    try:
        from langchain_core.callbacks.manager import dispatch_custom_event

        dispatch_custom_event(
            "ui_update",
            {
                "subtype": "ui_artifact",
                "data": [ui_artifact.to_dict()],
            },
        )
    except Exception as exc:
        logger.warning("Failed to dispatch ui_update event: %s", exc)


_RENDER_UI_DOC = f"""Render an interactive declarative UI (forms, tables, cards, charts) in chat.

Use when user input requires multi-field forms, structured tables, or rich dashboard layouts.
For simple single/multi-choice clarifying questions, prefer ask_question_tool instead.

Allowed types: {_ALLOWED_TYPES_LINE}

Rules:
1. components: Flat list of components. 'children' must hold child ID strings only (NEVER nest component objects inside children).
2. root_ids: List of top-level container/card component IDs only.
3. bindings: Use JSONPath syntax to bind component values to data fields (e.g. {{"value": "$.form.username"}}).
4. events & actions: Every event (e.g. {{"onClick": "act_submit"}}) MUST reference a matching id in 'actions'.
   Action schema: {{"id": "str", "type": "submit|cancel|navigate|custom", "label": "str"}}.

Minimal Example Structure:
  components=[
    {{"id": "card_1", "type": "card", "children": ["txt_1", "btn_1"]}},
    {{"id": "txt_1", "type": "text", "props": {{"text": "Hello"}}}},
    {{"id": "btn_1", "type": "button", "props": {{"label": "OK"}}, "events": {{"onClick": "act_1"}}}}
  ],
  root_ids=["card_1"],
  actions=[{{"id": "act_1", "type": "submit", "label": "OK"}}]

CRITICAL: For complex components (table, chart, tabs, form inputs) or 3+ components, use file_read_tool on `{A2UI_REFERENCE_REL_PATH}` for full props and examples.
After rendering, use update_ui_data_tool to patch data fields dynamically without re-sending the component graph.

Args:
    title: UI title displayed in chat
    components: Flat component list
    root_ids: Top-level component IDs
    data: Initial data model dictionary
    actions: Triggerable action buttons

Returns:
    Confirmation with surface_id upon success, or actionable validation error for self-correction.
"""


def render_ui(
    title: str,
    components: list[dict[str, object]],
    root_ids: list[str],
    data: dict[str, object] | None = None,
    actions: list[dict[str, object]] | None = None,
) -> str:
    """Render an interactive UI (forms, tables, charts) in chat."""
    if not components:
        return f"Failed to render UI: components must not be empty. Allowed types: {_ALLOWED_TYPES_LINE}."

    components = normalize_component_dicts(components)

    adjacency_errors = validate_ui_adjacency(components, root_ids)
    if adjacency_errors:
        return format_adjacency_error(adjacency_errors)

    try:
        parsed_components: list[UIComponent] = []
        invalid_types: list[str] = []

        for comp_dict in components:
            comp_type_str = str(comp_dict.get("type", "")).strip()
            if not comp_type_str:
                invalid_types.append("<missing>")
                continue
            try:
                comp_type = UIComponentType(comp_type_str)
            except ValueError:
                logger.warning("Unknown component type: %s", comp_type_str)
                invalid_types.append(comp_type_str)
                continue

            parsed_components.append(
                UIComponent(
                    id=str(comp_dict.get("id", "")),
                    type=comp_type,
                    props=dict(comp_dict.get("props", {})) if isinstance(comp_dict.get("props"), dict) else {},
                    children=list(comp_dict.get("children", [])) if isinstance(comp_dict.get("children"), list) else [],
                    bindings=dict(comp_dict.get("bindings", {})) if isinstance(comp_dict.get("bindings"), dict) else {},
                    events=dict(comp_dict.get("events", {})) if isinstance(comp_dict.get("events"), dict) else {},
                )
            )

        if invalid_types:
            return format_validation_error(invalid_types)

        if not parsed_components:
            return f"Failed to render UI: no valid components after parsing. Allowed types: {_ALLOWED_TYPES_LINE}."

        parsed_actions: list[UIAction] = []
        for index, action_dict in enumerate(actions or []):
            if not isinstance(action_dict, dict):
                return f"Failed to render UI: actions[{index}] must be an object, got {type(action_dict).__name__}."
            raw_action_type = str(action_dict.get("type", "custom"))
            action_type: Literal["submit", "cancel", "navigate", "custom"] = (
                raw_action_type if raw_action_type in ("submit", "cancel", "navigate", "custom") else "custom"
            )
            parsed_actions.append(
                UIAction(
                    id=str(action_dict.get("id", "")),
                    type=action_type,
                    label=str(action_dict.get("label", "")),
                    payload=dict(action_dict.get("payload", {}))
                    if isinstance(action_dict.get("payload"), dict)
                    else {},
                )
            )

        action_ref_errors = validate_action_references(components, actions)
        if action_ref_errors:
            return format_action_reference_error(action_ref_errors)

        ui_artifact = UIArtifact(
            title=title,
            components=parsed_components,
            root_ids=root_ids,
            data=data or {},
            actions=parsed_actions,
        )

        if not register_ui_artifact(ui_artifact):
            return (
                "Failed to render UI: UI registry is not initialized. "
                "Call render_ui only within an active artifact context."
            )

        logger.warning(
            "UI artifact registered: %s (surface_id=%s)",
            title,
            ui_artifact.surface_id,
        )
        _dispatch_ui_update_event(ui_artifact)

        return (
            f"已向用户展示交互式界面：「{title}」（surface_id={ui_artifact.surface_id}）。"
            "用户可以在界面上进行操作，操作结果将自动反馈给我。"
        )

    except Exception as e:
        error_msg = f"Failed to render UI: {type(e).__name__}: {e!s}"
        logger.error(error_msg)
        return error_msg


render_ui.__doc__ = _RENDER_UI_DOC
render_ui_tool = tool("render_ui_tool")(render_ui)
