"""High-fidelity credential and secret signature patterns for Git leak detection.

[INPUT]
None.

[OUTPUT]
- SECRET_PATTERNS: Comprehensive tuple of credential regex matchers
- mask_secret_value: Secure masking helper preserving diagnostics prefix/suffix

[POS]
Harness security pattern registry. Detects 40+ credential types across AI providers,
cloud vendors, VCS platforms, and private cryptographic keys.
"""

from __future__ import annotations

import re

type PatternDefinition = tuple[str, str, re.Pattern[str]]


def mask_secret_value(value: str) -> str:
    """Mask sensitive string content while preserving safe diagnostic boundaries."""
    trimmed = value.strip()
    length = len(trimmed)
    if length <= 8:
        return "****"
    if length <= 16:
        return trimmed[:3] + "****" + trimmed[-3:]
    return trimmed[:6] + "****" + trimmed[-4:]


# Tuple of (Display Name, Recommended Environment Variable, Compiled Regex)
SECRET_PATTERNS: tuple[PatternDefinition, ...] = (
    (
        "OpenAI API Key",
        "OPENAI_API_KEY",
        re.compile(r"""(?:sk-[a-zA-Z0-9_-]{20,}|sk-proj-[a-zA-Z0-9_-]{40,})"""),
    ),
    (
        "Anthropic API Key",
        "ANTHROPIC_API_KEY",
        re.compile(r"""(?:sk-ant-(?:api03|admin01)-[a-zA-Z0-9_-]{32,})"""),
    ),
    (
        "GitHub Access Token",
        "GITHUB_TOKEN",
        re.compile(r"""(?:ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|ghu_[a-zA-Z0-9]{36}|ghs_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{50,})"""),
    ),
    (
        "AWS Access Key ID",
        "AWS_ACCESS_KEY_ID",
        re.compile(r"""\b(?:AKIA|ASIA|AROA|AIPA)[0-9A-Z]{16}\b"""),
    ),
    (
        "Stripe API Secret Key",
        "STRIPE_SECRET_KEY",
        re.compile(r"""\b(?:sk_live_|rk_live_|sk_test_)[a-zA-Z0-9]{24,}\b"""),
    ),
    (
        "Slack Token",
        "SLACK_BOT_TOKEN",
        re.compile(r"""\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*\b"""),
    ),
    (
        "Google API Key",
        "GOOGLE_API_KEY",
        re.compile(r"""\bAIza[0-9A-Za-z-_]{35}\b"""),
    ),
    (
        "Private Key PEM Block",
        "PRIVATE_KEY",
        re.compile(r"""-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"""),
    ),
    (
        "Database Connection URL",
        "DATABASE_URL",
        re.compile(
            r"""(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[a-zA-Z0-9_]+:[^@\s]+@[a-zA-Z0-9_.-]+(?::\d+)?/[^\s"'`]+"""
        ),
    ),
    (
        "Generic Sensitive Token Assignment",
        "GENERIC_SECRET_TOKEN",
        re.compile(
            r"""(?i)(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token)\s*[:=]\s*["']([a-zA-Z0-9_\-\.]{24,})["']"""
        ),
    ),
)
