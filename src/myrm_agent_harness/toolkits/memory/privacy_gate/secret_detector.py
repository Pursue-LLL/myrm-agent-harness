"""Deterministic pattern-based detector for high-risk secrets and credentials.

Scans memory candidates for API tokens, private keys, database connection strings,
JWTs, and password fields with zero LLM API cost.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.privacy_gate.types::PrivacyViolationType, SecretFinding (POS: Type definitions and
  contracts for memory privacy boundary and allowlist gate.)

[OUTPUT]
- DeterministicSecretDetector: Zero-cost regex scanner for deterministic credential detection and redaction.

[POS]
Deterministic pattern-based detector for high-risk secrets and credentials.
"""

from __future__ import annotations

import re
from typing import ClassVar

from myrm_agent_harness.toolkits.memory.privacy_gate.types import (
    PrivacyViolationType,
    SecretFinding,
)


def _mask_evidence(secret: str) -> str:
    """Mask sensitive string leaving only safe boundary characters."""
    stripped = secret.strip()
    if len(stripped) <= 6:
        return "***"
    return f"{stripped[:3]}...{stripped[-3:]}"


class DeterministicSecretDetector:
    """Zero-cost regex scanner for deterministic credential detection and redaction."""

    _PATTERNS: ClassVar[list[tuple[PrivacyViolationType, re.Pattern[str], str]]] = [
        (
            PrivacyViolationType.PRIVATE_KEY,
            re.compile(
                r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
            ),
            "Asymmetric Private Key Block",
        ),
        (
            PrivacyViolationType.API_KEY,
            re.compile(r"\b(?:sk-ant-[a-zA-Z0-9_\-]{20,}|sk-[a-zA-Z0-9_\-]{20,})\b"),
            "LLM Provider API Key",
        ),
        (
            PrivacyViolationType.API_KEY,
            re.compile(r"\b(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{50,})\b"),
            "GitHub Access Token",
        ),
        (
            PrivacyViolationType.API_KEY,
            re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
            "AWS Access Key ID",
        ),
        (
            PrivacyViolationType.CONNECTION_URI,
            re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[a-zA-Z0-9_.\-]+:[^@\s/]+@[a-zA-Z0-9_.\-]+"),
            "Database Connection URI with Credentials",
        ),
        (
            PrivacyViolationType.JWT_TOKEN,
            re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
            "JSON Web Token",
        ),
        (
            PrivacyViolationType.PASSWORD_FIELD,
            re.compile(
                r"""(?i)\b(?:password|passwd|secret|api[_\-]?key|access[_\-]?token)\s*[:=]\s*["']?([^"'\s]{8,})["']?"""
            ),
            "Hardcoded Credential Assignment",
        ),
    ]

    def scan(self, text: str) -> list[SecretFinding]:
        """Scan candidate text and collect all detected secret findings."""
        findings: list[SecretFinding] = []
        if not text:
            return findings

        for v_type, pattern, category in self._PATTERNS:
            for match in pattern.finditer(text):
                # Calculate line number
                start_pos = match.start()
                line_no = text.count("\n", 0, start_pos) + 1
                matched_str = match.group(0)
                findings.append(
                    SecretFinding(
                        violation_type=v_type,
                        snippet_masked=_mask_evidence(matched_str),
                        category=category,
                        line_number=line_no,
                    )
                )
        return findings

    def redact(self, text: str) -> tuple[str, list[SecretFinding]]:
        """Redact detected secrets with safe semantic placeholders.

        Returns:
            Tuple of (redacted_text, collected_findings).
        """
        findings = self.scan(text)
        if not findings:
            return text, []

        redacted = text
        for v_type, pattern, _ in self._PATTERNS:
            placeholder = f"[REDACTED:{v_type.value.upper()}]"
            redacted = pattern.sub(placeholder, redacted)

        return redacted, findings
