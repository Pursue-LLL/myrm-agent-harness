"""Anti-Slop governance filter purging raw template tags, excessive blank lines, and malformed slop.

Ensures LLM response chunks streaming into client buffers are clean, compact,
and free of internal prompting artifacts or redundant filler.

[INPUT]
- agent.context_management.checked_stream_reader.checked_stream_types::AntiSlopFilterResult,
  AntiSlopViolationKind, StreamChunkFrame, StreamChunkKind (POS: Data contracts and schemas for checked
  session reply stream readers and anti-slop governance.)

[OUTPUT]
- AntiSlopFilter: Evaluates and cleans streaming chunk content against quality and integrity baselines.

[POS]
Anti-Slop governance filter purging raw template tags, excessive blank lines, and malformed slop.
"""

from __future__ import annotations

import re
from typing import Sequence

from .checked_stream_types import (
    AntiSlopFilterResult,
    AntiSlopViolationKind,
    StreamChunkFrame,
    StreamChunkKind,
)


class AntiSlopFilter:
    """Evaluates and cleans streaming chunk content against quality and integrity baselines."""

    _RAW_TAG_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"<\|(?:im_start|im_end|startoftext|endoftext|system|user|assistant)\|?>", re.IGNORECASE),
        re.compile(r"\[/?(?:INST|SYS)\]", re.IGNORECASE),
        re.compile(r"</?think>", re.IGNORECASE),
    )

    _EXCESSIVE_NEWLINES_PATTERN = re.compile(r"\n{3,}")
    _REPETITIVE_PADDING_PATTERN = re.compile(r"([=\-_~*#]{16,})")

    def filter_chunk(self, frame: StreamChunkFrame) -> AntiSlopFilterResult:
        """Inspect and sanitize a single stream frame."""
        # Non-textual control frames (e.g. heartbeat or done) bypass text slop filters
        if frame.kind in (StreamChunkKind.HEARTBEAT, StreamChunkKind.DONE):
            return AntiSlopFilterResult(is_valid=True, cleaned_content=frame.content)

        violations: list[AntiSlopViolationKind] = []
        raw_text = frame.content

        # 1. Check for empty payload
        if not raw_text.strip():
            # If it's pure empty text and not a necessary delimiter, flag violation
            if not raw_text:
                violations.append(AntiSlopViolationKind.EMPTY_PAYLOAD)
                return AntiSlopFilterResult(is_valid=False, cleaned_content="", violations=violations)

        cleaned_text = raw_text

        # 2. Check and scrub raw template artifacts
        for pat in self._RAW_TAG_PATTERNS:
            if pat.search(cleaned_text):
                violations.append(AntiSlopViolationKind.RAW_TAG_PATTERNS if False else AntiSlopViolationKind.RAW_TEMPLATE_TAG)
                cleaned_text = pat.sub("", cleaned_text)

        # 3. Collapse excessive newlines
        if self._EXCESSIVE_NEWLINES_PATTERN.search(cleaned_text):
            violations.append(AntiSlopViolationKind.EXCESSIVE_NEWLINES)
            cleaned_text = self._EXCESSIVE_NEWLINES_PATTERN.sub("\n\n", cleaned_text)

        # 4. Scrub repetitive divider padding slop
        if self._REPETITIVE_PADDING_PATTERN.search(cleaned_text):
            violations.append(AntiSlopViolationKind.REPETITIVE_PADDING)
            cleaned_text = self._REPETITIVE_PADDING_PATTERN.sub(r"----\n", cleaned_text)

        # Determine validity: if after scrubbing, content became completely empty, invalidate
        is_valid = bool(cleaned_text)

        return AntiSlopFilterResult(
            is_valid=is_valid,
            cleaned_content=cleaned_text,
            violations=violations,
        )
