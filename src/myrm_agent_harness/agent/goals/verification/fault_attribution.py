"""Execution fault attribution classifier for acceptance verification.

[INPUT]
- str: command, stdout, stderr, exit_code

[OUTPUT]
- FaultCategory: Enum of fault categories (INFRA_ENVIRONMENT_FAILURE vs CODE_DEFECT_FAILURE)
- FaultAttribution: Structured diagnosis with category, matched indicator, and actionable guidance

[POS]
Distinguishes between environmental/infrastructure anomalies (network timeout, port conflicts,
OOM, missing daemon, disk full, etc.) and true application code defects.
Prevents agents from blindly modifying business code when external dependencies fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class FaultCategory(str, Enum):
    """Categorization of an execution or verification failure."""

    INFRA_ENVIRONMENT_FAILURE = "INFRA_ENVIRONMENT_FAILURE"
    CODE_DEFECT_FAILURE = "CODE_DEFECT_FAILURE"


@dataclass(frozen=True)
class FaultAttribution:
    """Structured attribution result explaining why a verification command failed."""

    category: FaultCategory
    reason: str
    guidance: str
    matched_pattern: str | None = None

    @property
    def is_infra(self) -> bool:
        return self.category == FaultCategory.INFRA_ENVIRONMENT_FAILURE

    @property
    def is_infra_fault(self) -> bool:
        return self.is_infra

    @property
    def kind(self) -> FaultCategory:
        return self.category


# Alias for compatibility with classify_fault callers
FaultKind = FaultCategory
FaultClassificationResult = FaultAttribution


# Regex rules for diagnosing environment/infrastructure failures
_INFRA_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # Network / Connection refused / Reset
    (
        re.compile(
            r"(connection\s+refused|connection\s+reset\s+by\s+peer|ECONNREFUSED|ECONNRESET|"
            r"failed\s+to\s+connect\s+to|cannot\s+assign\s+requested\s+address)",
            re.IGNORECASE,
        ),
        "Network connection refused or unreachable host/service",
        "Target service is not running or unreachable. DO NOT mutate business code. "
        "Check required daemon/service status or network configuration.",
    ),
    # Timeout / Gateway errors
    (
        re.compile(
            r"(timed?\s*out|ETIMEDOUT|502\s+bad\s+gateway|504\s+gateway\s+timeout|"
            r"request\s+timeout|deadline\s+exceeded)",
            re.IGNORECASE,
        ),
        "Network or upstream service timeout / gateway error",
        "Service request timed out. DO NOT mutate business code. Verify service responsiveness or network latency.",
    ),
    # Out of Memory / Kill 137
    (
        re.compile(
            r"(out\s+of\s+memory|killed:\s*9|fatal\s+error:\s+runtime:\s+out\s+of\s+memory|"
            r"exit\s+(code|status)\s+137|OOMKilled|oom-killer)",
            re.IGNORECASE,
        ),
        "System Out Of Memory (OOM) / process killed by OS",
        "Process was terminated by system OOM killer (exit 137). Check memory limits or resource contention; "
        "do not modify business logic unless fixing an obvious runaway leak.",
    ),
    # Disk / Quota
    (
        re.compile(
            r"(no\s+space\s+left\s+on\s+device|disk\s+quota\s+exceeded|ENOSPC)",
            re.IGNORECASE,
        ),
        "Disk space or quota exhausted",
        "Storage volume is full (ENOSPC). Free disk space or increase disk allocation before retrying.",
    ),
    # Port conflict
    (
        re.compile(
            r"(address\s+already\s+in\s+use|port\s+\d+\s+is\s+already\s+in\s+use|EADDRINUSE)",
            re.IGNORECASE,
        ),
        "Port conflict (EADDRINUSE)",
        "Requested port is occupied by another process. Terminate existing listener or adjust port binding.",
    ),
    # Docker daemon / Container runtime
    (
        re.compile(
            r"(cannot\s+connect\s+to\s+the\s+docker\s+daemon|is\s+the\s+docker\s+daemon\s+running|"
            r"docker\.sock:\s+connect:\s+no\s+such\s+file)",
            re.IGNORECASE,
        ),
        "Docker daemon / container runtime unavailable",
        "Docker daemon is not running or accessible. Start the docker engine; do not alter codebase.",
    ),
    # External Database connection down
    (
        re.compile(
            r"(redis\.exceptions\.\w*connectionerror|psycopg2\.operationalerror:\s+could\s+not\s+connect|"
            r"mysql\.connector\.errors\.interfaceerror:\s*2003|pymongo\.errors\.serverselectiontimeouterror)",
            re.IGNORECASE,
        ),
        "Database service unavailable",
        "Database connection failed. Ensure database daemon is active and credentials/ports are correct.",
    ),
]


def classify_execution_fault(
    command: str,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
) -> FaultAttribution:
    """Classify failure as either an infrastructure defect or a code defect.

    Inspects exit code, stdout, and stderr against infrastructure heuristics.
    Returns FaultAttribution with guidance to prevent hallucinated code alterations.
    """
    combined_output = f"{stdout}\n{stderr}"

    # Explicit exit 137 is universally SIGKILL (often OOM)
    if exit_code == 137:
        return FaultAttribution(
            category=FaultCategory.INFRA_ENVIRONMENT_FAILURE,
            reason="Process was killed by SIGKILL / OS OOM killer (exit code 137)",
            guidance=(
                "[INFRASTRUCTURE FAULT] Process was killed due to memory limits or external termination (exit code 137). "
                "DO NOT blindly edit application code. Inspect resource limits or container quotas."
            ),
            matched_pattern="exit_code=137",
        )

    for pattern, desc, guidance in _INFRA_PATTERNS:
        match = pattern.search(combined_output)
        if match:
            matched_text = match.group(0)
            return FaultAttribution(
                category=FaultCategory.INFRA_ENVIRONMENT_FAILURE,
                reason=f"Infrastructure anomaly: {desc} (matched: {matched_text!r})",
                guidance=(
                    f"[INFRASTRUCTURE FAULT - {desc.upper()}]\n"
                    f"Evidence: '{matched_text}'\n"
                    f"Actionable Guidance: {guidance}\n"
                    "WARNING: Modifying application business code will NOT resolve this environment error!"
                ),
                matched_pattern=matched_text,
            )

    return FaultAttribution(
        category=FaultCategory.CODE_DEFECT_FAILURE,
        reason=f"Command '{command}' failed with exit code {exit_code} (Code defect)",
        guidance="Failure appears related to application logic, compilation, or test assertions.",
        matched_pattern=None,
    )


def classify_fault(
    command: str = "",
    exit_code: int = -1,
    stdout: str = "",
    stderr: str = "",
    exception: Exception | None = None,
) -> FaultAttribution:
    """Convenience wrapper for fault classification supporting optional exception objects."""
    if exception is not None:
        err_str = str(exception)
        stderr = f"{stderr}\n{err_str}" if stderr else err_str
    return classify_execution_fault(
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )
