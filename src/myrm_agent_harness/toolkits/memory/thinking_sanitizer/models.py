"""[POS]: myrm_agent_harness/toolkits/memory/thinking_sanitizer/models.py
[INPUT]: Sanitizer configuration options and sanitization inspection outputs.
[OUTPUT]: Data structures for thinking block scrubbing, tag detection, and egress guard validation.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThinkingSanitizerConfig:
    """Configuration for ThinkingBlockSanitizer."""

    min_usable_chars: int = 10
    strip_planning_leadins: bool = True
    preserve_post_close_text: bool = True
    drop_unclosed_tags: bool = True
    extra_planning_patterns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SanitizationResult:
    """Result of scrubbing thinking blocks and drafts from text."""

    original_text: str
    cleaned_text: str
    has_thinking_markers: bool
    has_unclosed_tags: bool
    stripped_markers_count: int
    is_usable: bool
    rejection_reason: str | None = None
