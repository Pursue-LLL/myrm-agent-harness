"""Type definitions for Zero-Trust Credential Isolation and Git Leakage Shield.

[INPUT]
None.

[OUTPUT]
- SecretMatch, GitProbeResult, RedactionResult, GitCommitSecretBlockedError

[POS]
Harness core security contracts for secret leak prevention during Git operations,
ephemeral secret injection, and outbound text redaction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecretMatch:
    """Detected credential match within code, diff, or outbound text."""

    secret_type: str
    pattern_name: str
    line_number: int
    raw_snippet: str
    masked_snippet: str
    suggested_env_var: str
    file_path: str = "staged"


@dataclass(frozen=True, slots=True)
class GitProbeResult:
    """Outcome of pre-commit credential leak scan."""

    has_leak: bool
    findings: list[SecretMatch]
    scanned_lines_count: int
    summary: str
    scanned_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Result of scrubbing secrets from outbound text or logs."""

    redacted_text: str
    redactions_count: int
    detected_types: list[str]


class GitCommitSecretBlockedError(Exception):
    """Raised when a git commit or push is blocked due to detected secrets."""

    def __init__(self, findings: list[SecretMatch]) -> None:
        count = len(findings)
        types_str = ", ".join(sorted({f.secret_type for f in findings}))
        super().__init__(
            f"Git operation blocked: {count} credential leak(s) detected ({types_str}). "
            "Remove hardcoded secrets from staging before committing."
        )
        self.findings = findings
