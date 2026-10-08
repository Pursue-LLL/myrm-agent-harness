"""Redaction Sanitization Gate with Transparent Model Notice."""

from __future__ import annotations

import re

from .types import RedactionResult

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GITHUB_PAT", re.compile(r"ghp_[A-Za-z0-9_]{36}")),
    ("GITHUB_FINE_GRAINED", re.compile(r"github_pat_[A-Za-z0-9_]{82}")),
    ("OPENAI_KEY", re.compile(r"sk-[A-Za-z0-9_\-]{32,}")),
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_\-]{32,}")),
    ("BEARER_TOKEN", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE)),
    ("AWS_ACCESS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "AWS_SECRET_KEY",
        re.compile(r"aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}", re.IGNORECASE),
    ),
]


class RedactionSanitizationGate:
    """Sanitizes sensitive tokens from process outputs and injects transparency notices for LLMs."""

    def __init__(
        self,
        custom_patterns: list[tuple[str, re.Pattern[str]]] | None = None,
        inject_notice: bool = True,
    ) -> None:
        self._patterns = list(_PATTERNS)
        if custom_patterns:
            self._patterns.extend(custom_patterns)
        self._inject_notice = inject_notice

    def sanitize(self, text: str) -> RedactionResult:
        """Scan and replace sensitive credential strings with [REDACTED_SECRET].

        Appends a structured transparency notice so LLMs know data was redacted
        by the security layer rather than corrupted, preventing hallucinated completions.
        """
        if not text:
            return RedactionResult(
                sanitized_text="",
                redacted_count=0,
                transparency_notice=None,
                matched_patterns=[],
            )

        sanitized = text
        total_redacted = 0
        matched_categories: list[str] = []

        for category, pattern in self._patterns:
            matches = pattern.findall(sanitized)
            if matches:
                total_redacted += len(matches)
                matched_categories.append(category)
                sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)

        notice: str | None = None
        if total_redacted > 0 and self._inject_notice:
            notice = (
                f"[Notice: {total_redacted} sensitive credential(s) redacted by security layer]"
            )
            # Append notice to output
            if not sanitized.endswith("\n"):
                sanitized += "\n"
            sanitized += notice

        return RedactionResult(
            sanitized_text=sanitized,
            redacted_count=total_redacted,
            transparency_notice=notice,
            matched_patterns=matched_categories,
        )
