"""Protected patterns matcher and syntax safety shield.

Shields immutable engineering facts (file paths, line numbers, error codes,
terminal commands, and fenced code blocks) from aggressive semantic reduction.
"""

from __future__ import annotations

import re
from typing import ClassVar

from myrm_agent_harness.runtime.context.tokenomics_compression_types import (
    ProtectedPatternsConfig,
)


class ProtectedPatternsMatcher:
    """Detects, masks, and restores non-negotiable engineering facts.

    Uses temporary token placeholders during semantic compression to guarantee
    zero corruption of file paths, line numbers, and fenced code blocks.
    """

    PLACEHOLDER_PREFIX: str = "__MYRM_PROTECTED_"

    REGEX_FENCED_CODE: ClassVar[re.Pattern[str]] = re.compile(
        r"```[a-zA-Z0-9_-]*\n[\s\S]*?```", re.MULTILINE
    )
    REGEX_INLINE_CODE: ClassVar[re.Pattern[str]] = re.compile(r"`[^`\n]+`")
    REGEX_FILE_PATH: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:/[a-zA-Z0-9_.-]+)+|(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+"
    )
    REGEX_LINE_NUMBER: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:line|lines|L)\s*\d+(?:-\d+)?\b|:\d+:\d+", re.IGNORECASE
    )
    REGEX_COMMAND: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:pytest|ruff|git|cargo|tsc|npm|yarn|pnpm|python|python3|pip|uv)\s+[^\n;,]+"
    )
    REGEX_ERROR_CODE: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:[A-Z][a-zA-Z0-9_]*Error|Exit\s+code\s+\d+|E\d{3,4}|W\d{3,4})\b"
    )

    def __init__(self, config: ProtectedPatternsConfig | None = None) -> None:
        self.config = config or ProtectedPatternsConfig()

    def mask_protected_entities(
        self,
        text: str,
    ) -> tuple[str, dict[str, str]]:
        """Scan text and replace all protected patterns with immutable placeholders.

        Returns (masked_text, placeholder_map).
        """
        if not text:
            return "", {}

        masked = text
        placeholders: dict[str, str] = {}
        counter = 0

        def replace_with_placeholder(match: re.Match[str]) -> str:
            nonlocal counter
            matched_str = match.group(0)
            token = f"{self.PLACEHOLDER_PREFIX}{counter}__"
            placeholders[token] = matched_str
            counter += 1
            return token

        # 1. First priority: Fenced and inline code blocks if code_safe is enabled
        if self.config.code_safe:
            masked = self.REGEX_FENCED_CODE.sub(replace_with_placeholder, masked)
            masked = self.REGEX_INLINE_CODE.sub(replace_with_placeholder, masked)

        # 2. File paths
        if self.config.protect_file_paths:
            masked = self.REGEX_FILE_PATH.sub(replace_with_placeholder, masked)

        # 3. Line numbers
        if self.config.protect_line_numbers:
            masked = self.REGEX_LINE_NUMBER.sub(replace_with_placeholder, masked)

        # 4. Commands
        if self.config.protect_commands:
            masked = self.REGEX_COMMAND.sub(replace_with_placeholder, masked)

        # 5. Error codes
        if self.config.protect_error_codes:
            masked = self.REGEX_ERROR_CODE.sub(replace_with_placeholder, masked)

        # 6. Custom protected keywords
        for custom_term in self.config.custom_protected_terms:
            if custom_term and custom_term in masked:
                term_pat = re.compile(re.escape(custom_term))
                masked = term_pat.sub(replace_with_placeholder, masked)

        return masked, placeholders

    def restore_protected_entities(
        self,
        masked_text: str,
        placeholders: dict[str, str],
    ) -> str:
        """Substitute placeholders back to their verbatim original values."""
        if not placeholders or not masked_text:
            return masked_text

        restored = masked_text
        for token, original in placeholders.items():
            restored = restored.replace(token, original)

        return restored
