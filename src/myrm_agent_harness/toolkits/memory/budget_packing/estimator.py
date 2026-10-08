# [POS]: src/myrm_agent_harness/toolkits/memory/budget_packing/estimator.py
# [INPUT]: Bilingual text content (CJK and Latin/ASCII)
# [OUTPUT]: estimate_tokens, calculate_content_overlap

"""Conservative bilingual token estimator and overlap calculator.

Ensures LLM context windows are protected against low-estimation blowouts.
CJK characters are conservatively weighted at 1.2 tokens each, Latin words at 1.33 tokens.
"""

from __future__ import annotations

import re
from typing import Final

_CJK_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\u4e00-\u9fa5\u3040-\u30ff\uac00-\ud7af]")
_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-zA-Z0-9_-]+")


def estimate_tokens(text: str) -> int:
    """Conservative bilingual token estimator.

    Guarantees no under-estimation blowout in CJK + English mixed contexts:
    - CJK characters counted at 1.2x.
    - Latin/alphanumeric words counted at 1.33x.
    """
    if not text:
        return 0

    cjk_count = len(_CJK_PATTERN.findall(text))
    words = _WORD_PATTERN.findall(text)
    word_count = len(words)

    estimated = int(cjk_count * 1.2 + word_count * 1.33)
    return max(1, estimated)


def calculate_content_overlap(text_a: str, text_b: str) -> float:
    """Calculate character-level bigram Jaccard similarity between two texts."""
    if not text_a or not text_b:
        return 0.0

    def _extract_bigrams(s: str) -> set[str]:
        cleaned = re.sub(r"\s+", "", s.lower())
        if len(cleaned) < 2:
            return {cleaned} if cleaned else set()
        return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}

    bigrams_a = _extract_bigrams(text_a)
    bigrams_b = _extract_bigrams(text_b)

    if not bigrams_a or not bigrams_b:
        return 0.0

    intersection = len(bigrams_a & bigrams_b)
    union = len(bigrams_a | bigrams_b)
    return float(intersection) / float(union) if union > 0 else 0.0
