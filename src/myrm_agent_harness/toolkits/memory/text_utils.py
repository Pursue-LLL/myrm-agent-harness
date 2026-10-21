r"""Unified text tokenization utilities for memory retrieval.

Provides consistent tokenization across different memory components
(adaptive query analysis, keyword overlap scoring, etc.).

Supports:
- English word segmentation (whitespace + punctuation)
- CJK character segmentation (per-character for Chinese/Japanese/Korean)
- Lowercase normalization for case-insensitive matching
- Efficient single-pass processing

[INPUT]
- re (POS: Standard library regex with UNICODE support)
- unicodedata (POS: Unicode character database)

[OUTPUT]
- tokenize_query(): Tokenize preserving order (for adaptive analysis)
- tokenize(): Tokenize as unique set (for overlap scoring)
- is_cjk_char(): Check if character is CJK
- get_token_count(): Fast token counting
- get_diversity_ratio(): Word diversity ratio calculation

[POS]
Unified multi-language tokenization for memory retrieval. Uses re.UNICODE
\w+ pattern for both English and CJK languages. Consecutive CJK characters
are treated as single tokens (e.g., "performanceoptimize" → 1 token). Supports adaptive
dual-channel selection, keyword overlap scoring, and diversity analysis.
"""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"\w+", re.UNICODE)


def tokenize_query(text: str) -> list[str]:
    """Tokenize Query text preserving token order.

    Used by adaptive channel selection where token count and order matter.

    Args:
        text: Query string to tokenize.

    Returns:
        List of lowercase tokens (preserving order).

    Examples:
        >>> tokenize_query("Python performance")
        ['python', 'performance']
        >>> tokenize_query("hello,world")
        ['hello', 'world']
        >>> tokenize_query("Pythonperformanceoptimize")
        ['python', '', 'can', '', '']
    """
    if not text:
        return []

    normalized = text.lower()
    tokens = _WORD_PATTERN.findall(normalized)
    return tokens


def tokenize(text: str) -> frozenset[str]:
    """Tokenize text into unique lowercase tokens.

    Used by keyword overlap scoring and retrieval where only token
    presence (not order or frequency) matters.

    Args:
        text: Text to tokenize.

    Returns:
        Frozen set of unique lowercase tokens.

    Examples:
        >>> tokenize("Python Python bug")
        frozenset({'python', 'bug'})
        >>> tokenize("Hello, World!")
        frozenset({'hello', 'world'})
    """
    if not text:
        return frozenset()

    normalized = text.lower()
    tokens = _WORD_PATTERN.findall(normalized)
    return frozenset(tokens)


def is_cjk_char(char: str) -> bool:
    """Check if a character is CJK (Chinese/Japanese/Korean).

    Args:
        char: Single character to check.

    Returns:
        True if character is in CJK Unicode range.
    """
    if not char:
        return False

    code_point = ord(char)
    return any(
        [
            0x4E00 <= code_point <= 0x9FFF,  # CJK Unified Ideographs
            0x3400 <= code_point <= 0x4DBF,  # CJK Extension A
            0x20000 <= code_point <= 0x2A6DF,  # CJK Extension B
            0x2A700 <= code_point <= 0x2B73F,  # CJK Extension C
            0x2B740 <= code_point <= 0x2B81F,  # CJK Extension D
            0x3040 <= code_point <= 0x309F,  # Hiragana
            0x30A0 <= code_point <= 0x30FF,  # Katakana
            0xAC00 <= code_point <= 0xD7AF,  # Hangul Syllables
        ]
    )


def get_token_count(text: str) -> int:
    """Get token count for adaptive channel selection.

    Fast shortcut for len(tokenize_query(text)).

    Args:
        text: Text to count tokens in.

    Returns:
        Number of tokens.
    """
    if not text:
        return 0

    return len(_WORD_PATTERN.findall(text.lower()))


def get_diversity_ratio(text: str) -> float:
    """Calculate word diversity ratio (unique_words / total_words).

    Used by adaptive channel selection to detect semantic complexity.

    Args:
        text: Text to analyze.

    Returns:
        Diversity ratio in [0, 1], or 0.0 if text is empty.

    Examples:
        >>> get_diversity_ratio("Python Python bug")
        0.6666666666666666  # 2 unique / 3 total
        >>> get_diversity_ratio("hello world")
        1.0  # 2 unique / 2 total
    """
    tokens = tokenize_query(text)
    if not tokens:
        return 0.0

    unique_count = len(set(tokens))
    return unique_count / len(tokens)
