"""RSS/Atom feed fetch tool for agents.

Provides structured feed parsing so agents can consume RSS/Atom feeds
without wasting tokens on raw XML. Uses stdlib xml.etree for zero
additional dependencies.

[INPUT]
- (none)

[OUTPUT]
- create_rss_tool: Create a LangChain tool that fetches and parses RSS/Atom feeds.

[POS]
RSS/Atom feed fetch tool for agents.
"""

from __future__ import annotations

import logging
from xml.etree.ElementTree import ParseError, fromstring

import httpx
from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 20
_TIMEOUT_SECONDS = 15
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB

# Namespace prefixes commonly used in RSS/Atom feeds
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"


def _text(el: object, tag: str) -> str:
    """Extract text from a child element, or empty string."""
    from xml.etree.ElementTree import Element

    if not isinstance(el, Element):
        return ""
    child = el.find(tag)
    if child is None:
        return ""
    return (child.text or "").strip()


def _parse_rss2(root: object) -> list[dict[str, str]]:
    """Parse RSS 2.0 <channel><item> structure."""
    from xml.etree.ElementTree import Element

    if not isinstance(root, Element):
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    entries: list[dict[str, str]] = []
    for item in channel.findall("item")[:_MAX_ENTRIES]:
        entries.append({
            "title": _text(item, "title"),
            "link": _text(item, "link"),
            "summary": _text(item, "description")[:500],
            "published": _text(item, "pubDate") or _text(item, f"{_DC_NS}date"),
        })
    return entries


def _parse_atom(root: object) -> list[dict[str, str]]:
    """Parse Atom <feed><entry> structure."""
    from xml.etree.ElementTree import Element

    if not isinstance(root, Element):
        return []
    entries: list[dict[str, str]] = []
    for entry in root.findall(f"{_ATOM_NS}entry")[:_MAX_ENTRIES]:
        link_el = entry.find(f"{_ATOM_NS}link[@rel='alternate']")
        if link_el is None:
            link_el = entry.find(f"{_ATOM_NS}link")
        link = (link_el.get("href", "") if link_el is not None else "").strip()

        summary_el = entry.find(f"{_ATOM_NS}summary")
        if summary_el is None:
            summary_el = entry.find(f"{_ATOM_NS}content")
        summary = ((summary_el.text or "") if summary_el is not None else "").strip()[:500]

        entries.append({
            "title": _text(entry, f"{_ATOM_NS}title"),
            "link": link,
            "summary": summary,
            "published": _text(entry, f"{_ATOM_NS}published") or _text(entry, f"{_ATOM_NS}updated"),
        })
    return entries


def _parse_feed(xml_text: str) -> tuple[str, list[dict[str, str]]]:
    """Detect feed type and parse. Returns (feed_title, entries)."""
    root = fromstring(xml_text)

    # RSS 2.0: root is <rss> with <channel>
    if root.tag == "rss" or root.find("channel") is not None:
        channel = root.find("channel")
        title = _text(channel, "title") if channel is not None else ""
        return title, _parse_rss2(root)

    # Atom: root is <feed> in atom namespace
    if root.tag == f"{_ATOM_NS}feed" or root.tag == "feed":
        title = _text(root, f"{_ATOM_NS}title") or _text(root, "title")
        return title, _parse_atom(root)

    # RDF/RSS 1.0 fallback
    if "rss" in root.tag.lower() or root.find("channel") is not None:
        channel = root.find("channel")
        title = _text(channel, "title") if channel is not None else ""
        return title, _parse_rss2(root)

    raise ParseError(f"Unrecognized feed format: root tag = {root.tag}")


def create_rss_tool() -> list[BaseTool]:
    """Create a LangChain tool for fetching and parsing RSS/Atom feeds."""

    @tool("rss_fetch")
    async def rss_fetch(url: str, max_items: int = 10) -> str:
        """Fetch and parse an RSS or Atom feed URL, returning structured entries.

        Returns structured data: feed title and entries with title, link,
        summary (first 500 chars), and published date. Much more efficient
        than fetching raw HTML/XML and parsing with the LLM.

        Args:
            url: The RSS/Atom feed URL to fetch (e.g. https://example.com/rss.xml).
            max_items: Maximum number of entries to return (1-20, default 10).
        """
        max_items = min(max(1, max_items), _MAX_ENTRIES)

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": "MyrM-RSS/1.0 (+https://myrm.ai)"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                if len(resp.content) > _MAX_RESPONSE_BYTES:
                    return f"Error: Feed response too large ({len(resp.content)} bytes, max {_MAX_RESPONSE_BYTES})."

                xml_text = resp.text
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} fetching {url}."
        except httpx.RequestError as e:
            return f"Error: Failed to fetch {url} — {type(e).__name__}: {e}"

        try:
            feed_title, entries = _parse_feed(xml_text)
        except (ParseError, Exception) as e:
            return f"Error: Failed to parse feed XML — {type(e).__name__}: {e}"

        entries = entries[:max_items]
        if not entries:
            return f"Feed '{feed_title}' returned 0 entries."

        lines = [f"# {feed_title}" if feed_title else "# RSS Feed", f"({len(entries)} entries)\n"]
        for i, entry in enumerate(entries, 1):
            lines.append(f"## {i}. {entry['title']}")
            if entry["link"]:
                lines.append(f"Link: {entry['link']}")
            if entry["published"]:
                lines.append(f"Date: {entry['published']}")
            if entry["summary"]:
                lines.append(f"{entry['summary']}")
            lines.append("")

        return "\n".join(lines)

    return [rss_fetch]
