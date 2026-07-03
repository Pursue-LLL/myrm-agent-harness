"""A2UI component reference helpers — SSOT for allowed types and bundled spec.

[INPUT]
- myrm_agent_harness.agent.artifacts.ui_artifact::UIComponentType (POS: UI 组件类型安全白名单枚举)

[OUTPUT]
- allowed_component_type_names: canonical type strings from enum
- parse_reference_allowed_types: types declared in bundled reference markdown
- get_bundled_reference_content / seed_reference_to_workspace: packaged spec + workspace copy
- format_validation_error: fail-closed ToolMessage for invalid component types

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
