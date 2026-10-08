"""Type definitions and data structures for GateGuard invisible Unicode sanitization.

[INPUT]
- Raw paths, denial reasons, and validation requests.

[OUTPUT]
- Structured sanitization results, category detections, and policy definitions.

[POS]
- Core data models for gate guard denial path Unicode sanitization.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InvisibleUnicodeCategory(StrEnum):
    """Categories of dangerous or invisible Unicode codepoints."""

    ASCII_CONTROL = "ascii_control"
    C1_CONTROL = "c1_control"
    BIDI_CONTROL = "bidi_control"
    LINE_SEPARATOR = "line_separator"
    ZERO_WIDTH = "zero_width"
    WORD_JOINER = "word_joiner"
    BYTE_ORDER_MARK = "byte_order_mark"
    VARIATION_SELECTOR = "variation_selector"
    TAG_BLOCK = "tag_block"
    FILLER = "filler"
    INVISIBLE_MATH = "invisible_math"
    OTHER_INVISIBLE = "other_invisible"


@dataclass(frozen=True)
class SanitizeResult:
    """Immutable result of a denial string sanitization."""

    original_text: str
    sanitized_text: str
    characters_removed_count: int
    categories_detected: tuple[InvisibleUnicodeCategory, ...]
    was_truncated: bool

    @property
    def has_modifications(self) -> bool:
        """Return True if any dangerous characters were removed or text was truncated."""
        return self.characters_removed_count > 0 or self.was_truncated


@dataclass(frozen=True)
class DenialSanitizePolicy:
    """Configuration policy for gate guard denial sanitization."""

    replacement_char: str = " "
    max_path_length: int = 500
    max_reason_length: int = 1000
    strip_surrounding_whitespace: bool = True
