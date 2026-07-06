"""LLM tool catalog metadata — role, load condition, derived product ID.

[INPUT]
- .tool_layers::ToolLayer (POS: CORE/COMMON/EXTENDED priority)
- core.security.tool_registry::TOOL_TO_GROUP (POS: harness tool group SSOT)
- meta_tools.discover_capability.capability_gap::BUILTIN_TOOL_ID_TO_GROUP (POS: GUI togglable product ID → group)

[OUTPUT]
- ToolCatalogRole: user_capability | orchestration_signal | runtime_hook
- get_tool_catalog_role(): resolve role for a registered tool name
- get_tool_load_condition(): human-readable load gate
- get_tool_product_id(): enabled_builtin_tools ID when applicable
- validate_tool_catalog(): role consistency checks for registered tool names
- build_tool_catalog_rows(): sorted rows for doc generation

[POS]
Catalog metadata for *LLM Tool* doc generation and CI (ToolRegistry entries only).
`ToolCatalogRole` / load overrides are owned here; `product_id` is derived from
`TOOL_TO_GROUP` + `BUILTIN_TOOL_ID_TO_GROUP` (not a separate runtime SSOT).
Agent runtime engines/middleware/skills are ordinary code, not LLM tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.agent.meta_tools.discover_capability.capability_gap import (
    BUILTIN_TOOL_ID_TO_GROUP,
)
from myrm_agent_harness.agent.tool_management.tool_layers import ToolLayer, get_tool_layer
from myrm_agent_harness.core.security.tool_registry import TOOL_TO_GROUP


class ToolCatalogRole(StrEnum):
    """How an LLM-facing tool participates in the product vs framework."""

    USER_CAPABILITY = "user_capability"
    ORCHESTRATION_SIGNAL = "orchestration_signal"
    RUNTIME_HOOK = "runtime_hook"


_ROLE_OVERRIDES: dict[str, ToolCatalogRole] = {
    "dispatch_research": ToolCatalogRole.ORCHESTRATION_SIGNAL,
    "think": ToolCatalogRole.ORCHESTRATION_SIGNAL,
    "finalize_report": ToolCatalogRole.ORCHESTRATION_SIGNAL,
    "submit_verdict": ToolCatalogRole.ORCHESTRATION_SIGNAL,
    "_completion_check": ToolCatalogRole.RUNTIME_HOOK,
}

_GROUP_TO_PRODUCT_ID: dict[str, str] = {
    group: product_id for product_id, group in BUILTIN_TOOL_ID_TO_GROUP.items()
}

_BASELINE_TOOL_GROUPS: frozenset[str] = frozenset({"file_ops", "shell"})

# Doc-only override: conversation_history group has no GUI togglable product ID.
_PRODUCT_ID_TOOL_OVERRIDES: dict[str, str] = {
    "conversation_search_tool": "memory",
}

_LOAD_CONDITION_OVERRIDES: dict[str, str] = {
    "web_fetch_tool": "Agent baseline; Turn1 (Fast mode may omit file/bash only)",
    "bash_code_execute_tool": "Agent baseline file_ops+code_execute; Turn1",
    "file_read_tool": "Agent baseline file_ops; Turn1",
    "file_write_tool": "Agent baseline file_ops; Turn1",
    "file_edit_tool": "Agent baseline file_ops; Turn1",
    "glob_tool": "Agent baseline file_ops; Turn1",
    "grep_tool": "Agent baseline file_ops; Turn1",
    "web_search_tool": "enabled_builtin_tools: web_search (default on)",
    "memory_recall_tool": "enable_memory + enabled_builtin_tools: memory",
    "memory_save_tool": "enable_memory + enabled_builtin_tools: memory",
    "memory_manage_tool": "enable_memory + enabled_builtin_tools: memory",
    "conversation_search_tool": "memoryEnableConversationSearch opt-in",
    "request_answer_user_tool": "enabled_builtin_tools: answer_tool",
    "todo_write": "planning or existing workspace todos",
    "bash_process_tool": "DISCOVERABLE; discover_capability AutoMount",
    "skill_discovery_tool": "DISCOVERABLE; skill marketplace",
    "discover_capability_tool": "Turn1 when discoverable pool non-empty",
    "skill_select_tool": "skill_backend present",
    "skill_manage_tool": "write_backend present",
    "dispatch_research": "Deep Research orchestrator session only; intercepted",
    "think": "Deep Research orchestrator session only; intercepted",
    "finalize_report": "Deep Research orchestrator session only; intercepted",
    "submit_verdict": "Verifier sub-agent session only",
    "_completion_check": "CompletionGuard RUNTIME_ONLY inject",
    "delegate_task_tool": "SubagentManagementExtension + entitlements",
    "batch_delegate_tasks_tool": "SubagentManagementExtension + entitlements",
    "delegate_parallel_tasks_tool": "SubagentManagementExtension + entitlements",
    "list_subagents_tool": "SubagentManagementExtension + entitlements",
    "cancel_subagent_tool": "SubagentManagementExtension + entitlements",
    "steer_subagent_tool": "SubagentManagementExtension + entitlements",
    "send_teammate_message_tool": "SubagentManagementExtension + entitlements",
    "get_goal_status_tool": "active Goal on chat",
    "update_goal_status_tool": "active Goal on chat",
    "x_search_tool": "x-live-search prebuilt skill bound",
    "channel_notify_tool": "Agent notify_targets configured",
    "cron_manage_tool": "user cron capability wired",
    "delegate_to_agent_tool": "external ACP agent configured",
    "render_ui_tool": "enabled_builtin_tools: render_ui",
    "ask_question_tool": "clarification wiring in factory",
    "image_tool": "enabled_builtin_tools: image_generation",
    "video_tool": "enabled_builtin_tools: video_generation",
    "tts_generate": "enabled_builtin_tools: tts",
}

_DEFAULT_LOAD_BY_LAYER: dict[ToolLayer, str] = {
    ToolLayer.CORE: "Agent baseline; Turn1 eager",
    ToolLayer.COMMON: "Profile togglable; Turn1 when enabled",
    ToolLayer.EXTENDED: "Opt-in Turn1 or DISCOVERABLE; see product switch",
}


@dataclass(frozen=True, slots=True)
class ToolCatalogRow:
    """One registered LLM tool row for docs and validation."""

    name: str
    layer: ToolLayer
    role: ToolCatalogRole
    load_condition: str
    product_id: str | None


def get_tool_catalog_role(tool_name: str) -> ToolCatalogRole:
    """Return catalog role; defaults to USER_CAPABILITY."""
    return _ROLE_OVERRIDES.get(tool_name, ToolCatalogRole.USER_CAPABILITY)


def get_tool_product_id(tool_name: str) -> str | None:
    """Map @tool name to enabled_builtin_tools product ID when applicable."""
    override = _PRODUCT_ID_TOOL_OVERRIDES.get(tool_name)
    if override is not None:
        return override

    group = TOOL_TO_GROUP.get(tool_name)
    if group is None or group in _BASELINE_TOOL_GROUPS:
        return None
    if group == "web" and tool_name != "web_search_tool":
        return None
    if group == "conversation_history":
        return None

    return _GROUP_TO_PRODUCT_ID.get(group)


def get_tool_load_condition(tool_name: str, *, layer: ToolLayer | None = None) -> str:
    """Human-readable load gate for docs and onboarding."""
    if tool_name in _LOAD_CONDITION_OVERRIDES:
        return _LOAD_CONDITION_OVERRIDES[tool_name]
    product_id = get_tool_product_id(tool_name)
    if product_id is not None:
        return f"enabled_builtin_tools: {product_id}"
    resolved_layer = layer if layer is not None else get_tool_layer(tool_name)
    return _DEFAULT_LOAD_BY_LAYER.get(resolved_layer, "Opt-in; see factory wiring")


def build_tool_catalog_row(tool_name: str, *, layer: ToolLayer | None = None) -> ToolCatalogRow:
    """Build a catalog row for one registered tool name."""
    resolved_layer = layer if layer is not None else get_tool_layer(tool_name)
    return ToolCatalogRow(
        name=tool_name,
        layer=resolved_layer,
        role=get_tool_catalog_role(tool_name),
        load_condition=get_tool_load_condition(tool_name, layer=resolved_layer),
        product_id=get_tool_product_id(tool_name),
    )


def _coerce_layer(layer: ToolLayer | str) -> ToolLayer:
    if isinstance(layer, ToolLayer):
        return layer
    return ToolLayer[str(layer)]


def build_tool_catalog_rows(registered: dict[str, ToolLayer | str]) -> list[ToolCatalogRow]:
    """Sorted catalog rows for all registered tool names."""
    rows = [
        build_tool_catalog_row(name, layer=_coerce_layer(layer))
        for name, layer in registered.items()
    ]
    rows.sort(key=lambda row: (int(row.layer), row.role.value, row.name))
    return rows


def validate_tool_catalog(registered: dict[str, ToolLayer | str]) -> list[str]:
    """Return error strings when catalog metadata is inconsistent."""
    errors: list[str] = []
    for name in registered:
        role = get_tool_catalog_role(name)
        if role is ToolCatalogRole.USER_CAPABILITY and name.startswith("_"):
            errors.append(f"{name}: underscore prefix requires RUNTIME_HOOK role override")
        if name == "_completion_check" and role is not ToolCatalogRole.RUNTIME_HOOK:
            errors.append(f"{name}: must use ToolCatalogRole.RUNTIME_HOOK")
        if name in {"dispatch_research", "think", "finalize_report", "submit_verdict"}:
            if role is not ToolCatalogRole.ORCHESTRATION_SIGNAL:
                errors.append(f"{name}: must use ToolCatalogRole.ORCHESTRATION_SIGNAL")
    return errors


def format_tool_catalog_markdown(rows: list[ToolCatalogRow]) -> str:
    """Render the auto-generated LLM tool catalog table."""
    lines = [
        "| Tool | Layer | Role | Product ID | Load condition |",
        "|------|-------|------|------------|----------------|",
    ]
    for row in rows:
        product = row.product_id or "—"
        lines.append(
            f"| `{row.name}` | {row.layer.name} | {row.role.value} | {product} | {row.load_condition} |"
        )
    return "\n".join(lines)
