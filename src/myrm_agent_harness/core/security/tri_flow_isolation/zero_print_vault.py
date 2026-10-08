"""Zero-Print Credential Vault protecting private keys from leaking into stdout/prompts."""

from __future__ import annotations

import hashlib
import re

from .types import ZeroPrintSanitizationResult

# Regex patterns for high-risk private keys and credentials
CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ethereum_private_key",
        re.compile(r"\b0x[a-fA-F0-9]{64}\b"),
    ),
    (
        "stripe_live_key",
        re.compile(r"\bsk_live_[a-zA-Z0-9]{24,}\b"),
    ),
    (
        "generic_secret_key",
        re.compile(r"(?i)(?:api_key|secret_key|private_key|token)\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{24,})['\"]"),
    ),
    (
        "rsa_openssh_private_key",
        re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC )?PRIVATE KEY-----"),
    ),
)


class ZeroPrintCredentialVault:
    """Isolates high-risk signing keys and sanitizes stdout, logs, and prompt contexts."""

    def __init__(self) -> None:
        self._isolated_keys: dict[str, str] = {}  # key_handle -> real_secret

    def store_isolated_key(self, key_secret: str, label: str = "signing_key") -> str:
        """Securely store a secret key and return an opaque non-leakable handle."""
        digest = hashlib.sha256(key_secret.encode("utf-8")).hexdigest()[:16]
        handle = f"key_handle_{label}_{digest}"
        self._isolated_keys[handle] = key_secret
        return handle

    def get_isolated_key(self, handle: str) -> str | None:
        """Retrieve real key only inside isolated signing worker."""
        return self._isolated_keys.get(handle)

    def sanitize_text(self, text: str) -> ZeroPrintSanitizationResult:
        """Scan and redact any plaintext private keys or sensitive credentials.

        Replaces discovered credentials with cryptographic hash placeholders.
        """
        if not text:
            return ZeroPrintSanitizationResult(
                sanitized_text="",
                redactions_count=0,
                detected_types=(),
            )

        sanitized = text
        redactions = 0
        detected: list[str] = []

        # 1. Match configured patterns
        for key_type, pattern in CREDENTIAL_PATTERNS:
            matches = pattern.findall(sanitized)
            if matches:
                detected.append(key_type)
                for m in matches:
                    matched_str = m if isinstance(m, str) else m[0]
                    # Compute prefix digest for audit trace without leaking key
                    h = hashlib.sha256(matched_str.encode("utf-8")).hexdigest()[:8]
                    placeholder = f"[REDACTED_CREDENTIAL:{key_type}:{h}]"
                    sanitized = sanitized.replace(matched_str, placeholder)
                    redactions += 1

        # 2. Check any registered isolated keys directly
        for handle, secret in self._isolated_keys.items():
            if secret in sanitized:
                sanitized = sanitized.replace(secret, f"[REDACTED_HANDLE:{handle}]")
                redactions += 1
                if "stored_vault_key" not in detected:
                    detected.append("stored_vault_key")

        return ZeroPrintSanitizationResult(
            sanitized_text=sanitized,
            redactions_count=redactions,
            detected_types=tuple(detected),
        )
