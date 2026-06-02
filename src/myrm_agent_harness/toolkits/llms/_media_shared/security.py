"""Media-specific security utilities — URL validation and filename sanitization.

[INPUT]

[OUTPUT]
- validate_media_url(): combines scheme/hostname check + DNS resolution
- sanitize_filename(): cleans filenames to safe, portable forms

[POS]
Delegates SSRF logic to agent.security.guards.ssrf_guard (single source of truth).
Adds media-specific concerns: max-length filenames, path traversal prevention,
extension allowlisting.
"""

from __future__ import annotations

import os
import re
import unicodedata

from myrm_agent_harness.core.security.guards.ssrf_guard import (
    SSRFVerdict,
    check_url,
    resolve_and_check,
)

_MAX_FILENAME_LEN = 200

_SAFE_CHAR_RE = re.compile(r"[^\w\s.\-]", re.UNICODE)
_MULTI_DOT_RE = re.compile(r"\.{2,}")
_MULTI_SPACE_RE = re.compile(r"\s+")

_MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".webm",
        ".mov",
        ".avi",
        ".mkv",
        ".flv",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".aac",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".tiff",
    }
)


def validate_media_url(
    url: str,
    *,
    allowed_internal_hosts: frozenset[str] = frozenset(),
    dns_resolve: bool = True,
) -> SSRFVerdict:
    """Validate a media download URL for SSRF safety.

    Phase 1: scheme + literal IP check (fast, no I/O).
    Phase 2 (if dns_resolve=True): DNS resolution + resolved-IP check.
    """
    verdict = check_url(url, allowed_internal_hosts=allowed_internal_hosts)
    if not verdict.allowed:
        return verdict

    if not dns_resolve:
        return verdict

    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return SSRFVerdict(allowed=False, reason="URL has no hostname")

    return resolve_and_check(hostname, allowed_internal_hosts=allowed_internal_hosts)


def sanitize_filename(
    name: str,
    *,
    default: str = "media",
    max_length: int = _MAX_FILENAME_LEN,
) -> str:
    """Sanitize a filename for safe filesystem storage.

    - Strips path components (prevents traversal)
    - Normalizes Unicode (NFC)
    - Removes unsafe characters
    - Truncates to max_length
    - Preserves extension if it's a known media type
    """
    name = os.path.basename(name)

    name = unicodedata.normalize("NFC", name)

    root, ext = os.path.splitext(name)
    ext = ext.lower()

    root = _SAFE_CHAR_RE.sub("", root)
    root = _MULTI_DOT_RE.sub(".", root)
    root = _MULTI_SPACE_RE.sub("_", root).strip(" ._-")

    if ext not in _MEDIA_EXTENSIONS:
        ext = ""

    if not root:
        root = default

    budget = max_length - len(ext)
    if budget < 1:
        budget = 1
    root = root[:budget]
    root = root.rstrip(" ._-")
    if not root:
        root = default

    return root + ext
