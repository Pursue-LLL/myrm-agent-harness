"""Render desktop AX snapshots for LLM consumption."""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta


def render_snapshot_tree(meta: SnapshotMeta, refs: dict[str, ElementRef]) -> str:
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

    lines = [header, "Use @dref IDs with desktop_interact_tool.", ""]
    for ref_id, element in refs.items():
        value_suffix = f' value="{element.value}"' if element.value else ""
        bbox = element.bbox
        lines.append(
            f'@{ref_id} {element.role} "{element.name}"{value_suffix} '
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
