"""Deterministic CJK Bigram + Unigram Tokenizer with Two-Tier Recall Fallback.

Pure Python, zero-external-C-dependency tokenization engine designed for SQLite FTS5,
BM25, and hybrid recall.

[INPUT]
- str: raw input text or search query

[OUTPUT]
- tokenize_cjk_bigram: Single-pass, position-preserving CJK (unigram + adjacent bigram) and ASCII word tokenizer
- build_cjk_index_segment: Deduplicated space-separated tokens for FTS index columns
- build_cjk_query_tokens: Query-side tokens (order-preserved, deduplicated)
- build_cjk_query_token_tiers: Two-tier query plan: [strict, relaxed] where relaxed drops CJK bigrams to allow out-of-order recall

[POS]
Harness-level retrieval foundation under toolkits/retriever/cjk_tokenizer.py.
Eliminates SQLite unicode61 CJK blindness and trigram 2-char keyword search failure.
"""

from __future__ import annotations

import re

# CJK Unified Ideographs, Extension A, Compatibility, Kana, Hangul
_CJK_CHAR_PATTERN = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)

# ASCII word characters including alphanumeric, underscore, plus, hash, dot, hyphen
# Preserves identifiers such as 'k8s-prod', 'v1.2.0', 'gpt-4o'
_ASCII_WORD_CHAR_PATTERN = re.compile(r"[A-Za-z0-9_+#.-]")


def is_cjk_char(char: str) -> bool:
    """Return True if character is a CJK ideograph, kana, or hangul."""
    return bool(_CJK_CHAR_PATTERN.match(char))


def tokenize_cjk_bigram(text: str) -> list[str]:
    """Single-pass, position-preserving CJK unigram+bigram and ASCII word tokenizer.

    Tokens are emitted in strict appearance order to preserve spatial proximity
    for subsequent FTS5 NEAR/phrase queries.

    Rules:
    1. CJK runs: each character is emitted as a unigram, and adjacent character pairs
       within the run are emitted as bigrams. Cross-punctuation bigrams are strictly
       prevented to avoid false positives.
    2. ASCII words: words are extracted as intact tokens (lowercased for case-insensitivity)
       without bigramming, preserving naturally bounded technical identifiers.
    3. Punctuation and whitespace act as run boundaries for both CJK and ASCII.
    """
    if not text:
        return []

    tokens: list[str] = []
    cjk_run: list[str] = []
    ascii_word: list[str] = []

    def _flush_cjk() -> None:
        nonlocal cjk_run
        if not cjk_run:
            return
        run_len = len(cjk_run)
        for i in range(run_len):
            tokens.append(cjk_run[i])
            if i + 1 < run_len:
                tokens.append(cjk_run[i] + cjk_run[i + 1])
        cjk_run = []

    def _flush_ascii() -> None:
        nonlocal ascii_word
        if not ascii_word:
            return
        word = "".join(ascii_word).lower().strip(".-")
        if word:
            tokens.append(word)
        ascii_word = []

    for char in text:
        if is_cjk_char(char):
            _flush_ascii()
            cjk_run.append(char)
        elif _ASCII_WORD_CHAR_PATTERN.match(char):
            _flush_cjk()
            ascii_word.append(char)
        else:
            _flush_ascii()
            _flush_cjk()

    _flush_ascii()
    _flush_cjk()

    return tokens


def build_cjk_index_segment(text: str) -> str:
    """Write side: Convert text into deduplicated space-separated tokens for FTS index columns."""
    tokens = tokenize_cjk_bigram(text)
    seen: set[str] = set()
    unique_tokens: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)
    return " ".join(unique_tokens)


def build_cjk_query_tokens(query: str) -> list[str]:
    """Query side: Extract deduplicated tokens in appearance order."""
    tokens = tokenize_cjk_bigram(query)
    seen: set[str] = set()
    unique_tokens: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)
    return unique_tokens


def build_cjk_query_token_tiers(query: str) -> list[list[str]]:
    """Build two-tier query tokens: [strict, relaxed].

    - Strict tier: contains all tokens (unigrams + bigrams + ASCII words).
    - Relaxed tier: drops 2-character CJK bigrams, keeping only unigrams and ASCII words.
      This allows matching out-of-order keywords without false negative misses
      caused by missing cross-boundary bigrams in the index.
    - If relaxed tier is identical to strict tier, only [strict] is returned to avoid
      duplicate queries.
    """
    strict = build_cjk_query_tokens(query)
    if not strict:
        return []

    relaxed = [
        t
        for t in strict
        if not (len(t) == 2 and is_cjk_char(t[0]) and is_cjk_char(t[1]))
    ]

    if not relaxed or relaxed == strict:
        return [strict]
    return [strict, relaxed]
