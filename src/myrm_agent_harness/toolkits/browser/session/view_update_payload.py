"""Shared browser inspector view payload builder for SSE and REST snapshot APIs.

[INPUT]
- session.snapshot_result::SnapshotResult (POS: immutable browser ARIA snapshot result)
- toolkits.browser.snapshot::RefInfo (POS: element reference metadata with optional BBox)

[OUTPUT]
- capture_browser_view_update_data: live screenshot + refs payload from BrowserSession
- build_browser_view_update_data: normalized payload dict for SSE and REST consumers

[POS]
Single source of truth for WebUI Browser Inspector payload shape (screenshot + refs + page meta).
"""

from __future__ import annotations

from collections.abc import Mapping

from myrm_agent_harness.toolkits.browser.session.snapshot_result import SnapshotResult
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo


def refs_data_from_ref_map(
    refs: Mapping[str, RefInfo],
) -> dict[str, dict[str, object]]:
    """Serialize RefInfo map for frontend BrowserRefInfo overlay."""
    payload: dict[str, dict[str, object]] = {}
    for ref_id, info in refs.items():
        entry: dict[str, object] = {
            "role": info.role,
            "name": info.name,
            "nth": info.nth,
            "position": info.position,
        }
        if info.bbox is not None:
            bbox = info.bbox
            entry["bbox"] = {
                "x": bbox.x,
                "y": bbox.y,
                "width": bbox.width,
                "height": bbox.height,
                "centerX": bbox.centerX,
                "centerY": bbox.centerY,
                "viewport_x": bbox.viewport_x,
                "viewport_y": bbox.viewport_y,
                "viewport_width": bbox.viewport_width,
                "viewport_height": bbox.viewport_height,
            }
        else:
            entry["bbox"] = None
        payload[ref_id] = entry
    return payload


def refs_data_from_snapshot_result(snapshot_result: SnapshotResult) -> dict[str, dict[str, object]]:
    return refs_data_from_ref_map(dict(snapshot_result.refs))


def resolve_viewport_from_refs(
    refs_data: dict[str, dict[str, object]],
    *,
    default_width: int = 1280,
    default_height: int = 720,
) -> tuple[int, int]:
    for info in refs_data.values():
        bbox = info.get("bbox")
        if isinstance(bbox, dict) and bbox.get("viewport_width"):
            return int(bbox["viewport_width"]), int(bbox["viewport_height"])
    return default_width, default_height


def build_browser_view_update_data(
    *,
    screenshot_base64: str,
    refs_data: dict[str, dict[str, object]],
    page_url: str,
    page_title: str,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
) -> dict[str, object]:
    if viewport_width is None or viewport_height is None:
        vw, vh = resolve_viewport_from_refs(refs_data)
        viewport_width = viewport_width if viewport_width is not None else vw
        viewport_height = viewport_height if viewport_height is not None else vh
    return {
        "screenshot_base64": screenshot_base64,
        "mime_type": "image/jpeg" if screenshot_base64 else "",
        "refs": refs_data,
        "page_url": page_url,
        "page_title": page_title,
        "viewport_width": viewport_width,
        "viewport_height": viewport_height,
    }


async def capture_browser_view_update_data(
    session: object,
    *,
    snapshot_result: SnapshotResult | None = None,
) -> dict[str, object]:
    """Capture screenshot + refs payload from a live BrowserSession."""
    from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession

    if not isinstance(session, BrowserSession):
        raise TypeError("session must be BrowserSession")

    if snapshot_result is None:
        snapshot_result = await session.snapshot(
            scope="interactive",
            compact=True,
            diff=False,
            include_bbox=True,
            max_tokens=4000,
            publish_inspector_view=False,
        )

    refs_data = refs_data_from_snapshot_result(snapshot_result)
    screenshot_b64 = await session.extract_screenshot(scale=1.0)

    page_url = ""
    page_title = ""
    tab_ctrl = getattr(session, "_tab_controller", None)
    if tab_ctrl is not None:
        try:
            page = tab_ctrl.get_active_page()
            if page is not None:
                page_url = page.url
                page_title = await page.title()
        except Exception:
            pass

    return build_browser_view_update_data(
        screenshot_base64=screenshot_b64,
        refs_data=refs_data,
        page_url=page_url,
        page_title=page_title,
    )


__all__ = [
    "build_browser_view_update_data",
    "capture_browser_view_update_data",
    "refs_data_from_ref_map",
    "refs_data_from_snapshot_result",
    "resolve_viewport_from_refs",
]
