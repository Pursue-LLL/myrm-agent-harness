"""Extract posts from X (Twitter) timeline via browser session.

Designed for execution inside the browser_execute_script sandbox.
Receives ``session`` (BrowserSession) and ``args`` dict as globals.
"""

from __future__ import annotations


async def get_timeline_posts(session, args: dict) -> str:  # type: ignore[type-arg]
    """Extract visible posts from the current X timeline or profile page.

    Uses ARIA snapshot to locate article-role elements, then extracts text
    content without relying on fragile CSS selectors.
    """
    import json

    max_posts = int(args.get("max_posts", 10))

    refs = session.get_all_refs()
    posts: list[dict[str, str]] = []

    for ref_id, info in refs.items():
        if len(posts) >= max_posts:
            break
        if info.role == "article":
            text = info.name or ""
            if text and len(text) > 10:
                posts.append({
                    "ref": ref_id,
                    "text": text[:500],
                    "role": info.role,
                })

    if not posts:
        snapshot_text = await session.get_text_snapshot()
        lines = snapshot_text.split("\n")
        current_post: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_post and len(" ".join(current_post)) > 20:
                    posts.append({"text": " ".join(current_post)[:500]})
                    current_post = []
                    if len(posts) >= max_posts:
                        break
                continue
            current_post.append(stripped)
        if current_post and len(posts) < max_posts and len(" ".join(current_post)) > 20:
            posts.append({"text": " ".join(current_post)[:500]})

    return json.dumps(posts, ensure_ascii=False, indent=2)
