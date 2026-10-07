"""[POS]: myrm_agent_harness/toolkits/memory/thinking_sanitizer/cleaner.py
[INPUT]: Raw LLM output containing thinking channels, orphan closing tags, or planning drafts.
[OUTPUT]: Scrubbed clean text with sanitization telemetry and egress usability assertion.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.thinking_sanitizer.models import (
    SanitizationResult,
    ThinkingSanitizerConfig,
)

_PAIRED_TAG_REGEX: re.Pattern[str] = re.compile(
    r"<(think|thought|reflection|reasoning)>(.*?)</\1>",
    re.DOTALL | re.IGNORECASE,
)

_ORPHAN_CLOSE_REGEX: re.Pattern[str] = re.compile(
    r"^.*?</(?:think|thought|reflection|reasoning)>\s*",
    re.DOTALL | re.IGNORECASE,
)

_UNCLOSED_OPEN_REGEX: re.Pattern[str] = re.compile(
    r"<(?:think|thought|reflection|reasoning)>",
    re.IGNORECASE,
)

_DEFAULT_PLANNING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:i need to|i should|i must) (?:create|write|draft|provide|generate|summarize|record)(?: a| the)? (?:thorough |concise |brief )?(?:summary|overview|breakdown|notes?)[^\n]*\n*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:here is|here's) (?:a |the )?(?:concise |detailed |brief )?(?:summary|overview) of the (?:session|conversation|dialogue|chat):?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^let me (?:think|summarize|review|recap|break down|analyze)[^\n]*\n*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^in this (?:summary|overview), (?:i will|we will|i'll)[^\n]*\n*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^the user (?:wants|asked|prompted|instructed) (?:me )?to (?:summarize|create a summary|record)[^\n]*\n*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^okay,?\s*(?:so\s*)?(?:let's|i will|let me|we should)[^\n]*\n*",
        re.IGNORECASE,
    ),
)


class ThinkingBlockSanitizer:
    """Sanitizer and egress guard for scrubbing reasoning blocks and drafts."""

    def __init__(self, config: ThinkingSanitizerConfig | None = None) -> None:
        self._config = config or ThinkingSanitizerConfig()
        extra_compiled = tuple(
            re.compile(pattern, re.IGNORECASE)
            for pattern in self._config.extra_planning_patterns
        )
        self._planning_patterns = _DEFAULT_PLANNING_PATTERNS + extra_compiled

    @property
    def config(self) -> ThinkingSanitizerConfig:
        return self._config

    def sanitize(self, text: str) -> SanitizationResult:
        """Deep clean reasoning tags, orphan endings, and planning lead-ins."""
        if not text:
            return SanitizationResult(
                original_text=text,
                cleaned_text="",
                has_thinking_markers=False,
                has_unclosed_tags=False,
                stripped_markers_count=0,
                is_usable=False,
                rejection_reason="Empty input text",
            )

        working_text = text
        stripped_count = 0
        has_thinking_markers = False

        # 1. Scrub matched pairs: <think>...</think>, <thought>...</thought>, etc.
        pairs_found = len(_PAIRED_TAG_REGEX.findall(working_text))
        if pairs_found > 0:
            has_thinking_markers = True
            stripped_count += pairs_found
            working_text = _PAIRED_TAG_REGEX.sub("", working_text)

        # 2. Check and rescue from orphan close tag (Hermes/Honcho pattern)
        # e.g., planning draft without <think> header followed by trailing </think>
        if self._config.preserve_post_close_text and _ORPHAN_CLOSE_REGEX.search(working_text):
            has_thinking_markers = True
            stripped_count += 1
            working_text = _ORPHAN_CLOSE_REGEX.sub("", working_text)

        # 3. Detect unclosed open tags
        unclosed_match = _UNCLOSED_OPEN_REGEX.search(working_text)
        has_unclosed_tags = unclosed_match is not None
        if has_unclosed_tags:
            has_thinking_markers = True
            if self._config.drop_unclosed_tags:
                # Truncate content starting at the unclosed tag
                working_text = working_text[: unclosed_match.start()]
                stripped_count += 1

        # 4. Strip planning lead-in patterns if enabled
        if self._config.strip_planning_leadins:
            for pattern in self._planning_patterns:
                match = pattern.search(working_text.strip())
                if match and match.start() == 0:
                    working_text = working_text.strip()[match.end() :]
                    stripped_count += 1

        cleaned_text = working_text.strip()

        # 5. Evaluate usability guard
        rejection_reason: str | None = None
        is_usable = True

        if has_unclosed_tags and not self._config.drop_unclosed_tags:
            is_usable = False
            rejection_reason = "Unclosed reasoning tags detected without dropping enabled"
        elif len(cleaned_text) < self._config.min_usable_chars:
            is_usable = False
            rejection_reason = (
                f"Cleaned content length ({len(cleaned_text)}) is below "
                f"min_usable_chars ({self._config.min_usable_chars})"
            )

        return SanitizationResult(
            original_text=text,
            cleaned_text=cleaned_text,
            has_thinking_markers=has_thinking_markers,
            has_unclosed_tags=has_unclosed_tags,
            stripped_markers_count=stripped_count,
            is_usable=is_usable,
            rejection_reason=rejection_reason,
        )

    def is_usable_summary(self, text: str) -> str | None:
        """Bi-directional egress guard: returns clean summary or None to omit."""
        if not text or not text.strip():
            return None

        result = self.sanitize(text)
        if not result.is_usable or not result.cleaned_text:
            return None
        return result.cleaned_text
