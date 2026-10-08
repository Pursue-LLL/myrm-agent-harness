"""
[POS] src/myrm_agent_harness/core/security/execution_approval_sanitizer/pattern_rules.py
[INPUT] re, types
[OUTPUT] SecretPatternRule, DEFAULT_SECRET_RULES, is_whitelisted_token
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .types import SecretType


@dataclass(frozen=True)
class SecretPatternRule:
    """Regex-based detection rule for a specific credential category."""

    secret_type: SecretType
    compiled_regex: re.Pattern[str]
    placeholder_template: str


# Pre-compiled high-confidence regular expression rules
DEFAULT_SECRET_RULES: tuple[SecretPatternRule, ...] = (
    # Anthropic API Keys (sk-ant-...)
    SecretPatternRule(
        secret_type=SecretType.ANTHROPIC_API_KEY,
        compiled_regex=re.compile(r"\b(sk-ant-[a-zA-Z0-9_\-]{20,})\b"),
        placeholder_template="[REDACTED:ANTHROPIC_KEY]",
    ),
    # OpenAI API Keys (sk-...)
    SecretPatternRule(
        secret_type=SecretType.OPENAI_API_KEY,
        compiled_regex=re.compile(r"\b(sk-(?:live|proj|admin|svc)?[a-zA-Z0-9_\-]{20,})\b"),
        placeholder_template="[REDACTED:OPENAI_KEY]",
    ),
    # GitHub Tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    SecretPatternRule(
        secret_type=SecretType.GITHUB_TOKEN,
        compiled_regex=re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{30,})\b"),
        placeholder_template="[REDACTED:GITHUB_TOKEN]",
    ),
    # AWS Access Key ID (AKIA...)
    SecretPatternRule(
        secret_type=SecretType.AWS_CREDENTIAL,
        compiled_regex=re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        placeholder_template="[REDACTED:AWS_KEY_ID]",
    ),
    # Slack Tokens (xoxb-, xoxp-, etc.)
    SecretPatternRule(
        secret_type=SecretType.SLACK_TOKEN,
        compiled_regex=re.compile(r"\b(xox[baprs]-[0-9a-zA-Z\-]{20,})\b"),
        placeholder_template="[REDACTED:SLACK_TOKEN]",
    ),
    # Authorization Bearer Tokens
    SecretPatternRule(
        secret_type=SecretType.BEARER_TOKEN,
        compiled_regex=re.compile(r"(?i)\bBearer\s+([A-Za-z0-9_\-\.]{25,})\b"),
        placeholder_template="Bearer [REDACTED:BEARER_TOKEN]",
    ),
    # Database Connection Password in URI (postgres://user:PASS@host:port/db)
    SecretPatternRule(
        secret_type=SecretType.DATABASE_PASSWORD,
        compiled_regex=re.compile(r"(?i)((?:postgres|mysql|mongodb|redis):\/\/[^:]+:)([^@\s]+)(@)"),
        placeholder_template=r"\1[REDACTED:DB_PASSWORD]\3",
    ),
)

_UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_GIT_SHA_REGEX = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def calculate_shannon_entropy(token: str) -> float:
    """Calculate Shannon Entropy score in bits per symbol."""
    if not token:
        return 0.0
    length = len(token)
    freq: dict[str, int] = {}
    for char in token:
        freq[char] = freq.get(char, 0) + 1
    entropy = 0.0
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def is_whitelisted_token(token: str) -> bool:
    """Filter out legitimate non-secret long identifiers (UUIDs, 40-char git commit SHAs)."""
    cleaned = token.strip().strip("'\"")
    if _UUID_REGEX.match(cleaned):
        return True
    return bool(_GIT_SHA_REGEX.match(cleaned))
