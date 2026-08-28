"""Charset auto-detection and normalization for web content.

Provides high-performance multi-tier charset probe and decoding:
1. HTTP Content-Type Header charset
2. HTML <meta> tag charset probe (fast regex scan on raw bytes)
3. Standard / CJK charset fallbacks and charset-normalizer / chardet fallback

[INPUT]
- (none)

[OUTPUT]
- detect_and_decode_html: (body: bytes, header_encoding: str | None = None) -> tuple[str, str]

[POS]
Low-level charset decoder utility. Placed in toolkits/web_fetch for clean separation of concerns.
"""

from __future__ import annotations

import re
from typing import Final

_META_CHARSET_RE: Final = re.compile(
    rb"""<meta(?:\s+[^>]*?)?\s+charset\s*=\s*['"]?([a-zA-Z0-9_\-]+)['"]?""",
    re.IGNORECASE,
)
_META_HTTP_EQUIV_RE: Final = re.compile(
    rb"""<meta(?:\s+[^>]*?)?\s+http-equiv\s*=\s*['"]?content-type['"]?(?:\s+[^>]*?)?\s+content\s*=\s*['"][^'"]*?charset\s*=\s*([a-zA-Z0-9_\-]+)['"]?""",
    re.IGNORECASE,
)
_MAX_PROBE_BYTES: Final = 4096


def _normalize_encoding_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip().lower().replace("_", "-")
    if normalized in ("gb2312", "gb_2312", "gbk"):
        return "gb18030"
    if normalized in ("utf-8", "utf8"):
        return "utf-8"
    if normalized in ("big5", "big5-hkscs"):
        return "big5"
    if normalized in ("shift-jis", "shift_jis", "sjis"):
        return "shift_jis"
    if normalized in ("euc-jp", "euc_jp"):
        return "euc_jp"
    if normalized in ("euc-kr", "euc_kr"):
        return "euc_kr"
    if normalized in ("iso-8859-1", "latin-1", "latin1", "windows-1252", "cp1252"):
        return "iso-8859-1"
    return normalized


def probe_meta_charset(body: bytes) -> str | None:
    """Scan the first 4KB of HTML bytes for <meta> charset declaration."""
    if not body:
        return None
    head_bytes = body[:_MAX_PROBE_BYTES]
    match = _META_CHARSET_RE.search(head_bytes)
    if match:
        return _normalize_encoding_name(match.group(1).decode("ascii", errors="ignore"))
    match_equiv = _META_HTTP_EQUIV_RE.search(head_bytes)
    if match_equiv:
        return _normalize_encoding_name(match_equiv.group(1).decode("ascii", errors="ignore"))
    return None


def detect_and_decode_html(body: bytes, header_encoding: str | None = None) -> tuple[str, str]:
    """Tiered charset detection and safe decoding.

    Returns:
        tuple of (decoded_text, detected_encoding)
    """
    if not body:
        return "", "utf-8"

    normalized_header = _normalize_encoding_name(header_encoding)

    # 1. If header explicitly declared a non-utf8/non-latin1 encoding, try it first
    if normalized_header and normalized_header not in ("utf-8", "iso-8859-1"):
        try:
            return body.decode(normalized_header), normalized_header
        except (UnicodeDecodeError, LookupError):
            pass

    # 2. Meta tag scan in HTML head bytes
    meta_encoding = probe_meta_charset(body)
    if meta_encoding:
        try:
            return body.decode(meta_encoding), meta_encoding
        except (UnicodeDecodeError, LookupError):
            pass

    # 3. Try UTF-8 strict decode
    try:
        return body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    # 4. Try CJK dominant fallback (GB18030 covers GB2312/GBK/Latin/ASCII)
    try:
        return body.decode("gb18030"), "gb18030"
    except (UnicodeDecodeError, LookupError):
        pass

    # 5. Try Japanese / Korean common encodings
    for cjk_enc in ("shift_jis", "euc_jp", "euc_kr", "big5"):
        try:
            return body.decode(cjk_enc), cjk_enc
        except (UnicodeDecodeError, LookupError):
            pass

    # 6. Fallback with header encoding or utf-8 with replace
    fallback_enc = normalized_header or "utf-8"
    return body.decode(fallback_enc, errors="replace"), fallback_enc
