"""Extract note entries from Xiaohongshu explore, search, or user profile via browser session.

Designed for execution inside the browser_manage run_site_tool sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as globals.

[POS]
Domain skill tool for Xiaohongshu (RED) harvesting.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urljoin

if TYPE_CHECKING:
    from ...session.browser_session import BrowserSession


async def get_explore_notes(session: BrowserSession, args: dict[str, str | int]) -> str:
    """Extract visible notes from current Xiaohongshu page.

    Includes automatic overlay penetration (Escape / micro-scroll),
    ARIA role element matching, absolute URL normalization, and text-stream fallback.
    """
    max_notes = int(args.get("max_notes", 10))
    current_url = getattr(session, "url", "https://www.xiaohongshu.com") or "https://www.xiaohongshu.com"

    # Step 1: Penetrate unauthenticated mask if present (press Escape then micro-scroll)
    try:
        await session.interact(action="press", text="Escape")
    except Exception:
        pass

    try:
        await session.interact(action="scroll", text="300")
    except Exception:
        pass

    refs = session.get_all_refs()
    if not refs:
        try:
            await session.snapshot()
            refs = session.get_all_refs()
        except Exception:
            refs = {}

    notes: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # Step 2: Semantic element matching
    for ref_id, info in refs.items():
        if len(notes) >= max_notes:
            break
        text = (info.name or "").strip()
        if not text or len(text) < 3:
            continue

        raw_url = getattr(info, "url", "") or ""
        if "/explore/" in raw_url or "/search_result/" in raw_url or "/user/profile/" in raw_url:
            canonical_url = urljoin(current_url, raw_url)
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            notes.append(
                {
                    "ref": ref_id,
                    "title": text[:300],
                    "url": canonical_url,
                    "role": info.role,
                }
            )

    # Step 3: Dual-track fallback if semantic links are insufficient
    if len(notes) < max_notes:
        try:
            snapshot_text = await session.extract_text(max_length=40000)
            lines = [line.strip() for line in snapshot_text.splitlines() if line.strip()]
            buffer: list[str] = []
            for line in lines:
                if len(notes) >= max_notes:
                    break
                if any(k in line for k in ("赞", "收藏", "评论", "关注", "作者")):
                    if buffer:
                        title_candidate = " ".join(buffer)
                        if len(title_candidate) > 4 and not any(n.get("title") == title_candidate for n in notes):
                            notes.append(
                                {
                                    "title": title_candidate[:300],
                                    "stats": line[:100],
                                    "url": current_url,
                                }
                            )
                        buffer = []
                else:
                    if len(line) > 2 and not any(skip in line for skip in ("登录", "注册", "探索", "发现", "通知")):
                        buffer.append(line)
        except Exception:
            pass

    return json.dumps(notes, ensure_ascii=False, indent=2)
