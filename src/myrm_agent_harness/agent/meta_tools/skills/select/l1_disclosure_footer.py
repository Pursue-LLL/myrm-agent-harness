"""L1 skill document disclosure footer (linked files + resolved config).

[INPUT]
- backends.skills.protocols::SkillBackend (POS: list_skill_resources for linked index)
- backends.skills.types::SkillMetadata, SkillInstance (POS: config_schema + overrides)
- core.security.detection.leak_detector::redact_leaks (POS: credential redaction)

[OUTPUT]
- build_l1_disclosure_footer: append-only footer for get_skill_document()
- ALLOWED_SKILL_FILE_DIRS: shared path guard with skill_select_tool L2 reader

[POS]
L1 progressive-disclosure footer. ToolMessage/HumanMessage only — never SystemMessage.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.types import SkillInstance, SkillMetadata

ALLOWED_SKILL_FILE_DIRS = frozenset({"scripts", "references", "templates", "assets"})
_MAX_PATHS_PER_GROUP = 8
_MAX_LINKED_PATHS_TOTAL = 24


def filter_disclosable_resource_paths(resources: list[str]) -> list[str]:
    """Keep only auxiliary paths under allowed skill subdirectories."""
    filtered: list[str] = []
    for raw in resources:
        normalized = PurePosixPath(raw.replace("\\", "/"))
        if ".." in normalized.parts:
            continue
        if not normalized.parts:
            continue
        if normalized.parts[0] not in ALLOWED_SKILL_FILE_DIRS:
            continue
        if len(normalized.parts) < 2:
            continue
        name = normalized.parts[-1]
        if name.startswith("."):
            continue
        filtered.append("/".join(normalized.parts))
    return sorted(set(filtered))


def group_linked_resources(resources: list[str]) -> dict[str, list[str]]:
    """Group paths by top-level directory (scripts, references, etc.)."""
    grouped: dict[str, list[str]] = {key: [] for key in sorted(ALLOWED_SKILL_FILE_DIRS)}
    for path in filter_disclosable_resource_paths(resources):
        top = path.split("/", 1)[0]
        if top in grouped:
            grouped[top].append(path)
    return {key: paths for key, paths in grouped.items() if paths}


def format_linked_files_section(
    grouped: dict[str, list[str]],
    *,
    max_per_group: int = _MAX_PATHS_PER_GROUP,
    max_total: int = _MAX_LINKED_PATHS_TOTAL,
) -> str:
    """Render Hermes-style linked_files index with caps."""
    if not grouped:
        return ""

    lines = ["", "[Linked files]"]
    shown = 0
    omitted = 0

    for group in sorted(grouped.keys()):
        paths = grouped[group]
        take = min(len(paths), max_per_group, max(0, max_total - shown))
        for path in paths[:take]:
            lines.append(f"  {group}: {path}")
            shown += 1
        group_omitted = len(paths) - take
        if group_omitted > 0:
            omitted += group_omitted
            lines.append(f"  {group}: ... and {group_omitted} more")

    if omitted > 0:
        lines.append(
            f"  ({omitted} path(s) omitted — use skill_select_tool(file_path=...) to read any file under "
            f"{', '.join(sorted(ALLOWED_SKILL_FILE_DIRS))}/)"
        )
    else:
        lines.append(
            '  Use skill_select_tool(file_path="<path>") to load an auxiliary file '
            f"({', '.join(sorted(ALLOWED_SKILL_FILE_DIRS))}/)."
        )
    return "\n".join(lines)


def format_compact_linked_index(resources: list[str], *, max_paths: int = 6) -> str:
    """One-line linked index for reload summaries (~50 tokens)."""
    paths = filter_disclosable_resource_paths(resources)
    if not paths:
        return ""
    shown = paths[:max_paths]
    suffix = f" (+{len(paths) - len(shown)} more)" if len(paths) > len(shown) else ""
    joined = ", ".join(shown)
    return f"Linked: {joined}{suffix}. Use skill_select_tool(file_path=...) to read."


def _schema_property_keys(config_schema: dict[str, object]) -> list[str]:
    props = config_schema.get("properties")
    if not isinstance(props, dict):
        return []
    return sorted(str(key) for key in props)


def _schema_default_values(config_schema: dict[str, object]) -> dict[str, object]:
    props = config_schema.get("properties")
    if not isinstance(props, dict):
        return {}
    defaults: dict[str, object] = {}
    for key, spec in props.items():
        if isinstance(spec, dict) and "default" in spec:
            defaults[str(key)] = spec["default"]
    return defaults


def resolve_config_display_values(
    skill_meta: SkillMetadata,
    skill_instance: SkillInstance | None,
) -> dict[str, object]:
    """Merge JSON-schema defaults with instance overrides for L1 display."""
    schema = skill_meta.config_schema
    if not schema:
        return {}

    keys = _schema_property_keys(schema)
    if not keys:
        return {}

    defaults = _schema_default_values(schema)
    resolved: dict[str, object] = {}
    for key in keys:
        if skill_instance is not None:
            value = skill_instance.get_config(key, defaults.get(key))
        else:
            value = defaults.get(key)
        if value is not None:
            resolved[key] = value
    return resolved


def format_config_section(
    skill_meta: SkillMetadata,
    skill_instance: SkillInstance | None,
    resolved: dict[str, object],
) -> str:
    """Render [Skill config (...)] block; empty when nothing to show."""
    if not skill_meta.config_schema:
        return ""

    if resolved:
        from myrm_agent_harness.core.security.detection.leak_detector import redact_leaks

        instance_label = skill_instance.instance_name if skill_instance is not None else "default"
        lines = ["", f"[Skill config (instance: {instance_label})]"]
        for key, value in sorted(resolved.items()):
            display = redact_leaks(str(value) if value != "" else "(empty)")
            lines.append(f"  {key} = {display}")
        lines.append("[/Skill config]")
        return "\n".join(lines)

    keys = _schema_property_keys(skill_meta.config_schema)
    if not keys:
        return ""

    if skill_instance is None:
        return (
            "\n[Skill config]\n"
            "  This skill declares configurable values in Settings (Skill Instance). "
            "Configure an instance to expose resolved values here.\n"
            "[/Skill config]"
        )
    return ""


async def build_l1_disclosure_footer(
    skill_meta: SkillMetadata,
    skill_backend: SkillBackend,
    skill_instance: SkillInstance | None,
) -> str:
    """Build linked-files + config footer for storage skills (empty for MCP)."""
    if skill_meta.is_mcp_skill or not skill_meta.storage_skill_id:
        return ""

    sections: list[str] = []

    skill_id = skill_meta.storage_skill_id or skill_meta.name
    try:
        raw_resources = await skill_backend.list_skill_resources(skill_id)
    except Exception:
        raw_resources = []

    grouped = group_linked_resources(raw_resources)
    linked_section = format_linked_files_section(grouped)
    if linked_section:
        sections.append(linked_section)

    resolved_config = resolve_config_display_values(skill_meta, skill_instance)
    config_section = format_config_section(skill_meta, skill_instance, resolved_config)
    if config_section:
        sections.append(config_section)

    return "".join(sections)
