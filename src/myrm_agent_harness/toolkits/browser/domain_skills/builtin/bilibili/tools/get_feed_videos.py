"""Extract video items from Bilibili feed, search results, or user space via browser session.

Designed for execution inside the browser_manage run_site_tool sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as globals.

[POS]
Domain skill tool for Bilibili video harvesting.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urljoin

if TYPE_CHECKING:
    from ...session.browser_session import BrowserSession


async def get_feed_videos(session: BrowserSession, args: dict[str, str | int]) -> str:
    """Extract visible video entries from current Bilibili page.

    Combines ARIA link/article semantic inspection with safe text extraction.
    Auto-triggers smooth scroll to wake up lazy-loaded cards and standardizes URLs.
    """
    max_videos = int(args.get("max_videos", 10))
    current_url = getattr(session, "url", "https://www.bilibili.com") or "https://www.bilibili.com"

    # Step 1: Smooth micro-scroll to wake up content-visibility: auto cards
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
        name = (info.name or "").strip()
        if not name or len(name) < 4:
            continue

        raw_url = getattr(info, "url", "") or ""
        # Check for typical Bilibili video path indicators
        if "/video/BV" in raw_url or "/video/av" in raw_url or "/bangumi/play/" in raw_url:
            canonical_url = urljoin(current_url, raw_url)
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            videos.append(
                {
                    "ref": ref_id,
                    "title": name[:300],
                    "url": canonical_url,
                    "role": info.role,
                }
            )

    # Step 3: Dual-track fallback if semantic refs are insufficient
    if len(videos) < max_videos:
        try:
            snapshot_text = await session.extract_text(max_length=40000)
            lines = [line.strip() for line in snapshot_text.splitlines() if line.strip()]
            buffer: list[str] = []
            for line in lines:
                if len(videos) >= max_videos:
                    break
                if any(k in line for k in ("播放", "弹幕", "点赞", "观看", "小时前", "天前", "UP", "up")):
                    if buffer:
                        title_candidate = " ".join(buffer)
                        if len(title_candidate) > 5 and not any(v.get("title") == title_candidate for v in videos):
                            videos.append(
                                {
                                    "title": title_candidate[:300],
                                    "stats": line[:100],
                                    "url": current_url,
                                }
                            )
                        buffer = []
                else:
                    if len(line) > 3 and not any(skip in line for skip in ("首页", "动态", "历史", "创作中心")):
                        buffer.append(line)
        except Exception:
            pass

    return json.dumps(videos, ensure_ascii=False, indent=2)
