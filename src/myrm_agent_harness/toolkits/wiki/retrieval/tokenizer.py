"""FTS5 query tokenizer with CJK bigram support.

[INPUT]
re (POS: standard library regex)

[OUTPUT]
tokenize_for_fts(): Build FTS5 query with CJK bigram support
STOP_WORDS: English + Chinese stop words for FTS filtering

[POS]
Tokenization utilities for FTS5 full-text search, including CJK (Chinese/Japanese/Korean)
bigram splitting and multi-language stop word filtering.
"""

from __future__ import annotations

import re

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
        "what",
        "how",
        "why",
        "who",
        "where",
        "when",
        "does",
        "do",
        "did",
        "can",
        "could",
        "should",
        "would",
        "的",
        "了",
        "和",
        "是",
        "就",
        "都",
        "而",
        "及",
        "与",
        "着",
        "或",
        "一个",
        "没有",
        "我们",
        "你们",
        "他们",
        "它",
        "它们",
        "什么",
        "怎么",
        "如何",
        "为什么",
        "谁",
        "在哪",
        "何时",
    }
)

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uF900-\uFAFF]+")


def tokenize_for_fts(query: str) -> str:
    """Build FTS5 query with CJK bigram support for proper Chinese/Japanese/Korean search."""
    tokens: list[str] = []

    cjk_segments = CJK_RE.findall(query)
    for seg in cjk_segments:
        if len(seg) == 1:
            tokens.append(f'"{seg}"')
        else:
            for i in range(len(seg) - 1):
                tokens.append(f'"{seg[i]}{seg[i + 1]}"')

    latin_text = CJK_RE.sub(" ", query)
    for word in latin_text.split():
        if word.lower() not in STOP_WORDS and word.strip():
            tokens.append(f'"{word}"')

    return " ".join(tokens)
