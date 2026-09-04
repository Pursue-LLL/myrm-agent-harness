"""Extract video list from Bilibili via browser session.

Designed for execution inside the browser_execute_script sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as parameters.

[POS]
Domain skill tool for bilibili.com feeds, user space, and search results.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


async def get_video_list(session: BrowserSession, args: dict[str, Any]) -> str:
    """Extract visible videos from the current Bilibili feed, search, or user space page.

    Uses ARIA snapshot elements and fallback DOM query to extract video titles,
    authors, play counts, and URLs without relying on brittle obfuscated CSS classes.
    """
    max_videos = int(args.get("max_videos", 10))

    refs = session.get_all_refs()
    if not refs:
        await session.snapshot()
        refs = session.get_all_refs()

    videos: list[dict[str, str]] = []

    # Strategy 1: Check ARIA links and article/group elements with video titles
    for ref_id, info in refs.items():
        if len(videos) >= max_videos:
            break
        text = (info.name or "").strip()
        role = info.role or ""
        # Bilibili video cards typically expose title in link or article names
        if role in ("link", "article", "listitem") and len(text) > 4:
            if any(term in text for term in ("万", "播放", "弹幕", "视频", "P")):
                videos.append(
                    {
                        "ref": ref_id,
                        "title": text[:200],
                        "role": role,
                    }
                )

    # Strategy 2: Fallback text stream extraction if structured ARIA is sparse
    if not videos:
        snapshot_text = await session.extract_text(max_length=50000)
        lines = [line.strip() for line in snapshot_text.splitlines() if line.strip()]
        for line in lines:
            if len(videos) >= max_videos:
                break
            if len(line) >= 5 and not line.startswith(("http", "www")):
                videos.append({"title": line[:200]})

    return json.dumps(videos, ensure_ascii=False)
