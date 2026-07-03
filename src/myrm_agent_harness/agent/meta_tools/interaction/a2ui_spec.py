"""A2UI component reference helpers — SSOT for allowed types and bundled spec.

[INPUT]
- myrm_agent_harness.agent.artifacts.ui_artifact::UIComponentType (POS: UI 组件类型安全白名单枚举)

[OUTPUT]
- allowed_component_type_names: canonical type strings from enum
- parse_reference_allowed_types: types declared in bundled reference markdown
- get_bundled_reference_content / seed_reference_to_workspace: packaged spec + workspace copy
- format_validation_error: fail-closed ToolMessage for invalid component types
- validate_ui_adjacency / format_adjacency_error: fail-closed graph checks (root_ids, children, ids)

[POS]
A2UI spec SSOT helpers. Keeps enum, bundled markdown, and slim tool docstrings aligned.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from myrm_agent_harness.agent.artifacts.ui_artifact import UIComponentType

A2UI_REFERENCE_FILENAME = "A2UI_REFERENCE.md"
A2UI_REFERENCE_REL_PATH = f".agent/docs/{A2UI_REFERENCE_FILENAME}"
_BUNDLED_REFERENCE = "A2UI_COMPONENT_REFERENCE.md"


def allowed_component_type_names() -> tuple[str, ...]:
    """Return canonical component type strings from UIComponentType enum."""
    return tuple(member.value for member in UIComponentType)


def format_allowed_types_line() -> str:
    """One-line whitelist for slim tool docstrings."""
    return ", ".join(allowed_component_type_names())


def parse_reference_allowed_types(content: str | None = None) -> tuple[str, ...]:
    """Parse allowed component types from bundled reference markdown header."""
    text = content if content is not None else get_bundled_reference_content()
    blockquote_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("> Allowed types"):
            blockquote_lines.append(stripped.removeprefix(">").strip())
            continue
        if blockquote_lines and stripped.startswith(">"):
            blockquote_lines.append(stripped.removeprefix(">").strip())
            continue
        if blockquote_lines:
            break

    if not blockquote_lines:
        return ()

    header_text = " ".join(blockquote_lines)
    match = re.search(r":\s*(.+)$", header_text)
    if not match:
        return ()

    return tuple(token.strip() for token in match.group(1).split(",") if token.strip())


def format_validation_error(invalid_types: list[str]) -> str:
    """Build fail-closed ToolMessage when component types are invalid."""
    invalid = ", ".join(sorted(set(invalid_types)))
    allowed = format_allowed_types_line()
    return (
        f"Failed to render UI: unknown component type(s): {invalid}. "
        f"Allowed types: {allowed}. "
        f"For full props/validation rules, file_read_tool `{A2UI_REFERENCE_REL_PATH}` "
        f"before complex UI (table/chart/tabs)."
    )


def validate_ui_adjacency(
    components: list[dict[str, object]],
    root_ids: list[str],
) -> tuple[str, ...]:
    """Return structural error messages; empty tuple means the adjacency graph is valid."""
    errors: list[str] = []

    if not root_ids:
        errors.append("root_ids must not be empty")

    id_set: set[str] = set()
    for index, comp in enumerate(components):
        if not isinstance(comp, dict):
            errors.append(f"components[{index}] must be an object")
            continue
        raw_id = comp.get("id")
        component_id = str(raw_id).strip() if raw_id is not None else ""
        if not component_id:
            errors.append(f"components[{index}] missing id")
            continue
        if component_id in id_set:
            errors.append(f"duplicate component id: {component_id}")
        id_set.add(component_id)

    for root_id in root_ids:
        root_str = str(root_id).strip()
        if not root_str:
            errors.append("root_ids must not contain empty id")
        elif root_str not in id_set:
            errors.append(f"root_id not found: {root_str}")

    for comp in components:
        if not isinstance(comp, dict):
            continue
        component_id = str(comp.get("id", "")).strip()
        if not component_id:
            continue
        children = comp.get("children", [])
        if children is None:
            continue
        if not isinstance(children, list):
            errors.append(f"component {component_id}: children must be a list")
            continue
        for child_ref in children:
            child_id = str(child_ref).strip()
            if child_id not in id_set:
                errors.append(f"component {component_id}: child id not found: {child_id}")

    return tuple(errors)


def format_adjacency_error(errors: tuple[str, ...] | list[str]) -> str:
    """Build fail-closed ToolMessage when adjacency graph is invalid."""
    if not errors:
        return ""
    detail = "; ".join(errors[:8])
    if len(errors) > 8:
        detail += f"; … and {len(errors) - 8} more"
    return (
        f"Failed to render UI: invalid UI graph: {detail}. "
        f"Use adjacency list with matching id, root_ids, and children references."
    )


def get_bundled_reference_content() -> str:
    """Load packaged A2UI reference markdown from the harness wheel."""
    resource = files("myrm_agent_harness.agent.meta_tools.interaction").joinpath(_BUNDLED_REFERENCE)
    return resource.read_text(encoding="utf-8")


def seed_reference_to_workspace(workspace_root: Path) -> Path | None:
    """Copy bundled reference into workspace for file_read_tool on-demand loading."""
    root = workspace_root.resolve()
    if not root.is_dir():
        return None

    dest_dir = root / ".agent" / "docs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / A2UI_REFERENCE_FILENAME
    content = get_bundled_reference_content()
    if dest.exists() and dest.read_text(encoding="utf-8") == content:
        return dest
    dest.write_text(content, encoding="utf-8")
    return dest
