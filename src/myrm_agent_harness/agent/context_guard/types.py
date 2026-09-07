from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ContextGuardConfig:
    """Configuration for message size limits and spillover paths."""

    max_message_chars: int = 16_000
    preview_chars: int = 300
    spillover_dir_name: str = ".myrm/spillover"
    spillover_ttl_seconds: int = 86_400  # 24 hours


@dataclass(slots=True)
class SpilloverPayload:
    """Metadata describing a spilled file payload."""

    spill_id: str
    file_path: str
    char_count: int
    line_count: int
    sha256_digest: str
    summary_preview: str
    original_role: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SpilloverResult:
    """Result of context guard evaluation on an incoming message."""

    spilled: bool
    sanitized_content: str
    payload: SpilloverPayload | None = None
    original_char_count: int = 0
