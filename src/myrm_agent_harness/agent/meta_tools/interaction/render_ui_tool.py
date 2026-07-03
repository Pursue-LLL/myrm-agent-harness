"""Declarative UI rendering tool (A2UI).

[INPUT]
- langchain_core.tools::tool
- myrm_agent_harness.agent.artifacts::UIArtifact, get_ui_registry
- myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec::format_validation_error, parse_reference_allowed_types (POS: A2UI spec SSOT helpers)

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
    format_adjacency_error,
    format_allowed_types_line,
    format_validation_error,
    normalize_component_dicts,
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


_RENDER_UI_DOC = f"""Render an interactive UI (forms, tables, charts) in chat.

Use for multi-field forms, structured tables, or layout-heavy UI.
For simple clarifying questions, prefer ask_question_tool instead.

Allowed component types: {_ALLOWED_TYPES_LINE}

JSON adjacency list: components[{{id,type,props,children,bindings,events}}], root_ids, optional data/actions.
Minimal example (text + text_field + button) needs no extra spec.

CRITICAL: Before table/chart/tabs or 3+ component UIs, file_read_tool `{A2UI_REFERENCE_REL_PATH}` for full props.

Args:
    title: UI title
    components: Flat component list
    root_ids: Root component IDs
    data: Initial data model
    actions: Triggerable actions

Returns:
    Confirmation that UI was sent to the user, or a validation error for self-correction.
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
        return (
            "Failed to render UI: components must not be empty. "
            f"Allowed types: {_ALLOWED_TYPES_LINE}."
        )

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
                    bindings=dict(comp_dict.get("bindings", {}))
                    if isinstance(comp_dict.get("bindings"), dict)
                    else {},
                    events=dict(comp_dict.get("events", {})) if isinstance(comp_dict.get("events"), dict) else {},
                )
            )

        if invalid_types:
            return format_validation_error(invalid_types)

        if not parsed_components:
            return (
                "Failed to render UI: no valid components after parsing. "
                f"Allowed types: {_ALLOWED_TYPES_LINE}."
            )

        parsed_actions: list[UIAction] = []
        for index, action_dict in enumerate(actions or []):
            if not isinstance(action_dict, dict):
                return (
                    f"Failed to render UI: actions[{index}] must be an object, "
                    f"got {type(action_dict).__name__}."
                )
            raw_action_type = str(action_dict.get("type", "custom"))
            action_type: Literal["submit", "cancel", "navigate", "custom"] = (
                raw_action_type
                if raw_action_type in ("submit", "cancel", "navigate", "custom")
                else "custom"
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

        return f"已向用户展示交互式界面：「{title}」。用户可以在界面上进行操作，操作结果将自动反馈给我。"

    except Exception as e:
        error_msg = f"Failed to render UI: {type(e).__name__}: {e!s}"
        logger.error(error_msg)
        return error_msg


render_ui.__doc__ = _RENDER_UI_DOC
render_ui_tool = tool("render_ui_tool")(render_ui)
