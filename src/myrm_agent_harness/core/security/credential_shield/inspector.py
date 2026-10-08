"""Command line credential inspector and process table leakage analyzer.

[INPUT]
- Shell command strings or argv argument lists.

[OUTPUT]
- ProcessLeakageAnalysis detailing exposed credentials, risk levels, and redactions.

[POS]
- Harness core security inspector detecting secrets passed via process CLI arguments.
"""

from __future__ import annotations

import re
import shlex
from typing import Final

from myrm_agent_harness.core.security.credential_shield.types import (
    LeakageRiskLevel,
    ProcessLeakageAnalysis,
)

_SECRET_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    (
        "HTTP_AUTH_HEADER",
        re.compile(
            r"(-H|--header)\s+['\"]?(Authorization:\s*(Bearer|Basic|Token)\s+[^'\"]+)['\"]?",
            re.IGNORECASE,
        ),
    ),
    (
        "API_KEY_HEADER",
        re.compile(
            r"(-H|--header)\s+['\"]?((X-Api-Key|Api-Key):\s*[^'\"]+)['\"]?",
            re.IGNORECASE,
        ),
    ),
    (
        "CLI_API_KEY_FLAG",
        re.compile(
            r"(--api-key|--token|--access-token|--secret)(=|\s+)(['\"]?[a-zA-Z0-9_\-\.]{8,}['\"]?)",
            re.IGNORECASE,
        ),
    ),
    (
        "CLI_PASSWORD_FLAG",
        re.compile(
            r"(-p|--password)(=|\s+)(['\"]?[^'\"]{3,}['\"]?)",
            re.IGNORECASE,
        ),
    ),
    (
        "URL_EMBEDDED_CREDENTIAL",
        re.compile(
            r"https?://[a-zA-Z0-9_\-\.%]+:([^@\s]+)@[a-zA-Z0-9_\-\.]+",
            re.IGNORECASE,
        ),
    ),
]


class CommandLineCredentialInspector:
    """Inspects command lines for plain-text credential leaks visible in OS process tables."""

    @classmethod
    def inspect(cls, command: str | list[str]) -> ProcessLeakageAnalysis:
        """Analyze a command string or argv list for exposed secrets."""
        if isinstance(command, list):
            cmd_str = " ".join(shlex.quote(arg) for arg in command)
        else:
            cmd_str = command.strip()

        if not cmd_str:
            return ProcessLeakageAnalysis(
                is_safe_for_process_table=True,
                risk_level=LeakageRiskLevel.SAFE,
                audit_notes="Empty command string is safe.",
            )

        detected_leaks: list[str] = []

        for name, pattern in _SECRET_PATTERNS:
            matches = pattern.findall(cmd_str)
            if matches:
                detected_leaks.append(f"{name}_DETECTED")

        if detected_leaks:
            return ProcessLeakageAnalysis(
                is_safe_for_process_table=False,
                risk_level=LeakageRiskLevel.HIGH_RISK_PROCESS_TABLE_EXPOSURE,
                detected_leaks=tuple(detected_leaks),
                suggested_rewritten_command=cls.sanitize_display(cmd_str),
                audit_notes=(
                    f"Command exposes credentials in argv ({', '.join(detected_leaks)}). "
                    "Must be redirected via stdin pipeline."
                ),
            )

        return ProcessLeakageAnalysis(
            is_safe_for_process_table=True,
            risk_level=LeakageRiskLevel.SAFE,
            audit_notes="No plain-text credentials found in command arguments.",
        )

    @classmethod
    def sanitize_display(cls, command_str: str) -> str:
        """Replace detected credentials in a command string with redaction placeholders."""
        sanitized = command_str
        for _, pattern in _SECRET_PATTERNS:
            sanitized = pattern.sub(r"\1 [REDACTED_CREDENTIAL]", sanitized)
        return sanitized
