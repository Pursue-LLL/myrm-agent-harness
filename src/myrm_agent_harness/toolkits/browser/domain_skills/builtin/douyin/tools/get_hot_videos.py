"""Extract hot videos from Douyin via browser session.

Designed for execution inside the browser_execute_script sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as parameters.

[POS]
Domain skill tool for douyin.com feeds, hotlist, and video discovery pages.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


async def get_hot_videos(session: BrowserSession, args: dict[str, Any]) -> str:
    """Extract visible video titles and descriptions from the current Douyin page.

    Uses ARIA snapshot elements and fallback text extraction without relying
    on dynamic minified classes or canvas video tags.
    """
    max_videos = int(args.get("max_videos", 10))

    # Known trap mitigation: trigger smooth micro-scroll to force virtual list render
    try:
        await session.interact(action="scroll", text="350")
    except Exception:
        pass

    refs = session.get_all_refs()
    if not refs:
        await session.snapshot()
        refs = session.get_all_refs()

    videos: list[dict[str, str]] = []

    # Strategy 1: ARIA roles (link, text, article, heading)
    for ref_id, info in refs.items():
        if len(videos) >= max_videos:
            break
        text = (info.name or "").strip()
        role = info.role or ""
        if role in ("link", "article", "heading", "generic") and len(text) > 4:
            if any(term in text for term in ("#", "赞", "评", "热", "视频", "抖音")):
                videos.append(
                    {
                        "ref": ref_id,
                        "title": text[:200],
                        "role": role,
                    }
                )

    # Strategy 2: Text stream fallback
    if not videos:
        snapshot_text = await session.extract_text(max_length=50000)
        lines = [line.strip() for line in snapshot_text.splitlines() if line.strip()]
        for line in lines:
            if len(videos) >= max_videos:
                break
            if len(line) >= 4 and not line.startswith(("http", "www")):
                videos.append({"title": line[:200]})

    return json.dumps(videos, ensure_ascii=False, indent=2)
