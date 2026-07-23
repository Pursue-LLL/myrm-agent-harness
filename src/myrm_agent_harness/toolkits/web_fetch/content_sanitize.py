"""Sanitize web-extracted markdown before model delivery.

Strips inline base64 image blobs that waste context tokens without adding
readable content for text models.

[POS]
web_fetch toolkit preprocessing (delivery only, not Turn1 schema).
"""

from __future__ import annotations

import re

_MD_BASE64_IMAGE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)"
)
_PAREN_BASE64 = re.compile(r"\(\s*data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)")
_BARE_BASE64 = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


def strip_base64_images_from_markdown(text: str) -> str:
    """Replace inline base64 images with compact placeholders."""

    def _md_repl(match: re.Match[str]) -> str:
        alt = (match.group("alt") or "").strip()
        return f"[IMAGE: {alt}]" if alt else "[IMAGE]"

    out = _MD_BASE64_IMAGE.sub(_md_repl, text)
    out = _PAREN_BASE64.sub("[IMAGE]", out)
    out = _BARE_BASE64.sub("[IMAGE]", out)
    return out
