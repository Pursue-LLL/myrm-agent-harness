"""Structured JSON Scan Failure Errors Suite.

[INPUT]
- Process outputs, exit codes, scanner metadata.

[OUTPUT]
- Public exports of domain types, emitter, and JSON serialization helpers.

[POS]
- Harness core security suite providing standard structured error contracts for security scans.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.structured_scan_errors.emitter import (
    ScanFailureEmitter,
)
from myrm_agent_harness.core.security.structured_scan_errors.types import (
    RemediationAction,
    ScanErrorCode,
    ScanErrorContext,
    ScanRemediationAdvice,
    StructuredScanErrorEnvelope,
)

__all__ = [
    "RemediationAction",
    "ScanErrorCode",
    "ScanErrorContext",
    "ScanFailureEmitter",
    "ScanRemediationAdvice",
    "StructuredScanErrorEnvelope",
]
