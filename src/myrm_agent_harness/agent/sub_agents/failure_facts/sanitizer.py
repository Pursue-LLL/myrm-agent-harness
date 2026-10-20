"""[INPUT] Raw strings, stack traces, and diagnostics payload.
[OUTPUT] SafeFailureSanitizer enforcing credential scrubbing, path masking, and strict 4096-byte boundary.
[POS] Privacy and credential isolation firewall for Subagent Diagnostic Protocol.
"""

from __future__ import annotations

import re

MAX_DIAGNOSTIC_FACTS_BYTES: int = 4096
TRUNCATION_MARKER: str = " ... [TRUNCATED_4096B]"


class SafeFailureSanitizer:
    """Sanitizer stripping credentials, absolute paths, and enforcing strict byte boundaries."""

    # Bearer tokens / JWTs
    _BEARER_PATTERN = re.compile(
        r"(Bearer\s+)[\w\-\.+=/]+",
        re.IGNORECASE,
    )

    # API keys and secret-looking tokens (e.g. sk-..., key-...)
    _SECRET_PATTERN = re.compile(
        r"(?i)(api[_-]?key|secret|password|access[_-]?token|auth[_-]?token|private[_-]?key)"
        r"(\s*[:=]\s*[\"']?)([\w\-\.]{6,})([\"']?)"
    )
    _GENERIC_KEY_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9]{16,})\b")

    # Absolute filesystem paths (e.g. /Users/..., /home/..., /root/..., /var/...)
    _PATH_PATTERN = re.compile(
        r"(/(?:Users|home|root|private/var|var)/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*)/([A-Za-z0-9_.\-]+)"
    )

    # Environment variable key-value pairs (e.g. OPENAI_API_KEY=..., GITHUB_TOKEN=...)
    _ENV_VAR_PATTERN = re.compile(
        r"\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)=([^\s,;]+)",
        re.IGNORECASE,
    )

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Deeply scrub credentials, absolute paths, and secrets from diagnostic text."""
        if not text:
            return ""

        # 1. Redact Bearer tokens
        sanitized = cls._BEARER_PATTERN.sub(r"\1[REDACTED_TOKEN]", text)

        # 2. Redact sk-... keys
        sanitized = cls._GENERIC_KEY_PATTERN.sub("[REDACTED_KEY]", sanitized)

        # 3. Redact key-value secrets
        sanitized = cls._SECRET_PATTERN.sub(r"\1\2[REDACTED_SECRET]\4", sanitized)

        # 4. Redact sensitive env vars
        sanitized = cls._ENV_VAR_PATTERN.sub(r"\1=[REDACTED_ENV]", sanitized)

        # 5. Mask absolute paths to protect local username and layout
        sanitized = cls._PATH_PATTERN.sub(r"[PATH_REDACTED]/\2", sanitized)

        return sanitized

    @classmethod
    def enforce_byte_limit(
        cls,
        text: str,
        max_bytes: int = MAX_DIAGNOSTIC_FACTS_BYTES,
    ) -> tuple[str, int]:
        """Strictly bound text size within max_bytes limit safely with UTF-8 character alignment.

        Returns:
            Tuple of (bounded_text, actual_byte_length).
        """
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text, len(encoded)

        marker_bytes = TRUNCATION_MARKER.encode("utf-8")
        budget = max_bytes - len(marker_bytes)
        if budget <= 0:
            return TRUNCATION_MARKER, len(marker_bytes)

        # Safe truncation avoiding broken multi-byte sequences
        truncated = encoded[:budget].decode("utf-8", errors="ignore") + TRUNCATION_MARKER
        final_bytes = truncated.encode("utf-8")
        return truncated, len(final_bytes)
