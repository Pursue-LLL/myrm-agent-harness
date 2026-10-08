"""Unicode safety policy rules and detection for GateGuard denial paths.

[INPUT]
- Raw string containing potential invisible or dangerous Unicode codepoints.

[OUTPUT]
- Classification of codepoints and categorization of dangerous elements.

[POS]
- Policy constants and classification logic mirroring ECC #3103 and CI Unicode safety.
"""

from __future__ import annotations

import re
from typing import Final

from .types import InvisibleUnicodeCategory

# ---------------------------------------------------------------------------
# Unicode Codepoints and Ranges (Aligned with ECC #3103 & CI policy)
# ---------------------------------------------------------------------------

ASCII_CONTROL_MAX: Final[int] = 0x1F
ASCII_DELETE: Final[int] = 0x7F
C1_CONTROLS_RANGE: Final[tuple[int, int]] = (0x80, 0x9F)

BIDI_MARKS_RANGE: Final[tuple[int, int]] = (0x200E, 0x200F)
BIDI_EMBEDDINGS_RANGE: Final[tuple[int, int]] = (0x202A, 0x202E)
BIDI_ISOLATES_RANGE: Final[tuple[int, int]] = (0x2066, 0x2069)

LINE_SEPARATOR: Final[int] = 0x2028
PARAGRAPH_SEPARATOR: Final[int] = 0x2029

ZERO_WIDTHS_RANGE: Final[tuple[int, int]] = (0x200B, 0x200D)
WORD_JOINER: Final[int] = 0x2060
BYTE_ORDER_MARK: Final[int] = 0xFEFF

VARIATION_SELECTORS_RANGE: Final[tuple[int, int]] = (0xFE00, 0xFE0F)
VARIATION_SUPPLEMENTS_RANGE: Final[tuple[int, int]] = (0xE0100, 0xE01EF)

TAG_BLOCK_RANGE: Final[tuple[int, int]] = (0xE0000, 0xE007F)

MONGOLIAN_VOWEL_SEPARATOR: Final[int] = 0x180E
HANGUL_CHOSEONG_FILLER: Final[int] = 0x115F
HANGUL_JUNGSEONG_FILLER: Final[int] = 0x1160
HANGUL_FILLER: Final[int] = 0x3164

INVISIBLE_MATH_RANGE: Final[tuple[int, int]] = (0x2061, 0x2064)

OTHER_INVISIBLES: Final[frozenset[int]] = frozenset({0x00AD, 0x034F, 0x061C})


def in_range(code: int, bounds: tuple[int, int]) -> bool:
    """Check if code point falls within inclusive bounds."""
    return bounds[0] <= code <= bounds[1]


def classify_codepoint(code: int) -> InvisibleUnicodeCategory | None:
    """Classify a Unicode code point into a dangerous category, or None if safe."""
    if code <= ASCII_CONTROL_MAX or code == ASCII_DELETE:
        return InvisibleUnicodeCategory.ASCII_CONTROL
    if in_range(code, C1_CONTROLS_RANGE):
        return InvisibleUnicodeCategory.C1_CONTROL
    if in_range(code, BIDI_MARKS_RANGE) or in_range(code, BIDI_EMBEDDINGS_RANGE) or in_range(code, BIDI_ISOLATES_RANGE):
        return InvisibleUnicodeCategory.BIDI_CONTROL
    if code in (LINE_SEPARATOR, PARAGRAPH_SEPARATOR):
        return InvisibleUnicodeCategory.LINE_SEPARATOR
    if in_range(code, ZERO_WIDTHS_RANGE):
        return InvisibleUnicodeCategory.ZERO_WIDTH
    if code == WORD_JOINER:
        return InvisibleUnicodeCategory.WORD_JOINER
    if code == BYTE_ORDER_MARK:
        return InvisibleUnicodeCategory.BYTE_ORDER_MARK
    if in_range(code, VARIATION_SELECTORS_RANGE) or in_range(code, VARIATION_SUPPLEMENTS_RANGE):
        return InvisibleUnicodeCategory.VARIATION_SELECTOR
    if in_range(code, TAG_BLOCK_RANGE):
        return InvisibleUnicodeCategory.TAG_BLOCK
    if code in (
        MONGOLIAN_VOWEL_SEPARATOR,
        HANGUL_CHOSEONG_FILLER,
        HANGUL_JUNGSEONG_FILLER,
        HANGUL_FILLER,
    ):
        return InvisibleUnicodeCategory.FILLER
    if in_range(code, INVISIBLE_MATH_RANGE):
        return InvisibleUnicodeCategory.INVISIBLE_MATH
    if code in OTHER_INVISIBLES:
        return InvisibleUnicodeCategory.OTHER_INVISIBLE
    return None


# Precompiled regex targeting all dangerous codepoints for high-performance cleaning
_DANGEROUS_RE_PATTERN: Final[str] = (
    r"[\x00-\x1f\x7f\x80-\x9f"
    r"\u00ad\u034f\u061c\u115f\u1160\u180e\u3164"
    r"\u200b-\u200f\u2028\u2029\u202a-\u202e\u2060-\u2064\u2066-\u2069"
    r"\ufe00-\ufe0f\ufeff"
    r"\U000e0000-\U000e007f\U000e0100-\U000e01ef]"
)
DANGEROUS_DENIAL_UNICODE_RE: Final[re.Pattern[str]] = re.compile(_DANGEROUS_RE_PATTERN)


def detect_categories(text: str) -> tuple[InvisibleUnicodeCategory, ...]:
    """Detect all unique dangerous Unicode categories present in text."""
    if not text:
        return ()
    found: set[InvisibleUnicodeCategory] = set()
    for char in text:
        cat = classify_codepoint(ord(char))
        if cat is not None:
            found.add(cat)
    # Sort deterministically based on enum values
    return tuple(sorted(found, key=lambda c: c.value))
