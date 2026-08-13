"""Evaluation decontamination helpers — keep benchmarks free of answer leakage.

[INPUT]
- none (pure functions)

[OUTPUT]
- HUGGINGFACE_DOMAINS: domain patterns for Hugging Face (hf.co / huggingface.co)
- is_huggingface_url(url): True when a URL targets a Hugging Face host
- query_targets_huggingface(query): True when a search query names Hugging Face
- normalize_answer(text): canonical text used by the exact-match judge pre-pass

[POS]
Framework-generic pollution guards for benchmark runs. External suites like
BrowseComp web research may let an agent stumble onto Hugging Face (models,
datasets, discussions) that can carry reference material for a task; blocking
those hosts and queries in ``benchmark_mode`` keeps the scored run measuring
the model instead of the leak. The business layer decides when to apply them
(only for benchmark runs, never for normal product tool use).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

# Pattern set in DomainAllowlist/DomainBlocklist form (wildcard suffix).
HUGGINGFACE_DOMAINS: tuple[str, ...] = (
    "huggingface.co",
    "*.huggingface.co",
    "hf.co",
    "*.hf.co",
)

# Substrings a search query may use to name Hugging Face resources.
_HF_QUERY_MARKERS: tuple[str, ...] = (
    "huggingface",
    "hf.co",
    "hugging face",
)

# Public alias so callers (e.g. benchmark-mode search blocklists) can install
# the exact same markers as ``query_targets_huggingface`` without duplicating
# them or reaching into the private constant.
HUGGINGFACE_QUERY_MARKERS: tuple[str, ...] = _HF_QUERY_MARKERS


def is_huggingface_url(url: str) -> bool:
    """Return True when *url* targets a Hugging Face host.

    Covers ``huggingface.co`` and its short alias ``hf.co`` including any
    subdomain (e.g. ``huggingface.co/datasets/...``).
    """
    hostname = (urlparse(url).hostname or "").lower()
    if not hostname:
        return False
    for pattern in HUGGINGFACE_DOMAINS:
        if pattern.startswith("*."):
            suffix = pattern[1:]  # ".huggingface.co"
            bare = pattern[2:]  # "huggingface.co"
            if hostname == bare or hostname.endswith(suffix):
                return True
        elif hostname == pattern:
            return True
    return False


def query_targets_huggingface(query: str) -> bool:
    """Return True when a search query names Hugging Face.

    Detects explicit resource references (``huggingface``, ``hf.co``) in the
    query text so the eval policy can reject the search before it runs.
    """
    lowered = query.lower()
    return any(marker in lowered for marker in _HF_QUERY_MARKERS)


def normalize_answer(text: str) -> str:
    """Canonicalize an answer for the exact-match judge pre-pass.

    Lowercases, collapses whitespace and strips punctuation so trivially
    equivalent spellings (case, spacing, trailing marks) short-circuit the
    LLM judge. Decimal numbers keep their magnitude semantics: ``42.5`` never
    collides with ``425`` (the point is preserved as a separator), whole-number
    forms like ``42.0`` fold to ``42``, and trailing zeros (``42.50``,
    ``3.140``) collapse. Non-empty guard is the caller's responsibility — an
    empty normalized string must never be treated as a match.
    """
    normalized = unicodedata.normalize("NFKC", text)
    # Fold trailing zeros after a decimal point (42.50 -> 42.5, 3.140 -> 3.14)
    # before the point itself is treated as punctuation.
    normalized = re.sub(r"(\d\.\d*?)0+(?=\D|$)", r"\1", normalized)
    # Fold whole-number decimals (42.0 -> 42.); the trailing point is then
    # stripped by the punctuation pass below.
    normalized = re.sub(r"(?<=\d)\.0+(?=\D|$)", "", normalized)
    # Preserve decimal-point semantics (42.5 -> "42 dot 5") so a decimal never
    # collapses into an integer of a different magnitude.
    normalized = re.sub(r"(?<=\d)\.(?=\d)", " dot ", normalized)
    normalized = re.sub(r"[^\w\s]", "", normalized, flags=re.UNICODE)
    return " ".join(normalized.lower().split())
