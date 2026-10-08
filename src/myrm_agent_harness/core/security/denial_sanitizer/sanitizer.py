"""Core sanitization engine for gate guard denial and rejection paths.

[INPUT]
- Denial messages or dictionary payloads containing potentially malicious text.

[OUTPUT]
- DenialSanitizeResult with stripped text, codepoint metrics, and spoof risk rating.

[POS]
- Harness core security module preventing invisible Unicode bypass and UI spoofing.
"""

from __future__ import annotations

import re
from typing import Final

from .types import DenialSanitizeResult, SpoofRiskLevel

# Bidi control characters capable of reversing visual text order (UI deception)
_BIDI_CONTROL_CODEPOINTS: Final[frozenset[int]] = frozenset(
    {
        0x202A,  # Left-to-Right Embedding (LRE)
        0x202B,  # Right-to-Left Embedding (RLE)
        0x202C,  # Pop Directional Formatting (PDF)
        0x202D,  # Left-to-Right Override (LRO)
        0x202E,  # Right-to-Left Override (RLO)
        0x2066,  # Left-to-Right Isolate (LRI)
        0x2067,  # Right-to-Left Isolate (RLI)
        0x2068,  # First Strong Isolate (FSI)
        0x2069,  # Pop Directional Isolate (PDI)
    }
)

# Invisible / Zero-width codepoints used for steganography or signature bypass
_INVISIBLE_CODEPOINTS: Final[frozenset[int]] = frozenset(
    {
        0x200B,  # zero width space
        0x200C,  # zero width non-joiner
        0x200D,  # zero width joiner
        0xFEFF,  # byte order mark / zero width no-break space
        0x2060,  # word joiner
        0x2061,  # function application (invisible math)
        0x2062,  # invisible times
        0x2063,  # invisible separator
        0x2064,  # invisible plus
        0x00AD,  # soft hyphen
        0x034F,  # combining grapheme joiner
        0x061C,  # Arabic letter mark
        0x180E,  # Mongolian vowel separator
    }
)

_ALL_DANGEROUS_CODEPOINTS: Final[frozenset[int]] = (
    _BIDI_CONTROL_CODEPOINTS | _INVISIBLE_CODEPOINTS
)

_DANGEROUS_CHARS_PATTERN: Final[re.Pattern[str]] = re.compile(
    "[" + "".join(f"\\u{cp:04X}" for cp in sorted(_ALL_DANGEROUS_CODEPOINTS)) + "]"
)


def sanitize_denial_message(text: str) -> DenialSanitizeResult:
    """Sanitize denial reason or message by stripping invisible and bidi characters.

    Args:
        text: Raw denial text string from gate guard or classifier.

    Returns:
        DenialSanitizeResult detailing sanitized output, removal metrics, and risk.
    """
    if not text:
        return DenialSanitizeResult(
            original_text=text,
            sanitized_text=text,
            invisible_codepoints_removed=0,
            has_bidi_controls=False,
            spoof_risk=SpoofRiskLevel.NONE,
            removed_characters=[],
        )

    removed_chars: list[str] = []
    has_bidi = False
    invisible_count = 0

    for ch in text:
        cp = ord(ch)
        if cp in _BIDI_CONTROL_CODEPOINTS:
            has_bidi = True
            removed_chars.append(f"U+{cp:04X}")
        elif cp in _INVISIBLE_CODEPOINTS:
            invisible_count += 1
            removed_chars.append(f"U+{cp:04X}")

    sanitized = _DANGEROUS_CHARS_PATTERN.sub("", text)
    unique_removed = sorted(set(removed_chars))

    if has_bidi:
        risk = SpoofRiskLevel.HIGH
    elif invisible_count > 0:
        risk = SpoofRiskLevel.LOW
    else:
        risk = SpoofRiskLevel.NONE

    return DenialSanitizeResult(
        original_text=text,
        sanitized_text=sanitized,
        invisible_codepoints_removed=len(removed_chars),
        has_bidi_controls=has_bidi,
        spoof_risk=risk,
        removed_characters=unique_removed,
    )


def sanitize_denial_payload(payload: dict[str, str]) -> dict[str, str]:
    """Sanitize all string values within a gate guard denial payload dictionary.

    Args:
        payload: Mapping of string keys to raw string values.

    Returns:
        New dictionary with all string values sanitized.
    """
    return {
        key: sanitize_denial_message(value).sanitized_text
        for key, value in payload.items()
    }
