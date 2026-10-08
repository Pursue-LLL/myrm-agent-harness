"""Precision detector for provider 400 Bad Request and context window overflow errors.

[INPUT]
- agent.context_management.dual_mode_compaction.dual_mode_compaction_types::ProviderOverflowKind (POS: Types
  and schemas for proactive watermark compaction and reactive 400 self-healing.)

[OUTPUT]
- ProviderOverflowDetector: Detects and categorizes context window exceeded and token overflow errors across
  providers.

[POS]
Precision detector for provider 400 Bad Request and context window overflow errors.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .dual_mode_compaction_types import ProviderOverflowKind


class ProviderOverflowDetector:
    """Detects and categorizes context window exceeded and token overflow errors across providers."""

    # Common patterns emitted by OpenAI, Anthropic, DeepSeek, Gemini, and local vLLM/Ollama
    _OVERFLOW_PATTERNS = [
        (
            re.compile(r"context_length_exceeded|maximum context length|context window exceeded", re.IGNORECASE),
            ProviderOverflowKind.CONTEXT_WINDOW_EXCEEDED,
        ),
        (
            re.compile(r"max_tokens_exceeded|exceeds the max tokens limit|tokens limit exceeded", re.IGNORECASE),
            ProviderOverflowKind.MAX_TOKENS_EXCEEDED,
        ),
        (
            re.compile(r"prompt is too long|request is too large|prompt exceeds limit|payload too large", re.IGNORECASE),
            ProviderOverflowKind.PROMPT_TOO_LONG,
        ),
        (
            re.compile(r"400.*(tokens?|context|too long|limit exceeded)", re.IGNORECASE),
            ProviderOverflowKind.CONTEXT_WINDOW_EXCEEDED,
        ),
    ]

    @classmethod
    def is_context_overflow(cls, error_obj_or_msg: Exception | str) -> bool:
        """Return True if exception or error string matches provider overflow signatures."""
        kind, _ = cls.classify_overflow(error_obj_or_msg)
        return kind is not None

    @classmethod
    def classify_overflow(
        cls,
        error_obj_or_msg: Exception | str,
    ) -> Tuple[Optional[ProviderOverflowKind], str]:
        """Classify the error object or string into a standardized ProviderOverflowKind."""
        raw_msg = str(error_obj_or_msg)

        for pattern, kind in cls._OVERFLOW_PATTERNS:
            if pattern.search(raw_msg):
                return kind, raw_msg

        return None, raw_msg

    @classmethod
    def extract_token_overshoot(cls, error_message: str) -> Optional[int]:
        """Attempt to extract exact numeric token overshoot from provider error message if present."""
        # e.g., "This model's maximum context length is 128000 tokens. However, your messages resulted in 131500 tokens"
        match = re.search(r"resulted in (\d+) tokens.*maximum context length is (\d+)", error_message, re.IGNORECASE)
        if match:
            actual = int(match.group(1))
            maximum = int(match.group(2))
            if actual > maximum:
                return actual - maximum

        match_rev = re.search(r"limit is (\d+).*requested (\d+)", error_message, re.IGNORECASE)
        if match_rev:
            maximum = int(match_rev.group(1))
            actual = int(match_rev.group(2))
            if actual > maximum:
                return actual - maximum

        return None
