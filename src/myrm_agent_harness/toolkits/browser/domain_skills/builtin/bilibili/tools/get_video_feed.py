"""Extract video feed items from Bilibili.

Extracts titles, authors, view counts, danmaku counts, and links.
Supports home feed, ranking, channel, and search result pages.

[INPUT]
- session: BrowserSession
- args: {"max_items": int} (default: 10)

[OUTPUT]
- JSON string array of video items

[POS]
Bilibili domain skill executable tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_video_feed(session: Any, args: dict[str, Any]) -> str:
    """Extract video cards from current Bilibili page."""
    max_items = int(args.get("max_items", 10))
    videos: list[dict[str, str]] = []

    # 1. Primary track: DOM evaluate query for structured card elements
    try:
        eval_script = """
        () => {
            const results = [];
            const cards = document.querySelectorAll(
                '.bili-video-card, .feed-card, .video-card, .rank-item, .bili-video-card__wrap, .video-list-item'
            );
            for (const el of cards) {
                const titleEl = el.querySelector(
                    '.bili-video-card__info--tit, h3, .title, a[title]'
                );
                const authorEl = el.querySelector(
                    '.bili-video-card__info--author, .up-name, .author, .bili-video-card__info--owner'
                );
                const stats = el.querySelectorAll(
                    '.bili-video-card__stats--item, .so-icon, .play-text, .bili-video-card__stats--text'
                );
                const linkEl = el.querySelector('a[href*="/video/"], a[href*="bilibili.com/video/"]') || el.querySelector('a');

                let title = titleEl ? (titleEl.getAttribute('title') || titleEl.innerText || '').trim() : '';
                let author = authorEl ? (authorEl.innerText || '').trim() : '';
                let play = stats.length > 0 ? (stats[0].innerText || '').trim() : '';
                let danmaku = stats.length > 1 ? (stats[1].innerText || '').trim() : '';
                let href = linkEl ? (linkEl.href || linkEl.getAttribute('href') || '') : '';

                if (title && title.length > 2) {
                    results.push({
                        title: title,
                        author: author,
                        play_count: play,
                        danmaku: danmaku,
                        url: href
                    });
                }
            }
            return results;
        }
        """
        page = getattr(session, "page", None)
        if page is not None and hasattr(page, "evaluate"):
            items = await page.evaluate(eval_script)
            if isinstance(items, list) and items:
                for it in items[:max_items]:
                    videos.append({
                        "title": str(it.get("title", "")),
                        "author": str(it.get("author", "")),
                        "play_count": str(it.get("play_count", "")),
                        "danmaku": str(it.get("danmaku", "")),
                        "url": str(it.get("url", "")),
                    })
    except Exception as exc:
        logger.debug("Bilibili DOM evaluate track encountered non-fatal error: %s", exc)

    # 2. Secondary fallback track: ARIA snapshot refs
    if not videos:
        refs = session.get_all_refs() if hasattr(session, "get_all_refs") else {}
        if not refs and hasattr(session, "snapshot"):
            await session.snapshot()
            refs = session.get_all_refs() if hasattr(session, "get_all_refs") else {}

        for ref_id, info in refs.items():
            if len(videos) >= max_items:
                break
            name = (info.name or "").strip()
            # Bilibili video links usually contain BV/av or title text
            if info.role in ("link", "article") and len(name) > 8:
                if any(kw in name for kw in ("UP", "播放", "弹幕", "BV", "观看")):
                    videos.append({
                        "title": name[:150],
                        "author": "",
                        "play_count": "",
                        "danmaku": "",
                        "url": "",
                        "ref": ref_id,
                    })

    # 3. Tertiary fallback track: text content parsing
    if not videos and hasattr(session, "extract_text"):
        raw_text = await session.extract_text(max_length=40000)
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        for line in lines:
            if len(videos) >= max_items:
                break
            if len(line) > 12 and any(k in line for k in ("UP", "观看", "弹幕", "万", "亿")):
                videos.append({
                    "title": line[:150],
                    "author": "",
                    "play_count": "",
                    "danmaku": "",
                    "url": "",
                })

    return json.dumps(videos, ensure_ascii=False, indent=2)
