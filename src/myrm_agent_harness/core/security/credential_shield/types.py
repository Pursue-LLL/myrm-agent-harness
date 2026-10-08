"""Domain types and models for Credential Stdin Pipelining & Process Leakage Shield.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing credential transport modes,
  process table leakage risk levels, pipelined command specifications, and analysis outcomes.

[POS]
- Harness core security models preventing token sniffing via `ps aux`, `/proc/$PID/cmdline`,
  and OS process tables by enforcing stdin pipelining and memory zeroization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CredentialTransportMode(StrEnum):
    """Method by which sensitive credentials are delivered to child processes."""

    STDIN_PIPELINE = "STDIN_PIPELINE"
    STDIN_CONFIG_STREAM = "STDIN_CONFIG_STREAM"
    ENV_VARIABLE_SECURE = "ENV_VARIABLE_SECURE"
    REJECTED_CLI_LEAKAGE = "REJECTED_CLI_LEAKAGE"


class LeakageRiskLevel(StrEnum):
    """Risk severity of command-line parameter inspection."""

    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    HIGH_RISK_PROCESS_TABLE_EXPOSURE = "HIGH_RISK_PROCESS_TABLE_EXPOSURE"


@dataclass(frozen=True)
class PipelinedCommandSpec:
    """Sanitized command specification designed for process table immunity."""

    original_command: str
    sanitized_argv: tuple[str, ...]
    stdin_payload: bytes
    transport_mode: CredentialTransportMode
    sanitized_display_cmd: str
    detected_secret_patterns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProcessLeakageAnalysis:
    """Outcome of inspecting a command line for cleartext credential exposure."""

    is_safe_for_process_table: bool
    risk_level: LeakageRiskLevel
    detected_leaks: tuple[str, ...] = field(default_factory=tuple)
    suggested_rewritten_command: str | None = None
    audit_notes: str = ""


class ProcessLeakageViolationError(Exception):
    """Raised when a command violates process table credential leakage prohibitions."""


class CredentialPipeliningError(Exception):
    """Raised when rewriting or piping a credential to standard input fails."""
