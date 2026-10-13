"""High-entropy token scan for credentials that carry no vendor prefix and no label.

[INPUT]
- core.security.detection.secret_value::is_reference_token (POS: shared rules telling a secret from a reference to one:
    identifiers, class names, constants, slugs, domains, query strings.)

[OUTPUT]
- scan_high_entropy(): (pattern name, token) pairs for random-looking tokens in free text
- shannon_entropy(): Shannon entropy of a string in bits per character

[POS]
Unknown-credential tier of the leak detector. Splits text into tokens (URLs, UUIDs, long hex digests and file paths
removed first) and keeps those that are long, ASCII, alphanumeric with both letters and digits, not base64/hex blobs,
not a reference to a secret and above the entropy threshold.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from myrm_agent_harness.core.security.detection.secret_value import is_reference_token

_ENTROPY_MIN_TOKEN_LEN = 24
_ENTROPY_THRESHOLD = 4.2

_URL_STRIP_RE = re.compile(r"https?://\S+")
_UUID_STRIP_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX_HASH_RE = re.compile(r"\b[0-9a-f]{40,}\b")
_FILE_PATH_RE = re.compile(r"(?:/[\w._-]+){2,}")


def shannon_entropy(s: str) -> float:
    """Compute Shannon entropy in bits per character."""
    if not s:
        return 0.0
    freq = Counter(s.encode())
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def _is_all_hex(s: str) -> bool:
    return all(c in "0123456789abcdef" for c in s.lower())


def _looks_like_base64(s: str) -> bool:
    base64_special = set("+/=")
    return any(c in base64_special for c in s) and all(
        c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in s
    )


def scan_high_entropy(content: str, already_matched: set[str]) -> list[tuple[str, str]]:
    """Detect high-entropy tokens that may be unknown credentials.

    Returns list of (pattern_name, matched_token) pairs.
    Skips tokens contained in a string of ``already_matched`` (matches of the other tiers).
    """
    stripped = _URL_STRIP_RE.sub(" ", content)
    stripped = _UUID_STRIP_RE.sub(" ", stripped)
    stripped = _HEX_HASH_RE.sub(" ", stripped)
    stripped = _FILE_PATH_RE.sub(" ", stripped)

    found: list[tuple[str, str]] = []
    tokens = re.split(r"[\s,;:\"'`()\[\]{}|<>#]+", stripped)

    for token in tokens:
        if len(token) < _ENTROPY_MIN_TOKEN_LEN:
            continue
        if not token.isascii():
            continue
        if _is_all_hex(token):
            continue
        if _looks_like_base64(token):
            continue
        has_alpha = any(c.isalpha() for c in token)
        has_digit = any(c.isdigit() for c in token)
        if not (has_alpha and has_digit):
            continue
        if is_reference_token(token, min_length=_ENTROPY_MIN_TOKEN_LEN):
            continue
        if any(token in matched for matched in already_matched):
            continue
        entropy = shannon_entropy(token)
        if entropy >= _ENTROPY_THRESHOLD:
            found.append(("high_entropy_token", token))

    return found
