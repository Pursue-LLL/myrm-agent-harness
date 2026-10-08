"""High performance log and command redaction engine for sandbox execution environments.

[INPUT]
- Raw logs, terminal outputs, command strings, and arguments.

[OUTPUT]
- RedactionResult containing redacted text, redaction count, and detected categories.

[POS]
- Harness core security module preventing credential leakages in sandbox execution logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myrm_agent_harness.core.security.sandbox_log_continuation.types import (
    RedactionCategory,
    RedactionResult,
)


@dataclass(frozen=True)
class _CompiledRedactionRule:
    category: RedactionCategory
    pattern: re.Pattern[str]
    replacement: str


class SandboxLogRedactor:
    """Detects and redacts sensitive credentials, tokens, and private keys in logs."""

    def __init__(self) -> None:
        self._rules: list[_CompiledRedactionRule] = []
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        # Private key blocks
        self._rules.append(
            _CompiledRedactionRule(
                category=RedactionCategory.PRIVATE_KEY,
                pattern=re.compile(
                    r"-----BEGIN\s+[A-Z\s]+PRIVATE\s+KEY-----[\s\S]+?-----END\s+[A-Z\s]+PRIVATE\s+KEY-----",
                    re.MULTILINE,
                ),
                replacement="[REDACTED_PRIVATE_KEY]",
            )
        )

        # JWT tokens (header.payload.signature)
        self._rules.append(
            _CompiledRedactionRule(
                category=RedactionCategory.BEARER_TOKEN,
                pattern=re.compile(
                    r"eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]+",
                ),
                replacement="[REDACTED_JWT_TOKEN]",
            )
        )

        # Bearer Authorization headers / tokens
        self._rules.append(
            _CompiledRedactionRule(
                category=RedactionCategory.BEARER_TOKEN,
                pattern=re.compile(
                    r"(?i)\bBearer\s+[A-Za-z0-9\-_.~+/=]{16,}\b",
                ),
                replacement="Bearer [REDACTED_BEARER_TOKEN]",
            )
        )

        # Common API keys (OpenAI sk-..., GitHub ghp_..., Slack xoxb-..., etc.)
        self._rules.append(
            _CompiledRedactionRule(
                category=RedactionCategory.API_KEY,
                pattern=re.compile(
                    r"\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9]{10,})\b",
                ),
                replacement="[REDACTED_API_KEY]",
            )
        )

        # Embedded URL credentials (e.g. https://user:password@hostname, postgresql://user:pass@host)
        self._rules.append(
            _CompiledRedactionRule(
                category=RedactionCategory.URL_CREDENTIAL,
                pattern=re.compile(
                    r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^:\s@]+):([^@\s]+)@",
                ),
                replacement=r"\1\2:[REDACTED_CREDENTIAL]@",
            )
        )

        # Environment variable / CLI flag assignments
        self._rules.append(
            _CompiledRedactionRule(
                category=RedactionCategory.PASSWORD_ENV,
                pattern=re.compile(
                    r"(?i)\b((?:api[-_]?key|access[-_]?token|auth[-_]?token|token|password|passwd|secret)[-_]?(?:val|key|secret)?\s*[:=]\s*)(?:\"[^\"]+\"|'[^']+'|[^\s;,&|]+)",
                ),
                replacement=r"\1[REDACTED_SECRET]",
            )
        )

    def add_custom_rule(
        self,
        category: RedactionCategory,
        regex_pattern: str,
        replacement: str,
    ) -> None:
        """Register a custom redaction rule pattern."""
        compiled = re.compile(regex_pattern)
        self._rules.append(
            _CompiledRedactionRule(
                category=category,
                pattern=compiled,
                replacement=replacement,
            )
        )

    def redact_text(self, text: str) -> RedactionResult:
        """Scan input text, apply all redaction rules, and return structured result."""
        current_text = text
        detected_categories: set[RedactionCategory] = set()
        total_substitutions = 0

        for rule in self._rules:
            new_text, count = rule.pattern.subn(rule.replacement, current_text)
            if count > 0:
                detected_categories.add(rule.category)
                total_substitutions += count
                current_text = new_text

        return RedactionResult(
            original_length=len(text),
            redacted_text=current_text,
            redaction_count=total_substitutions,
            categories_redacted=sorted(
                detected_categories, key=lambda c: c.value
            ),
        )

    def redact_command(
        self,
        command: str,
        args: list[str],
    ) -> tuple[str, list[str]]:
        """Redact sensitive parameters and values in command line invocations."""
        redacted_cmd = self.redact_text(command).redacted_text
        redacted_args = [self.redact_text(arg).redacted_text for arg in args]
        return redacted_cmd, redacted_args
