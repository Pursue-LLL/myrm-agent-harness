"""Context guard data models and token-pressure estimation.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类标准库)
- unicodedata::unicodedata (POS: Python Unicode 东亚宽度标准库)

[OUTPUT]
- ContextGuardConfig: thresholds controlling when a payload is spilled
- SpilloverPayload / SpilloverResult: spilled-file metadata and evaluation outcome
- estimate_token_pressure: adaptive token estimate weighting CJK glyphs at ~1.8x

[POS]
Value-object and measurement layer of the context guard subsystem. Keeps the CJK-aware
token estimate next to the config it feeds, since a naive chars/4 heuristic would
under-count CJK text by roughly an order of magnitude and let oversized payloads slip
past the guard. Pure computation: no filesystem access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import unicodedata


@dataclass(slots=True)
class ContextGuardConfig:
    """Configuration for message size limits, CJK token weighting, and spillover paths."""

    max_message_chars: int = 16_000
    # Equivalent token threshold (e.g. 8,000 tokens)
    max_token_pressure: int = 8_000
    preview_chars: int = 300
    spillover_dir_name: str = ".myrm/spillover"
    spillover_ttl_seconds: int = 86_400  # 24 hours


def estimate_token_pressure(text: str) -> int:
    """Calculate adaptive token pressure weighting CJK characters (1.8x factor).

    Mitigates Measurement Decay where Chinese/Japanese characters consume ~2-3x tokens per char.
    """
    if not text:
        return 0

    cjk_count = 0
    non_cjk_count = 0

    for char in text:
        # Check East Asian Width or common CJK Unified Ideographs
        width = unicodedata.east_asian_width(char)
        if width in ("W", "F") or ("\u4e00" <= char <= "\u9fff"):
            cjk_count += 1
        else:
            non_cjk_count += 1

    # CJK characters consume ~1.8x - 2.0x tokens in cl100k/o200k分词器
    estimated_tokens = int(cjk_count * 1.8 + non_cjk_count * 0.25)
    return estimated_tokens


@dataclass(slots=True)
class SpilloverPayload:
    """Metadata describing a spilled file payload."""

    spill_id: str
    file_path: str
    relative_path: str
    char_count: int
    line_count: int
    estimated_tokens: int
    sha256_digest: str
    summary_preview: str
    original_role: str = "user"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SpilloverResult:
    """Result of context guard evaluation on an incoming message."""

    spilled: bool
    sanitized_content: str
    payload: SpilloverPayload | None = None
    original_char_count: int = 0
    estimated_tokens: int = 0
