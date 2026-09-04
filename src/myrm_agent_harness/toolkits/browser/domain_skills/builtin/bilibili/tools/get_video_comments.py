"""Extract video comments from Bilibili video detail page.

Extracts usernames, comment text, like counts, and reply timestamps.

[INPUT]
- session: BrowserSession
- args: {"max_comments": int} (default: 10)

[OUTPUT]
- JSON string array of comment items

[POS]
Bilibili domain skill executable tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_video_comments(session: Any, args: dict[str, Any]) -> str:
    """Extract comments from current Bilibili video page."""
    max_comments = int(args.get("max_comments", 10))
    comments: list[dict[str, str]] = []

    # 1. Primary track: DOM evaluate query for comment items
    try:
        eval_script = """
        () => {
            const results = [];
            const items = document.querySelectorAll(
                'bili-comment-thread-renderer, bili-comment-action-buttons-renderer, .reply-item, .comment-item, .bili-comment-item'
            );
            for (const el of items) {
                const userEl = el.querySelector('#user-name, .user-name, .name, .reply-item .user');
                const contentEl = el.querySelector('#content, .reply-content, .text-con, .comment-content');
                const likeEl = el.querySelector('#like-count, .reply-like, .like-count, .like');
                const timeEl = el.querySelector('#pubdate, .reply-time, .pubdate, .time');

                let user = userEl ? (userEl.innerText || '').trim() : '';
                let content = contentEl ? (contentEl.innerText || '').trim() : '';
                let like = likeEl ? (likeEl.innerText || '').trim() : '';
                let pubtime = timeEl ? (timeEl.innerText || '').trim() : '';

                if (content && content.length > 1) {
                    results.push({
                        user: user,
                        comment: content,
                        like_count: like,
                        time: pubtime
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
                for it in items[:max_comments]:
                    comments.append({
                        "user": str(it.get("user", "")),
                        "comment": str(it.get("comment", "")),
                        "like_count": str(it.get("like_count", "")),
                        "time": str(it.get("time", "")),
                    })
    except Exception as exc:
        logger.debug("Bilibili comments evaluate track encountered non-fatal error: %s", exc)

    # 2. Secondary fallback track: ARIA snapshot refs
    if not comments:
        refs = session.get_all_refs() if hasattr(session, "get_all_refs") else {}
        if not refs and hasattr(session, "snapshot"):
            await session.snapshot()
            refs = session.get_all_refs() if hasattr(session, "get_all_refs") else {}

        for ref_id, info in refs.items():
            if len(comments) >= max_comments:
                break
            name = (info.name or "").strip()
            # Bilibili comment refs often contain 回复 or 点赞
            if info.role in ("article", "listitem") and len(name) > 10:
                comments.append({
                    "user": "",
                    "comment": name[:300],
                    "like_count": "",
                    "time": "",
                    "ref": ref_id,
                })

    return json.dumps(comments, ensure_ascii=False, indent=2)
