"""Shared GFM markdown normalization for multi-format parser output.

[INPUT]
- text: 原始解析文本（可能含 CRLF、多余空行、行尾空格）

[OUTPUT]
- normalize_to_gfm_markdown(): 归一化文本 → GFM 友好 Markdown

[POS]
Format-agnostic text normalization shared by all parsers, guaranteeing consistent
GFM markdown output regardless of the source format.
"""

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
