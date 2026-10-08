"""GateGuard denial path Unicode sanitizer.

[INPUT]
- Untrusted file paths, tool arguments, or denial reason strings.

[OUTPUT]
- Cleaned strings safe from zero-width bypass, UI spoofing, and invisible injection.

[POS]
- Core sanitization engine for gate guard denial output paths.
"""

from __future__ import annotations

from typing import Final

from .types import DenialSanitizePolicy, SanitizeResult
from .unicode_policy import DANGEROUS_DENIAL_UNICODE_RE, detect_categories

_DEFAULT_POLICY: Final[DenialSanitizePolicy] = DenialSanitizePolicy()


class GateGuardDenialSanitizer:
    """Sanitizer that cleans dangerous invisible Unicode from gate guard denial paths."""

    def __init__(self, policy: DenialSanitizePolicy = _DEFAULT_POLICY) -> None:
        self._policy = policy

    @property
    def policy(self) -> DenialSanitizePolicy:
        """Return the active policy configuration."""
        return self._policy

    def sanitize_text(
        self,
        text: str,
        max_length: int | None = None,
        replacement: str | None = None,
    ) -> SanitizeResult:
        """Sanitize an arbitrary string against dangerous invisible Unicode.

        Replaces dangerous/invisible characters with the replacement character,
        normalizes whitespace if configured, and enforces max_length bound.
        """
        if not text:
            return SanitizeResult(
                original_text="",
                sanitized_text="",
                characters_removed_count=0,
                categories_detected=(),
                was_truncated=False,
            )

        eff_replacement = self._policy.replacement_char if replacement is None else replacement
        categories = detect_categories(text)

        # Count total matches of dangerous characters
        matches = list(DANGEROUS_DENIAL_UNICODE_RE.finditer(text))
        removed_count = len(matches)

        # Substitute dangerous characters
        cleaned = DANGEROUS_DENIAL_UNICODE_RE.sub(eff_replacement, text)

        if self._policy.strip_surrounding_whitespace:
            cleaned = cleaned.strip()

        limit = max_length if max_length is not None else len(cleaned)
        was_truncated = False
        if len(cleaned) > limit:
            cleaned = cleaned[:limit]
            was_truncated = True

        return SanitizeResult(
            original_text=text,
            sanitized_text=cleaned,
            characters_removed_count=removed_count,
            categories_detected=categories,
            was_truncated=was_truncated,
        )

    def sanitize_path(
        self,
        path: str,
        max_length: int | None = None,
    ) -> SanitizeResult:
        """Sanitize file path intended for denial messages or UI presentation."""
        eff_limit = max_length if max_length is not None else self._policy.max_path_length
        return self.sanitize_text(path, max_length=eff_limit)

    def sanitize_reason(
        self,
        reason: str,
        max_length: int | None = None,
    ) -> SanitizeResult:
        """Sanitize denial reason explanation intended for audit logs or user review."""
        eff_limit = max_length if max_length is not None else self._policy.max_reason_length
        return self.sanitize_text(reason, max_length=eff_limit)

    def sanitize_denial_payload(
        self,
        tool_name: str,
        target_path: str | None,
        reason: str,
    ) -> dict[str, str]:
        """Sanitize complete denial payload dictionary for security auditing."""
        sanitized_tool = self.sanitize_text(tool_name, max_length=100).sanitized_text
        sanitized_reason = self.sanitize_reason(reason).sanitized_text
        payload: dict[str, str] = {
            "tool_name": sanitized_tool,
            "reason": sanitized_reason,
        }
        if target_path is not None:
            payload["target_path"] = self.sanitize_path(target_path).sanitized_text
        return payload


def sanitize_denial_path(path: str, max_length: int = 500) -> str:
    """Convenience helper to sanitize a denial path string with default policy."""
    sanitizer = GateGuardDenialSanitizer()
    return sanitizer.sanitize_path(path, max_length=max_length).sanitized_text


def sanitize_denial_reason(reason: str, max_length: int = 1000) -> str:
    """Convenience helper to sanitize a denial reason string with default policy."""
    sanitizer = GateGuardDenialSanitizer()
    return sanitizer.sanitize_reason(reason, max_length=max_length).sanitized_text
