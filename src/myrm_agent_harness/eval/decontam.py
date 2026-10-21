"""Evaluation decontamination helpers — keep benchmarks free of answer leakage.

[INPUT]
- none (pure functions)

[OUTPUT]
- HUGGINGFACE_DOMAINS: domain patterns for Hugging Face (hf.co / huggingface.co)
- HUGGINGFACE_QUERY_MARKERS: substrings a search query may use to name HF
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

# Pattern set in DomainAllowlist/DomainBlocklist form (wildcard suffix).
HUGGINGFACE_DOMAINS: tuple[str, ...] = (
    "huggingface.co",
    "*.huggingface.co",
    "hf.co",
    "*.hf.co",
)

# Substrings a search query may use to name Hugging Face resources.
# Consumed by the business layer to build benchmark-mode search blocklists.
HUGGINGFACE_QUERY_MARKERS: tuple[str, ...] = (
    "huggingface",
    "hf.co",
    "hugging face",
)


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
