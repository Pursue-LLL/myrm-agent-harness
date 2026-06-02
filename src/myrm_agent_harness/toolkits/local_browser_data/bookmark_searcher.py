"""Chromium bookmark JSON search.


[INPUT]
- types::BrowserProfile (POS: browser profile info)
- types::BookmarkResult (POS: bookmark search result)

[OUTPUT]
- search_bookmarks: search bookmarks in specified profile

[POS]
Chromium bookmark retriever. Recursively traverses Bookmarks JSON file,
supports multi-keyword AND matching (title + url), preserving bookmark folder path info.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from .types import BookmarkResult, BrowserProfile

logger = logging.getLogger(__name__)


def search_bookmarks(
    browser_data_dir: str,
    profile: BrowserProfile,
    keywords: Sequence[str],
) -> list[BookmarkResult]:
    """Search bookmarks in a Chromium profile.

    Recursively walks the Bookmarks JSON tree, matching entries
    where **all** keywords appear in the title or URL (case-insensitive AND).

    Args:
        browser_data_dir: Browser data directory path.
        profile: Browser profile to search.
        keywords: Search keywords (all must match).

    Returns:
        Matching bookmark results. Empty list if no keywords are given
        (bookmarks have no time dimension, so keyword-less search is useless).
    """
    if not keywords:
        return []

    bookmark_file = Path(browser_data_dir) / profile.directory / "Bookmarks"
    if not bookmark_file.is_file():
        return []

    try:
        raw = bookmark_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read bookmarks for %s/%s: %s", profile.browser_name, profile.display_name, exc)
        return []

    needles = [kw.lower() for kw in keywords]
    results: list[BookmarkResult] = []
    roots = data.get("roots", {})

    for root in roots.values():
        if isinstance(root, dict):
            _walk_bookmark_tree(root, [], needles, profile, results)

    return results


def _walk_bookmark_tree(
    node: dict[str, object],
    trail: list[str],
    needles: list[str],
    profile: BrowserProfile,
    out: list[BookmarkResult],
) -> None:
    """Recursively walk bookmark tree collecting matches."""
    if not isinstance(node, dict):
        return

    node_type = node.get("type", "")
    node_name = str(node.get("name", ""))

    if node_type == "url":
        url = str(node.get("url", ""))
        haystack = f"{node_name} {url}".lower()
        if all(n in haystack for n in needles):
            out.append(
                BookmarkResult(
                    title=node_name,
                    url=url,
                    folder_path=" / ".join(trail),
                    profile=profile.display_name,
                    browser=profile.browser_name,
                )
            )

    children = node.get("children")
    if isinstance(children, list):
        sub_trail = [*trail, node_name] if node_name else trail
        for child in children:
            if isinstance(child, dict):
                _walk_bookmark_tree(child, sub_trail, needles, profile, out)
