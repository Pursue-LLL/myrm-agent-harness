"""Twitter / X post fast-path extractor.

Extracts post content, author metadata, engagement metrics, and media links
via lightweight public APIs (FxTwitter / VxTwitter / oEmbed).
Used as a fast-path shortcut in FetchEngine when an X or Twitter URL is detected,
bypassing browser-based crawling to deliver <150ms structured Markdown Documents.

When the fast-path is unavailable or returns 404, FetchEngine degrades gracefully.

[INPUT]
- x.com or twitter.com post URL

[OUTPUT]
- is_x_url: Detect x.com / twitter.com status URLs
- extract_x_post: Fetch + parse post into Document, or None
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from langchain_core.documents import Document

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool

logger = logging.getLogger(__name__)

_X_STATUS_RE = re.compile(
    r"(?:https?://)?"
    r"(?:(?:www\.|mobile\.)?(?:twitter\.com|x\.com|vxtwitter\.com|fxtwitter\.com|fixupx\.com))"
    r"/([a-zA-Z0-9_]+)/status/(\d+)",
    re.IGNORECASE,
)

_REQUEST_TIMEOUT = 8
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def is_x_url(url: str) -> bool:
    """Return True when url is a valid Twitter/X post status link."""
    if not url:
        return False
    return _X_STATUS_RE.search(url.strip()) is not None


def extract_status_info(url: str) -> tuple[str, str] | None:
    """Extract (screen_name, status_id) from an X/Twitter URL."""
    match = _X_STATUS_RE.search(url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _build_opener(proxy_pool: ProxyPool | None = None) -> urllib.request.OpenerDirector:
    """Build urllib opener with optional proxy support."""
    if proxy_pool:
        proxy_config = proxy_pool.get_next()
        proxy_url = proxy_config.to_url()
        handler = urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def _fetch_fxtwitter_data(
    screen_name: str,
    status_id: str,
    opener: urllib.request.OpenerDirector,
) -> dict | None:
    """Fetch structured post data via api.fxtwitter.com."""
    endpoint = f"https://api.fxtwitter.com/{screen_name}/status/{status_id}"
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with opener.open(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 200 and "tweet" in data:
                return data["tweet"]
    except Exception as exc:
        logger.debug("FxTwitter API fetch failed for %s/%s: %s", screen_name, status_id, exc)
    return None


def _fetch_oembed_data(
    url: str,
    opener: urllib.request.OpenerDirector,
) -> dict | None:
    """Fallback: Fetch oEmbed metadata via publish.twitter.com."""
    endpoint = f"https://publish.twitter.com/oembed?url={url}&omit_script=true"
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    try:
        with opener.open(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Twitter oEmbed fetch failed for %s: %s", url, exc)
    return None


def _format_tweet_document(tweet: dict, original_url: str) -> Document:
    """Convert FxTwitter tweet dict to structured Markdown Document."""
    author = tweet.get("author", {})
    author_name = author.get("name", "")
    screen_name = author.get("screen_name", "")
    text = tweet.get("text", "").strip()
    created_at = tweet.get("created_at", "")
    likes = tweet.get("likes", 0)
    retweets = tweet.get("retweets", 0)
    replies = tweet.get("replies", 0)

    header = f"**{author_name}** (@{screen_name})" if screen_name else f"**{author_name}**"
    lines: list[str] = [header]
    if created_at:
        lines.append(f"*发布时间*: {created_at}")
    lines.append("")
    lines.append(text)

    # Media attachments (photos / videos)
    media = tweet.get("media", {})
    photos = media.get("photos", []) if isinstance(media, dict) else []
    videos = media.get("videos", []) if isinstance(media, dict) else []
    
    media_urls: list[str] = []
    for p in photos:
        if isinstance(p, dict) and p.get("url"):
            media_urls.append(p["url"])
            lines.append(f"![Image]({p['url']})")
    for v in videos:
        if isinstance(v, dict) and v.get("thumbnail_url"):
            media_urls.append(v.get("url") or v["thumbnail_url"])

    # Engagement line
    engagement_parts: list[str] = []
    if retweets:
        engagement_parts.append(f"🔁 {retweets} 转发")
    if likes:
        engagement_parts.append(f"❤️ {likes} 喜欢")
    if replies:
        engagement_parts.append(f"💬 {replies} 回复")
    if engagement_parts:
        lines.append("")
        lines.append(f"> {' · '.join(engagement_parts)}")

    page_content = "\n".join(lines).strip()

    metadata: dict[str, str | int] = {
        "url": original_url,
        "title": f"Post by @{screen_name}: {text[:60]}..." if len(text) > 60 else f"Post by @{screen_name}: {text}",
        "author": author_name,
        "screen_name": screen_name,
        "source_type": "x_post",
        "likes": likes,
        "retweets": retweets,
    }
    if created_at:
        metadata["created_at"] = created_at
    if media_urls:
        metadata["media_urls"] = json.dumps(media_urls, ensure_ascii=False)

    return Document(page_content=page_content, metadata=metadata)


def _format_oembed_document(oembed: dict, original_url: str) -> Document:
    """Convert oEmbed dict to fallback Document."""
    author_name = oembed.get("author_name", "")
    author_url = oembed.get("author_url", "")
    raw_html = oembed.get("html", "")
    
    # Strip HTML tags simply
    text_content = re.sub(r"<[^>]+>", " ", raw_html).strip()
    text_content = re.sub(r"\s+", " ", text_content)

    lines: list[str] = []
    if author_name:
        lines.append(f"**{author_name}** ({author_url})")
        lines.append("")
    lines.append(text_content)

    return Document(
        page_content="\n".join(lines),
        metadata={
            "url": original_url,
            "title": f"Post by {author_name}",
            "author": author_name,
            "source_type": "x_post_oembed",
        },
    )


async def extract_x_post(
    url: str,
    *,
    proxy_pool: ProxyPool | None = None,
) -> Document | None:
    """Extract Twitter / X post and return as Document, or None on failure.

    Args:
        url: Status URL (x.com/user/status/123 or twitter.com/...)
        proxy_pool: Optional proxy pool for network egress.

    Returns:
        Document with structured post markdown and metadata, or None.
    """
    if not is_x_url(url):
        return None

    status_info = extract_status_info(url)
    if not status_info:
        return None

    screen_name, status_id = status_info
    opener = _build_opener(proxy_pool)

    def _do_fetch() -> Document | None:
        # Tier 1: FxTwitter API (Rich JSON)
        tweet = _fetch_fxtwitter_data(screen_name, status_id, opener)
        if tweet:
            return _format_tweet_document(tweet, url)

        # Tier 2: Twitter official oEmbed (HTML Embed fallback)
        oembed = _fetch_oembed_data(url, opener)
        if oembed:
            return _format_oembed_document(oembed, url)

        return None

    return await asyncio.to_thread(_do_fetch)
