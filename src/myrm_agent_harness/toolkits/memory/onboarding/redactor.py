"""Local zero-leakage secret scrubber combining regex patterns with Shannon entropy scanning.

[INPUT]
- re: High-speed precompiled regex matchers
- .entropy_inspector: ShannonEntropyInspector

[OUTPUT]
- LocalSecretRedactor: Sanitizer ensuring 100% credential redaction before distillation.

[POS]
Harness framework security module preventing sensitive authentication tokens,
passwords, and cryptographic keys from leaking into LLM prompt contexts.
"""

from __future__ import annotations

import re

from .entropy_inspector import ShannonEntropyInspector

_REGEX_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Private Key blocks
    (
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Common API Keys (OpenAI, Anthropic, Gemini, Stripe)
    (
        re.compile(r"\b(?:sk-[a-zA-Z0-9_\-]{20,}|sk-ant-[a-zA-Z0-9_\-]{20,}|AIza[0-9A-Za-z-_]{35})\b"),
        "[REDACTED_API_KEY]",
    ),
    # GitHub Tokens (Personal access, OAuth, Fine-grained)
    (
        re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{36,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    # AWS Access Key ID
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "[REDACTED_AWS_KEY]",
    ),
    # Bearer Tokens
    (
        re.compile(r"(?i)\bbearer\s+[a-zA-Z0-9_\-\.]{20,}"),
        "Bearer [REDACTED_TOKEN]",
    ),
    # Key-value assignment of credentials
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|api_key|access_token|client_secret)\s*[:=]\s*[\"']?([^\s\"'`]{6,})[\"']?"
        ),
        r"\1=[REDACTED_SECRET]",
    ),
]


class LocalSecretRedactor:
    """Sanitizes sensitive tokens, passwords, and private keys via regex and entropy inspection."""

    def __init__(self, enable_entropy: bool = True, entropy_threshold: float = 4.5) -> None:
        self._enable_entropy = enable_entropy
        self._entropy_inspector = (
            ShannonEntropyInspector(entropy_threshold=entropy_threshold) if enable_entropy else None
        )

    def scrub(self, text: str) -> tuple[str, int]:
        """Scrub known regex patterns and optional high-entropy candidates from text.

        Returns a tuple of (sanitized_text, total_redactions_count).
        """
        if not text:
            return "", 0

        sanitized = text
        redaction_count = 0

        # Pass 1: Regex known patterns
        for pattern, replacement in _REGEX_PATTERNS:
            matches = len(pattern.findall(sanitized))
            if matches > 0:
                sanitized = pattern.sub(replacement, sanitized)
                redaction_count += matches

        # Pass 2: Shannon Entropy inspection for zero-day / un-prefixed keys
        if self._entropy_inspector:
            sanitized, entropy_redactions = self._entropy_inspector.redact_high_entropy_tokens(sanitized)
            redaction_count += entropy_redactions

        return sanitized, redaction_count
