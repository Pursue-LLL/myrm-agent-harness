"""Deterministic fingerprinting for wiki raw corpus files.

[POS]
See module docstring.
"""

from __future__ import annotations

import hashlib
import re
from html import unescape
from pathlib import Path

from myrm_agent_harness.toolkits.memory._internal.hash_utils import (
    NormalizationLevel,
    compute_normalized_hash,
)
from myrm_agent_harness.toolkits.wiki.core.claims_contract import sha256_raw_file
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.types import (
    RawFileFingerprint,
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_FENCE_RE = re.compile(r"^---[\s\S]*?---\n", re.MULTILINE)
_SIMHASH_BITS = 64
_NEAR_DUP_HAMMING_THRESHOLD = 3


def extract_body_text(content: str) -> str:
    """Extract comparable body text from markdown or HTML."""
    text = _FENCE_RE.sub("", content)
    if "<" in text and ">" in text:
        text = unescape(_HTML_TAG_RE.sub(" ", text))
    return text


def compute_exact_hash(raw_file: Path) -> str:
    """Return full SHA256 hex for raw file bytes."""
    return sha256_raw_file(raw_file)


def compute_normalized_body_hash(content: str) -> str:
    """Return normalized hash for cross-format duplicate detection."""
    body = extract_body_text(content)
    return compute_normalized_hash(body, NormalizationLevel.FULL)


def _tokenize_for_simhash(content: str) -> list[str]:
    body = extract_body_text(content).lower()
    body = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", body)
    tokens = [token for token in body.split() if token]
    if not tokens:
        return []
    if len(tokens) == 1:
        return tokens
    bigrams: list[str] = []
    for index in range(len(tokens) - 1):
        bigrams.append(f"{tokens[index]} {tokens[index + 1]}")
    return bigrams


def compute_simhash(content: str) -> int:
    """Return 64-bit simhash for near-duplicate detection."""
    shingles = _tokenize_for_simhash(content)
    if not shingles:
        return 0
    vector = [0] * _SIMHASH_BITS
    for shingle in shingles:
        digest = hashlib.sha256(shingle.encode("utf-8")).digest()
        hash_int = int.from_bytes(digest[:8], byteorder="big", signed=False)
        for bit in range(_SIMHASH_BITS):
            vector[bit] += 1 if (hash_int >> bit) & 1 else -1
    result = 0
    for bit, weight in enumerate(vector):
        if weight >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left: int, right: int) -> int:
    """Count differing bits between two simhashes."""
    return (left ^ right).bit_count()


def is_near_duplicate(left: int, right: int) -> bool:
    """Return True when simhashes are similar enough to group."""
    if left == 0 or right == 0:
        return False
    return hamming_distance(left, right) <= _NEAR_DUP_HAMMING_THRESHOLD


def build_fingerprint(raw_file: Path, *, relative_path: str) -> RawFileFingerprint:
    """Collect all fingerprint tiers for one raw file."""
    content = raw_file.read_text(encoding="utf-8")
    stat = raw_file.stat()
    return RawFileFingerprint(
        relative_path=relative_path.replace("\\", "/"),
        exact_hash=compute_exact_hash(raw_file),
        normalized_hash=compute_normalized_body_hash(content),
        simhash=compute_simhash(content),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def recommend_keep_path(members: list[RawFileFingerprint]) -> str:
    """Pick the path most likely to be the canonical copy."""
    if not members:
        return ""

    def sort_key(item: RawFileFingerprint) -> tuple[int, int, str]:
        depth = item.relative_path.count("/")
        return (depth, -item.mtime_ns, item.relative_path)

    return sorted(members, key=sort_key)[0].relative_path
