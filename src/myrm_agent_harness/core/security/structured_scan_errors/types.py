"""Domain types and models for Structured JSON Scan Failure Errors.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing structured scan error codes,
  context, remediation advice, and JSON contract envelopes.

[POS]
- Harness core security domain models ensuring CLI/scanner failure predictability
  and programmatic error classification without brittle text matching.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum


class ScanErrorCode(StrEnum):
    """Categorized error codes for security and dependency scan failures."""

    TARGET_UNREACHABLE = "SCAN_TARGET_UNREACHABLE"
    TIMEOUT = "SCAN_TIMEOUT"
    PERMISSION_DENIED = "SCAN_PERMISSION_DENIED"
    ENGINE_CRASH = "SCAN_ENGINE_CRASH"
    RULESET_SYNTAX_ERROR = "SCAN_RULESET_SYNTAX_ERROR"
    RATE_LIMITED = "SCAN_RATE_LIMITED"
    OUTPUT_CORRUPTED = "SCAN_OUTPUT_CORRUPTED"
    AUTHENTICATION_FAILED = "SCAN_AUTHENTICATION_FAILED"
    OUT_OF_MEMORY = "SCAN_OUT_OF_MEMORY"
    UNKNOWN_FAILURE = "SCAN_UNKNOWN_FAILURE"


class RemediationAction(StrEnum):
    """Actionable decision for CI/CD or Agent pipeline orchestrators."""

    RETRY = "RETRY"
    SKIP = "SKIP"
    BLOCK_PIPELINE = "BLOCK_PIPELINE"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"


@dataclass(frozen=True)
class ScanErrorContext:
    """Execution context captured when a scan failure occurs."""

    scan_id: str
    target_path_or_url: str
    scanner_engine: str
    exit_code: int | None
    timestamp: float = field(default_factory=time.time)
    raw_stderr_snippet: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ScanRemediationAdvice:
    """Actionable remediation guidance for automated pipeline or human engineer."""

    suggested_action: RemediationAction
    remediation_steps: tuple[str, ...]
    retryable: bool
    backoff_seconds: float | None = None


@dataclass(frozen=True)
class StructuredScanErrorEnvelope:
    """Standardized JSON contract emitted when a security scan fails."""

    error_code: ScanErrorCode
    message: str
    severity: str
    context: ScanErrorContext
    remediation: ScanRemediationAdvice

    def to_dict(self) -> dict[str, str | int | float | bool | None | dict[str, str] | list[str]]:
        """Convert structured envelope into JSON-serializable dictionary."""
        data = asdict(self)
        # Ensure enums serialize to their string values
        data["error_code"] = self.error_code.value
        data["remediation"]["suggested_action"] = self.remediation.suggested_action.value
        data["remediation"]["remediation_steps"] = list(self.remediation.remediation_steps)
        return data

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize envelope into formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
