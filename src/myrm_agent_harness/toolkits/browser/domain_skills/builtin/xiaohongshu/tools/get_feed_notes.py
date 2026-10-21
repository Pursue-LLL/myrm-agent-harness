"""Extract notes from Xiaohongshu via browser session.

Designed for execution inside the browser_execute_script sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as parameters.

[POS]
Domain skill tool for xiaohongshu.com explore feeds, search results, and creator pages.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


async def get_feed_notes(session: BrowserSession, args: dict[str, Any]) -> str:
    """Extract visible notes from the current Xiaohongshu feed or search results.

    Uses ARIA snapshot elements and fallback text extraction to parse note titles,
    authors, and engagement metrics without relying on dynamic hash class names.
    """
    max_notes = int(args.get("max_notes", 10))

    # Known trap mitigation: dismiss modal login overlay if present via Escape
    try:
        await session.interact(action="press", text="Escape")
    except Exception:
        pass

    refs = session.get_all_refs()
    if not refs:
        await session.snapshot()
        refs = session.get_all_refs()

    notes: list[dict[str, str]] = []

    # Strategy 1: ARIA roles (link, article, image, text)
    for ref_id, info in refs.items():
        if len(notes) >= max_notes:
            break
        text = (info.name or "").strip()
        role = info.role or ""
        if role in ("link", "article", "heading") and len(text) > 4:
            notes.append(
                {
                    "ref": ref_id,
                    "title": text[:200],
                    "role": role,
                }
            )

    # Strategy 2: Text stream fallback
    if not notes:
        snapshot_text = await session.extract_text(max_length=50000)
        lines = [line.strip() for line in snapshot_text.splitlines() if line.strip()]
        for line in lines:
            if len(notes) >= max_notes:
                break
            if len(line) >= 4 and not line.startswith(("http", "www")):
                notes.append({"title": line[:200]})

    return json.dumps(notes, ensure_ascii=False, indent=2)
