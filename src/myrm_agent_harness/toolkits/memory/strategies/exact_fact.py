"""Exact fact classification and identifier extraction strategy.

Provides zero-LLM deterministic classification of high-entropy exact facts
(UUIDs, Git SHAs, SemVer tags, network endpoints, system configuration keys)
to support physical dual-track governance and prevent lossy memory compression.

[INPUT]
- str: raw text content or query string
- dict[str, str | int | float | bool] | None: optional memory metadata

[OUTPUT]
- extract_exact_identifiers: extract unique high-entropy tokens and identifiers
- is_exact_fact_text: determine if text constitutes an exact fact
- classify_memory_exactness: tuple of (is_exact_fact, extracted_identifiers)

[POS]
Harness-level deterministic classifier in memory/strategies. Decoupled from LLM
runtime and business layers. Fully compatible with SQLite FTS5 inverted indexing.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

# Pre-compiled high-precision regex patterns for exact identifiers
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_GIT_SHA_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{40}\b|\b[0-9a-fA-F]{7,12}\b"
)
_SEMVER_PATTERN = re.compile(
    r"\bv?(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9a-zA-Z.-]+)?(?:\+[0-9a-zA-Z.-]+)?\b"
)
_NETWORK_ENDPOINT_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?::[1-9][0-9]{0,4})\b"
    r"|\b(?:localhost|0\.0\.0\.0):[1-9][0-9]{0,4}\b"
)
_CONFIG_KEY_PATTERN = re.compile(
    r"\b[A-Z][A-Z0-9_]{3,}[A-Z0-9]\b"
)
_PORT_DECLARATION_PATTERN = re.compile(
    r"\b(?:port|PORT|端口)[:\s=]+([1-9][0-9]{1,4})\b"
)

# Common words matching hex/config patterns that are pure false-positives
_CONFIG_DENYLIST = frozenset({
    "THE", "AND", "FOR", "NOT", "WITH", "THIS", "THAT", "FROM", "HAVE", "USER",
    "TRUE", "FALSE", "NONE", "NULL", "INFO", "WARN", "DEBUG", "ERROR", "FATAL",
    "HTTP", "HTTPS", "JSON", "YAML", "HTML", "REST", "GRPC", "TODO", "NOTE",
})

# Words that look like short hex SHAs but are common English words
_HEX_DENYLIST = frozenset({
    "decade", "defaced", "accord", "afford", "beefed", "coffee", "facade",
    "added", "dead", "beef", "fade", "face", "deed", "feed", "cede", "cafe",
})


def compute_shannon_entropy(token: str) -> float:
    """Compute Shannon entropy for a given token string.

    Higher entropy indicates random/hashed identifiers (e.g. UUIDs, random keys).
    """
    if not token:
        return 0.0
    length = len(token)
    char_counts: dict[str, int] = {}
    for char in token:
        char_counts[char] = char_counts.get(char, 0) + 1
    entropy = 0.0
    for count in char_counts.values():
        prob = count / length
        entropy -= prob * math.log2(prob)
    return entropy


class ExactFactClassifier:
    """Zero-LLM deterministic classifier for exact facts and high-entropy identifiers."""

    @staticmethod
    def extract_identifiers(text: str) -> list[str]:
        """Extract deduplicated high-entropy tokens and identifiers from text.

        Preserves original casing while preventing duplicate matches.
        """
        if not text or not text.strip():
            return []

        identifiers: list[str] = []
        seen: set[str] = set()

        def _add(match_val: str) -> None:
            cleaned = match_val.strip()
            lower = cleaned.lower()
            if lower not in seen:
                seen.add(lower)
                identifiers.append(cleaned)

        # 1. UUID extraction (RFC 4122)
        for m in _UUID_PATTERN.finditer(text):
            _add(m.group(0))

        # 2. Network endpoint extraction
        for m in _NETWORK_ENDPOINT_PATTERN.finditer(text):
            _add(m.group(0))

        # 3. Port declaration extraction
        for m in _PORT_DECLARATION_PATTERN.finditer(text):
            _add(m.group(1))

        # 4. SemVer version extraction
        for m in _SEMVER_PATTERN.finditer(text):
            val = m.group(0)
            # Filter trivial single digits like '1.0' that aren't semver
            if val.count(".") >= 2:
                _add(val)

        # 5. Config keys (ALL_CAPS identifiers)
        for m in _CONFIG_KEY_PATTERN.finditer(text):
            val = m.group(0)
            if val not in _CONFIG_DENYLIST and "_" in val:
                _add(val)

        # 6. Git commit SHA extraction (full 40 or short 7~12)
        for m in _GIT_SHA_PATTERN.finditer(text):
            val = m.group(0)
            lower = val.lower()
            if lower in _HEX_DENYLIST:
                continue
            # For short hashes (7-12), enforce that it has both letters and numbers
            if len(val) < 16:
                has_digit = any(c.isdigit() for c in val)
                has_alpha = any(c.isalpha() for c in val)
                if has_digit and has_alpha:
                    _add(val)
            else:
                _add(val)

        return identifiers

    @classmethod
    def is_exact_fact(
        cls,
        text: str,
        metadata: Mapping[str, str | int | float | bool] | None = None,
    ) -> bool:
        """Determine if a memory or input text constitutes an exact fact.

        Returns True if:
        1. Explicitly marked via metadata (e.g. metadata['is_exact_fact'] is True)
        2. Text contains at least one validated high-entropy identifier (UUID, SHA, SemVer, config key)
        """
        if metadata:
            explicit_flag = metadata.get("is_exact_fact")
            if isinstance(explicit_flag, bool):
                return explicit_flag

        identifiers = cls.extract_identifiers(text)
        return len(identifiers) > 0

    @classmethod
    def classify(
        cls,
        text: str,
        metadata: Mapping[str, str | int | float | bool] | None = None,
    ) -> tuple[bool, list[str]]:
        """Classify text and return both the boolean verdict and extracted identifiers."""
        identifiers = cls.extract_identifiers(text)
        if metadata and metadata.get("is_exact_fact") is True:
            return True, identifiers
        return len(identifiers) > 0, identifiers
