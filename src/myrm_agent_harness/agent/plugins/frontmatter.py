"""Markdown frontmatter split shared by skill and agent profile files.

[INPUT]
-- (none)

[OUTPUT]
-- split_frontmatter: ``---`` delimited YAML header + body → (metadata, description, body).

[POS]
Tiny pure helper for the plugin parser; the writer renders the inverse form itself.
"""

from __future__ import annotations

import logging
import re

import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict[str, object], str, str]:
    """Split ``---`` delimited YAML frontmatter from the body.

    Returns ``(metadata, description, pure_content)``. A missing or unparsable
    header yields empty metadata and the whole text as content.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, "", text.strip()

    pure_content = text[match.end() :].strip()
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except Exception as exc:  # untrusted input: any loader failure degrades to plain content
        logger.warning("Failed to parse frontmatter: %s", exc)
        return {}, "", text.strip()

    if not isinstance(frontmatter, dict):
        return {}, "", pure_content
    raw_description = frontmatter.get("description")
    return frontmatter, raw_description if isinstance(raw_description, str) else "", pure_content
