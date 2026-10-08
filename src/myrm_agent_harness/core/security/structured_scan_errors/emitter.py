"""Structured scan failure classifier and JSON contract emitter.

[INPUT]
- Process exit codes, stderr/stdout output streams, target paths, scanner engine metadata.

[OUTPUT]
- StructuredScanErrorEnvelope containing machine-readable error codes and remediation advice.

[POS]
- Harness core security emitter standardizing scan failures across CLI and automated pipelines.
"""

from __future__ import annotations

import re
import time
from typing import Final

from myrm_agent_harness.core.security.structured_scan_errors.types import (
    RemediationAction,
    ScanErrorCode,
    ScanErrorContext,
    ScanRemediationAdvice,
    StructuredScanErrorEnvelope,
)

_RATE_LIMIT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:rate\s*limit|too\s+many\s+requests|status\s*429|http\s*429)", re.IGNORECASE
)
_OOM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:out\s+of\s+memory|killed\s+process|oom|exit\s+code\s+137)", re.IGNORECASE
)
_AUTH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:authentication\s+failed|unauthorized|invalid\s+token|401\s+unauthorized)", re.IGNORECASE
)
_PERMISSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:permission\s+denied|forbidden|eacces|403\s+forbidden)", re.IGNORECASE
)
_TIMEOUT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:timed?\s*out|deadline\s+exceeded|timed\s+out\s+after)", re.IGNORECASE
)
_SYNTAX_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:syntax\s*error|failed\s+to\s+parse\s+ruleset|invalid\s+yaml|invalid\s+json)", re.IGNORECASE
)
_CRASH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:segmentation\s+fault|core\s+dumped|command\s+not\s+found|no\s+such\s+file\s+or\s+directory)", re.IGNORECASE
)


class ScanFailureEmitter:
    """Classifies raw scanner exit conditions and generates structured JSON error envelopes."""

    @classmethod
    def classify_failure(
        cls,
        exit_code: int | None,
        stderr: str,
    ) -> tuple[ScanErrorCode, str, RemediationAction, tuple[str, ...], bool, float | None]:
        """Determine categorized error code and remediation steps from process results."""
        normalized_text = (stderr or "").strip().lower()

        # 1. Out of memory
        if exit_code == 137 or _OOM_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.OUT_OF_MEMORY,
                "Scanner terminated due to memory exhaustion (OOM).",
                RemediationAction.RETRY,
                (
                    "Increase container/sandbox memory allocation limit.",
                    "Exclude large binary or generated artifact directories from scan scope.",
                ),
                True,
                10.0,
            )

        # 2. Rate limiting
        if _RATE_LIMIT_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.RATE_LIMITED,
                "Scanner API requests were throttled by upstream provider rate limit.",
                RemediationAction.RETRY,
                (
                    "Back off requests and retry after rate limit reset window.",
                    "Configure local vulnerability database caching to reduce external queries.",
                ),
                True,
                60.0,
            )

        # 3. Authentication failure
        if _AUTH_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.AUTHENTICATION_FAILED,
                "Scanner failed authentication against vulnerability database or registry.",
                RemediationAction.BLOCK_PIPELINE,
                (
                    "Verify provided scanner API key / token validity.",
                    "Refresh expired credentials in secure secret broker.",
                ),
                False,
                None,
            )

        # 4. Permission denied
        if _PERMISSION_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.PERMISSION_DENIED,
                "Scanner lacked sufficient filesystem or network permissions.",
                RemediationAction.BLOCK_PIPELINE,
                (
                    "Check workspace file read permissions for scan worker user.",
                    "Ensure target repository is mounted with read access.",
                ),
                False,
                None,
            )

        # 5. Timeout
        if exit_code == 124 or _TIMEOUT_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.TIMEOUT,
                "Scan execution exceeded allotted execution time deadline.",
                RemediationAction.RETRY,
                (
                    "Extend scan timeout ceiling parameter.",
                    "Split monolithic repository scanning into parallel sub-directory batches.",
                ),
                True,
                5.0,
            )

        # 6. Ruleset syntax error
        if _SYNTAX_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.RULESET_SYNTAX_ERROR,
                "Custom security ruleset contains malformed syntax.",
                RemediationAction.BLOCK_PIPELINE,
                (
                    "Validate security rule YAML/JSON against schema.",
                    "Fix rule regex patterns and parameter definitions.",
                ),
                False,
                None,
            )

        # 7. Engine crash
        if exit_code == 127 or _CRASH_PATTERN.search(normalized_text):
            return (
                ScanErrorCode.ENGINE_CRASH,
                "Scanner binary crashed or was missing from runtime environment.",
                RemediationAction.BLOCK_PIPELINE,
                (
                    "Ensure scanner binary is installed and executable in PATH.",
                    "Check system dependencies and glibc compatibility.",
                ),
                False,
                None,
            )

        # 8. Target unreachable
        if "connection refused" in normalized_text or "could not resolve host" in normalized_text:
            return (
                ScanErrorCode.TARGET_UNREACHABLE,
                "Target host or remote registry was unreachable.",
                RemediationAction.RETRY,
                (
                    "Verify network connectivity and DNS resolution.",
                    "Check proxy settings and firewall egress rules.",
                ),
                True,
                15.0,
            )

        # Default fallback
        return (
            ScanErrorCode.UNKNOWN_FAILURE,
            f"Scanner exited with unclassified failure (exit code {exit_code}).",
            RemediationAction.ESCALATE_HUMAN,
            (
                "Inspect raw stderr and scanner log artifacts for diagnostic clues.",
                "File an issue with reproduction bundle if problem persists.",
            ),
            False,
            None,
        )

    def emit_failure(
        self,
        scan_id: str,
        target_path_or_url: str,
        scanner_engine: str,
        exit_code: int | None,
        stderr: str = "",
        metadata: dict[str, str] | None = None,
    ) -> StructuredScanErrorEnvelope:
        """Construct structured scan failure error envelope."""
        code, msg, action, steps, retryable, backoff = self.classify_failure(exit_code, stderr)

        # Truncate stderr snippet if overly long to avoid payload bloat
        snippet = (stderr.strip()[:1000] + "...") if len(stderr) > 1000 else (stderr.strip() or None)

        context = ScanErrorContext(
            scan_id=scan_id,
            target_path_or_url=target_path_or_url,
            scanner_engine=scanner_engine,
            exit_code=exit_code,
            timestamp=time.time(),
            raw_stderr_snippet=snippet,
            metadata=metadata or {},
        )

        remediation = ScanRemediationAdvice(
            suggested_action=action,
            remediation_steps=steps,
            retryable=retryable,
            backoff_seconds=backoff,
        )

        severity = "HIGH" if action == RemediationAction.BLOCK_PIPELINE else "MEDIUM"
        if code in (ScanErrorCode.OUT_OF_MEMORY, ScanErrorCode.ENGINE_CRASH):
            severity = "CRITICAL"

        return StructuredScanErrorEnvelope(
            error_code=code,
            message=msg,
            severity=severity,
            context=context,
            remediation=remediation,
        )

    def emit_from_exception(
        self,
        scan_id: str,
        target_path_or_url: str,
        scanner_engine: str,
        exc: Exception,
        metadata: dict[str, str] | None = None,
    ) -> StructuredScanErrorEnvelope:
        """Construct structured envelope from caught Python exception."""
        stderr_msg = f"{type(exc).__name__}: {exc}"
        return self.emit_failure(
            scan_id=scan_id,
            target_path_or_url=target_path_or_url,
            scanner_engine=scanner_engine,
            exit_code=-1,
            stderr=stderr_msg,
            metadata=metadata,
        )
