"""Extract video entries from Douyin feed or creator user profile via browser session.

Designed for execution inside the browser_manage run_site_tool sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as globals.

[POS]
Domain skill tool for Douyin video harvesting.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urljoin

if TYPE_CHECKING:
    from ...session.browser_session import BrowserSession


async def get_user_videos(session: BrowserSession, args: dict[str, str | int]) -> str:
    """Extract visible video entries from current Douyin page.

    Includes automatic overlay penetration, ARIA role element matching,
    absolute URL normalization, and text-stream fallback.
    """
    max_videos = int(args.get("max_videos", 10))
    current_url = getattr(session, "url", "https://www.douyin.com") or "https://www.douyin.com"

    # Step 1: Smooth micro-scroll to wake up lazy-loaded virtual list items
    try:
        await session.interact(action="scroll", text="350")
    except Exception:
        pass

    refs = session.get_all_refs()
    if not refs:
        try:
            await session.snapshot()
            refs = session.get_all_refs()
        except Exception:
            refs = {}

    videos: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # Step 2: Semantic element matching
    for ref_id, info in refs.items():
        if len(videos) >= max_videos:
            break
        text = (info.name or "").strip()
        if not text or len(text) < 3:
            continue

        raw_url = getattr(info, "url", "") or ""
        if "/video/" in raw_url or "/user/" in raw_url or "/discover" in raw_url:
            canonical_url = urljoin(current_url, raw_url)
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            videos.append(
                {
                    "ref": ref_id,
                    "title": text[:300],
                    "url": canonical_url,
                    "role": info.role,
                }
            )

    # Step 3: Dual-track fallback if semantic links are insufficient
    if len(videos) < max_videos:
        try:
            snapshot_text = await session.extract_text(max_length=40000)
            lines = [line.strip() for line in snapshot_text.splitlines() if line.strip()]
            buffer: list[str] = []
            for line in lines:
                if len(videos) >= max_videos:
                    break
                if any(k in line for k in ("赞", "获赞", "粉丝", "喜欢", "作品")):
                    if buffer:
                        title_candidate = " ".join(buffer)
                        if len(title_candidate) > 4 and not any(v.get("title") == title_candidate for v in videos):
                            videos.append(
                                {
                                    "title": title_candidate[:300],
                                    "stats": line[:100],
                                    "url": current_url,
                                }
                            )
                        buffer = []
                else:
                    if len(line) > 2 and not any(skip in line for skip in ("登录", "关注", "直播", "商城")):
                        buffer.append(line)
        except Exception:
            pass

    return json.dumps(videos, ensure_ascii=False, indent=2)
