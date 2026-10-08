# [INPUT] None (Domain text and environment variable dictionaries)
# [OUTPUT] PreSealSecretMasker, MaskedSecretRecord
# [POS] Pre-seal credential redactor, pattern scanner, and scoped environment pruner

"""Pre-seal secret masking and scoped pruner for sealed decision continuity."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re

from myrm_agent_harness.agent.context_management.sealed_decision_handoff.sealed_decision_types import (
    SecretMaskingError,
)

_SENSITIVE_KEY_NAMES = {
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "API_KEY",
    "APIKEY",
    "PRIVATE_KEY",
    "AUTH",
    "CREDENTIALS",
    "CREDENTIAL",
    "ACCESS_KEY",
}


@dataclass(frozen=True)
class MaskedSecretRecord:
    """Audit footprint of a masked credential."""

    fingerprint: str
    pattern_name: str
    original_len: int


class PreSealSecretMasker:
    """Redacts sensitive credentials and enforces scoped clearance pruning."""

    def __init__(self) -> None:
        self._compiled_patterns: list[tuple[str, re.Pattern[str]]] = [
            ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
            ("anthropic_key", re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b")),
            ("openai_key", re.compile(r"\bsk-[a-zA-Z0-9_\-]{20,}\b")),
            ("github_token", re.compile(r"\bgh[pousr][_\-][a-zA-Z0-9]{20,}\b")),
            ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
            ("bearer_token", re.compile(r"(?i)\bbearer\s+([a-zA-Z0-9_\-\.]{20,})\b")),
            ("database_dsn", re.compile(r"[a-zA-Z+]+://[^:\s]+:([^@\s]+)@[^\s]+")),
            ("key_value_secret", re.compile(r'(?i)(["\']?(?:api_key|token|secret|password)["\']?\s*[:=]\s*["\'])([^"\'\s]{8,})(["\'])')),
        ]

    @staticmethod
    def _generate_fingerprint(secret: str) -> str:
        """Derive an 8-character deterministic hex fingerprint from a secret."""
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return digest[:8]

    def mask_text(self, text: str) -> str:
        """Mask all detected secret occurrences in freeform text."""
        if not text:
            return ""

        result = text
        for pattern_name, pattern in self._compiled_patterns:
            if pattern_name == "bearer_token":
                result = pattern.sub(
                    lambda m: f"Bearer [REDACTED_SECRET:{self._generate_fingerprint(m.group(1))}]",
                    result,
                )
            elif pattern_name == "database_dsn":
                result = pattern.sub(
                    lambda m: m.group(0).replace(m.group(1), f"[REDACTED_SECRET:{self._generate_fingerprint(m.group(1))}]"),
                    result,
                )
            elif pattern_name == "key_value_secret":
                result = pattern.sub(
                    lambda m: f"{m.group(1)}[REDACTED_SECRET:{self._generate_fingerprint(m.group(2))}]{m.group(3)}",
                    result,
                )
            else:
                result = pattern.sub(
                    lambda m: f"[REDACTED_SECRET:{self._generate_fingerprint(m.group(0))}]",
                    result,
                )
        return result

    def mask_dict(self, data: dict[str, str]) -> dict[str, str]:
        """Mask sensitive values in a key-value dictionary."""
        masked: dict[str, str] = {}
        for k, v in data.items():
            if self._is_sensitive_key_name(k):
                masked[k] = f"[REDACTED_SECRET:{self._generate_fingerprint(v)}]"
            else:
                masked[k] = self.mask_text(v)
        return masked

    @staticmethod
    def _is_sensitive_key_name(key_name: str) -> bool:
        """Check if an environment variable or dictionary key implies a secret."""
        upper = key_name.upper()
        return any(term in upper for term in _SENSITIVE_KEY_NAMES)

    def scoped_prune_env_vars(
        self,
        env_vars: dict[str, str],
        allowed_prefixes: list[str] | None = None,
    ) -> dict[str, str]:
        """Prune sensitive or unpermitted environment variables according to least privilege."""
        pruned: dict[str, str] = {}
        prefixes = allowed_prefixes or ["APP_", "MYRM_", "WORKSPACE_", "LANG", "PYTHON", "PATH", "ENV_"]

        for key, value in env_vars.items():
            # Never include explicitly sensitive key names
            if self._is_sensitive_key_name(key):
                continue

            # Check if key starts with allowed prefixes
            if any(key.startswith(pfx) for pfx in prefixes):
                pruned[key] = self.mask_text(value)

        return pruned
