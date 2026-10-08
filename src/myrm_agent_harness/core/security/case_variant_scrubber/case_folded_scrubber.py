"""
[POS] src/myrm_agent_harness/core/security/case_variant_scrubber/case_folded_scrubber.py
[INPUT] fnmatch, logging, time, typing
[OUTPUT] CaseFoldedCredentialScrubber

Implements canonical case-folding and delimiter normalization for environment variables.
Defends subprocesses against case-variant credential leakage (e.g. Openai_Api_Key, github_Token).
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import fnmatch
import logging
import time

from .types import (
    ScrubActionEnum,
    ScrubAuditReport,
    ScrubbedEnvRecord,
)

logger = logging.getLogger(__name__)

# Standard canonical sensitive patterns evaluated against folded keys
CANONICAL_SENSITIVE_PATTERNS: tuple[str, ...] = (
    # Generic credential suffixes
    "*_key",
    "*_token",
    "*_secret",
    "*_password",
    "*_auth",
    "*_credential",
    "*_credentials",
    "*_api_key",
    "*_access_key",
    "*_private_key",
    # Specific AI & Cloud vendor patterns
    "openai_*",
    "anthropic_*",
    "gemini_*",
    "aws_*",
    "azure_*",
    "github_*",
    "gitlab_*",
    "huggingface_*",
    "cohere_*",
    "mistral_*",
    "groq_*",
    "deepseek_*",
    # Exact standalone keywords
    "api_key",
    "access_token",
    "auth_token",
    "secret_key",
    "private_key",
    "password",
)

REDACTED_PLACEHOLDER: str = "[REDACTED_BY_SCRUBBER]"


class CaseFoldedCredentialScrubber:
    """Deep scrubber that folds case and normalizes delimiters to intercept credential variants."""

    def __init__(
        self,
        custom_patterns: tuple[str, ...] | None = None,
    ) -> None:
        self._patterns: tuple[str, ...] = custom_patterns or CANONICAL_SENSITIVE_PATTERNS

    @staticmethod
    def normalize_env_key(raw_key: str) -> str:
        """Normalize key to lowercase with hyphens converted to underscores."""
        return raw_key.strip().lower().replace("-", "_")

    def match_pattern(self, folded_key: str) -> str | None:
        """Check if normalized folded key matches any sensitive credential pattern."""
        for pattern in self._patterns:
            if fnmatch.fnmatch(folded_key, pattern):
                return pattern
        return None

    def detect_injection_attempts(self, env_dict: dict[str, str]) -> list[str]:
        """Detect intentional mixed-case or hyphenated credential injection vectors."""
        suspicious: list[str] = []
        for raw_key in env_dict:
            folded = self.normalize_env_key(raw_key)
            if self.match_pattern(folded) is not None and (raw_key != raw_key.upper() or "-" in raw_key):
                suspicious.append(raw_key)
        return suspicious

    def scrub_env(
        self,
        env_dict: dict[str, str],
        action: ScrubActionEnum = ScrubActionEnum.DROP,
        whitelist: set[str] | None = None,
    ) -> tuple[dict[str, str], ScrubAuditReport]:
        """Deeply scrub environment dictionary against case variant credential leaks."""
        clean_env: dict[str, str] = {}
        scrubbed_records: list[ScrubbedEnvRecord] = []
        effective_whitelist = {self.normalize_env_key(k) for k in (whitelist or set())}
        injections = self.detect_injection_attempts(env_dict)

        dropped_count = 0
        redacted_count = 0

        for raw_key, raw_val in env_dict.items():
            folded = self.normalize_env_key(raw_key)

            if folded in effective_whitelist:
                clean_env[raw_key] = raw_val
                continue

            matched_pattern = self.match_pattern(folded)
            if matched_pattern is not None:
                # Key is a sensitive credential
                if action == ScrubActionEnum.DROP:
                    dropped_count += 1
                    scrubbed_records.append(
                        ScrubbedEnvRecord(
                            original_key=raw_key,
                            folded_key=folded,
                            action=ScrubActionEnum.DROP,
                            matched_pattern=matched_pattern,
                            redacted_value="",
                        )
                    )
                    logger.warning(
                        "Scrubbed case-variant credential key (DROPPED): %s (folded: %s, rule: %s)",
                        raw_key,
                        folded,
                        matched_pattern,
                    )
                elif action == ScrubActionEnum.REDACT_PLACEHOLDER:
                    redacted_count += 1
                    clean_env[raw_key] = REDACTED_PLACEHOLDER
                    scrubbed_records.append(
                        ScrubbedEnvRecord(
                            original_key=raw_key,
                            folded_key=folded,
                            action=ScrubActionEnum.REDACT_PLACEHOLDER,
                            matched_pattern=matched_pattern,
                            redacted_value=REDACTED_PLACEHOLDER,
                        )
                    )
                    logger.warning(
                        "Scrubbed case-variant credential key (REDACTED): %s (folded: %s, rule: %s)",
                        raw_key,
                        folded,
                        matched_pattern,
                    )
                else:
                    # ALLOW_PASSTHROUGH
                    clean_env[raw_key] = raw_val
            else:
                clean_env[raw_key] = raw_val

        report = ScrubAuditReport(
            total_scanned=len(env_dict),
            total_dropped=dropped_count,
            total_redacted=redacted_count,
            scrubbed_records=tuple(scrubbed_records),
            detected_injections=tuple(injections),
            timestamp=time.time(),
        )

        return clean_env, report
