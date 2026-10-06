"""Security gate for memory write paths: zero-width Unicode stripping and credential leak prevention.

[INPUT]
myrm_agent_harness.toolkits.memory.prompt_cache_guard.models::SecurityThreatBlockedError (POS: 安全威胁拦截异常)

[OUTPUT]
ZeroWidthAndCredentialLeakScanner: Static scanner validating memory write payloads, removing invisible Unicode, and blocking secret leaks.

[POS]
前缀缓存稳定守卫之安全门禁层。在记忆持久化与不可变快照编译前执行强制安全审查：
彻底清除隐蔽零宽字符（防御潜伏式提示词注入）、硬阻断高危凭证与 API Key 外泄、并拦截完全重复条目。
"""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.toolkits.memory.prompt_cache_guard.models import (
    SecurityThreatBlockedError,
)

logger = logging.getLogger(__name__)

# Zero-width spaces, soft hyphens, joiners, directional isolates, and BOM marks
_INVISIBLE_UNICODE_REGEX = re.compile(r"[\u200B-\u200F\u2060-\u2064\u206A-\u206F\uFEFF\u00AD]")

# Standard API key, token, private key, and cloud credential patterns
_CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_api_key", re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9]{10,}-[a-zA-Z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIzaSy[a-zA-Z0-9_-]{33}\b")),
    ("private_key_header", re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----")),
]


class ZeroWidthAndCredentialLeakScanner:
    """Security scanner enforcing clean text, secret isolation, and duplicate prevention."""

    @classmethod
    def strip_invisible_unicode(cls, text: str) -> tuple[str, bool]:
        """Strip hidden zero-width characters and report if any were present."""
        if not text:
            return ("", False)

        has_invisible = bool(_INVISIBLE_UNICODE_REGEX.search(text))
        cleaned = _INVISIBLE_UNICODE_REGEX.sub("", text)
        return (cleaned, has_invisible)

    @classmethod
    def scan_credential_leaks(cls, text: str) -> list[str]:
        """Scan text for sensitive tokens, private keys, or API credentials."""
        if not text:
            return []

        matched_patterns: list[str] = []
        for name, pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(text):
                matched_patterns.append(name)
        return matched_patterns

    @classmethod
    def is_duplicate(cls, candidate: str, existing_items: list[str]) -> bool:
        """Check whether candidate item is an exact duplicate of existing memory entries."""
        normalized_candidate = candidate.strip().lower()
        if not normalized_candidate:
            return True

        return any(item.strip().lower() == normalized_candidate for item in existing_items)

    @classmethod
    def validate_and_sanitize(cls, text: str, existing_items: list[str]) -> str:
        """Validate candidate text against security policies and strip invisible characters.

        Raises:
            SecurityThreatBlockedError: If credentials or exact duplicates are detected.
        """
        if not text or not text.strip():
            raise SecurityThreatBlockedError("empty_content", ["empty_payload"])

        cleaned, had_invisible = cls.strip_invisible_unicode(text)
        if had_invisible:
            logger.info("Zero-width invisible Unicode characters automatically stripped from memory candidate.")

        credentials = cls.scan_credential_leaks(cleaned)
        if credentials:
            raise SecurityThreatBlockedError("credential_leak", credentials)

        if cls.is_duplicate(cleaned, existing_items):
            raise SecurityThreatBlockedError("duplicate_entry", ["exact_duplicate"])

        return cleaned.strip()
