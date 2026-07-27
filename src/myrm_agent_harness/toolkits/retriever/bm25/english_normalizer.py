"""Zero-dependency English token normalization for BM25 retrieval.

Provides stopword filtering and conservative suffix normalization without runtime
corpus downloads (airgap/sandbox safe).

[INPUT]
- Raw English tokens from TokenizerService

[OUTPUT]
- normalize_english_token: Normalize a single token (None if stopword)
- normalize_english_tokens: Batch normalize token list

[POS]
Opt-in English enhancement backend for BM25 sparse retrieval (-ies/-ing/-ed + stopwords).
Call sites enable via `enable_english_enhancement`; skill search keeps the default off.
"""

from __future__ import annotations

# Common English stopwords (Lucene-style minimal set; no runtime download).
_ENGLISH_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "him",
        "his",
        "how",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "might",
        "must",
        "of",
        "on",
        "or",
        "over",
        "shall",
        "she",
        "should",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


def _strip_doubled_consonant(stem: str) -> str:
    if len(stem) > 2 and stem[-1] == stem[-2]:
        return stem[:-1]
    return stem


def _apply_suffix_rules(word: str) -> str:
    """Apply -ies/-ing/-ed suffix rules only (no bare plural -s stripping)."""
    if len(word) <= 3:
        return word

    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"

    if word.endswith("ing") and len(word) > 5:
        return _strip_doubled_consonant(word[:-3])

    if word.endswith("ed") and len(word) > 4:
        return _strip_doubled_consonant(word[:-2])

    return word


def normalize_english_token(token: str) -> str | None:
    """Normalize one English token; return None if it is a stopword."""
    normalized = token.lower().strip()
    if not normalized:
        return None
    if normalized in _ENGLISH_STOPWORDS:
        return None
    return _apply_suffix_rules(normalized)


def normalize_english_tokens(tokens: list[str]) -> list[str]:
    """Filter stopwords and normalize English tokens in order."""
    result: list[str] = []
    for token in tokens:
        normalized = normalize_english_token(token)
        if normalized is not None:
            result.append(normalized)
    return result
