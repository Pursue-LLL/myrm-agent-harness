"""Shared GFM markdown normalization for multi-format parser output."""

from __future__ import annotations

import re

_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)


def normalize_to_gfm_markdown(text: str) -> str:
    """Normalize parser text into consistent GFM-friendly markdown."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _TRAILING_SPACES.sub("", cleaned)
    cleaned = _MULTI_BLANK.sub("\n\n", cleaned)
    return cleaned.strip()
