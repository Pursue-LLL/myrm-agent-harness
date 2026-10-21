"""Render desktop AX snapshots for LLM consumption.

[INPUT]
- dref.types::ElementRef, SnapshotMeta (POS: @dref snapshot metadata)
- perception.ax_diff::RefDiff, UpdatedRef (POS: incremental diff result)

[OUTPUT]
- render_snapshot_tree(): full-tree text (+ optional `[N]` SOM prefixes) + enriched SnapshotMeta
- render_diff_tree(): incremental diff text for follow-up snapshots

[POS]
Text serialization for desktop_snapshot_tool AX trees (full and incremental diff).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.perception.ax_diff import RefDiff


def render_snapshot_tree(
    meta: SnapshotMeta,
    refs: dict[str, ElementRef],
    *,
    som_index_map: dict[str, int] | None = None,
) -> tuple[str, SnapshotMeta]:
    header_parts = [
        f"[{meta.ref_count} refs",
        f"app: {meta.app_name or 'unknown'}",
        f"window: {meta.window_title or 'unknown'}",
        f"scope: {meta.scope}",
    ]
    if meta.truncated:
        header_parts.append("truncated")
    if meta.needs_permission:
        header_parts.append("permission_required")
    header = " | ".join(header_parts) + "]"

    hint = "Use @dref IDs with desktop_interact_tool."
    if som_index_map:
        hint += " [N] labels match numbered regions on the screenshot."
    lines = [header, hint, ""]

    ordered_refs = sorted(refs.items(), key=lambda item: item[0])
    for ref_id, element in ordered_refs:
        value_suffix = f' value="{element.value}"' if element.value else ""
        bbox = element.bbox
        prefix = ""
        if som_index_map and ref_id in som_index_map:
            prefix = f"[{som_index_map[ref_id]}] "
        lines.append(
            f'{prefix}@{ref_id} {element.role} "{element.name}"{value_suffix} '
            f"bbox=({bbox.x},{bbox.y} {bbox.width}x{bbox.height}) "
            f"actions=[{', '.join(element.actions)}]"
        )
    body = "\n".join(lines)
    token_estimate = max(1, len(body) // 4)
    enriched_meta = SnapshotMeta(
        ref_count=meta.ref_count,
        app_name=meta.app_name,
        window_title=meta.window_title,
        scope=meta.scope,
        truncated=meta.truncated,
        needs_permission=meta.needs_permission,
        token_estimate=token_estimate,
    )
    return body, enriched_meta


def render_diff_tree(
    meta: SnapshotMeta,
    diff: RefDiff,
) -> tuple[str, SnapshotMeta]:
    """Render an incremental diff for LLM consumption.

    Produces a compact text block showing only added/updated/removed refs,
    with total change count in the header.
    """
    change_count = len(diff.added) + len(diff.updated) + len(diff.removed)

    if change_count == 0:
        body = (
            f"[app: {meta.app_name or 'unknown'} | scope: {meta.scope}]\n"
            "Desktop state unchanged (0 changes vs previous snapshot)."
        )
        token_estimate = max(1, len(body) // 4)
        enriched = SnapshotMeta(
            ref_count=meta.ref_count,
            app_name=meta.app_name,
            window_title=meta.window_title,
            scope=meta.scope,
            truncated=meta.truncated,
            needs_permission=meta.needs_permission,
            token_estimate=token_estimate,
        )
        return body, enriched

    lines = [
        f"Desktop diff ({change_count} change{'s' if change_count != 1 else ''} "
        f"vs previous snapshot, app: {meta.app_name or 'unknown'}):",
    ]

    for el in diff.added:
        value_part = f' value="{el.value}"' if el.value else ""
        lines.append(f'+ @{el.ref_id} {el.role} "{el.name}"{value_part} actions=[{", ".join(el.actions)}]')

    for upd in diff.updated:
        el = upd.element
        fields_str = ", ".join(upd.changed_fields)
        value_part = f' value="{el.value}"' if el.value else ""
        lines.append(f'~ @{upd.ref_id} {el.role} "{el.name}"{value_part} changed=[{fields_str}]')

    for ref_id in diff.removed:
        lines.append(f"- @{ref_id} (removed)")

    body = "\n".join(lines)
    token_estimate = max(1, len(body) // 4)
    enriched = SnapshotMeta(
        ref_count=meta.ref_count,
        app_name=meta.app_name,
        window_title=meta.window_title,
        scope=meta.scope,
        truncated=meta.truncated,
        needs_permission=meta.needs_permission,
        token_estimate=token_estimate,
    )
    return body, enriched
