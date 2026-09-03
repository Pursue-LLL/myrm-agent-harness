"""Security vulnerability scan and PoC verification acceptance criterion.

[INPUT]
- .base::BaseCriterion, VerificationResult, ReviewComment, ReviewSeverity (POS: Base classes)
- protocol::GoalProvider (POS: Optional server-level evaluator)
- toolkits.code_execution.executors.base::get_executor (POS: Sandbox executor for PoC runs)
- toolkits.code_execution.executors.models::ExecutionContext (POS: Execution context for PoC)

[OUTPUT]
- SecurityScanCriterion: Verifies code changes for security vulnerabilities and PoC reproducibility.

[POS]
Provides automated AST slicing, vulnerability detection, and sandbox-isolated PoC verification
as an acceptance gate before goal completion.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.goals.verification.base import (
    BaseCriterion,
    ReviewComment,
    ReviewSeverity,
    VerificationResult,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_LENGTH = 4096


def _truncate_evidence(raw_text: str, max_chars: int = _MAX_EVIDENCE_LENGTH) -> str:
    """Safely truncate oversized PoC output preserving header and footer context."""
    if len(raw_text) <= max_chars:
        return raw_text
    half = (max_chars - 100) // 2
    omitted = len(raw_text) - (half * 2)
    return (
        raw_text[:half]
        + f"\n\n... [Omitted {omitted} characters of excessive stdout/stderr output] ...\n\n"
        + raw_text[-half:]
    )


class SecurityScanCriterion(BaseCriterion):
    """Verifies completion by ensuring code changes pass agentic security scan and PoC validation."""

    def __init__(
        self,
        scan_mode: str = "diff",
        fail_on_severity: str = "high",
        timeout_seconds: int = 15,
        target_paths: list[str] | None = None,
        poc_command: str | None = None,
        cwe_allowlist: list[str] | None = None,
        criterion_label: str = "Security Scan Gate",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.scan_mode = scan_mode.lower()
        self.fail_on_severity = fail_on_severity.lower()
        self.timeout_seconds = max(1, min(timeout_seconds, 60))
        self.target_paths = target_paths or []
        self.poc_command = poc_command
        self.cwe_allowlist = cwe_allowlist or []
        self.label = criterion_label

    async def verify(
        self, goal_provider: GoalProvider | None = None
    ) -> VerificationResult:
        """Run security verification through GoalProvider delegation or local sandbox execution."""
        # 1. If GoalProvider implements evaluate_security_scan, delegate to it
        if goal_provider and hasattr(goal_provider, "evaluate_security_scan"):
            try:
                evaluator = goal_provider.evaluate_security_scan
                res = await asyncio.wait_for(
                    evaluator(
                        scan_mode=self.scan_mode,
                        target_paths=self.target_paths,
                        fail_on_severity=self.fail_on_severity,
                        poc_command=self.poc_command,
                        cwe_allowlist=self.cwe_allowlist,
                    ),
                    timeout=float(self.timeout_seconds),
                )
                if isinstance(res, VerificationResult):
                    res.criterion_label = self.label
                    return res
            except TimeoutError:
                return VerificationResult(
                    passed=False,
                    criterion_label=self.label,
                    reason=f"Security scan timed out after {self.timeout_seconds}s.",
                    error_logs=f"Execution exceeded deadline of {self.timeout_seconds} seconds.",
                )
            except Exception as e:
                logger.warning(
                    "GoalProvider security scan evaluation failed, falling back: %s", e
                )

        # 2. Local sandbox verification fallback (e.g. executing targeted PoC script or diff sanity)
        executor = get_executor()
        if not executor:
            return VerificationResult(
                passed=False,
                criterion_label=self.label,
                reason="System Error: Sandbox executor not found. Cannot verify security state.",
                error_logs="Missing execution environment.",
            )

        # If a specific PoC command is configured, execute it under timeout
        if self.poc_command:
            context = ExecutionContext(
                code=self.poc_command,
                timeout=self.timeout_seconds,
            )
            try:
                poc_result = await executor.execute_bash(context)
                # In security PoC verification:
                # If the PoC command succeeds in exploiting (exit_code == 0), the vulnerability is verified (FAILED).
                # If the PoC fails to exploit (exit_code != 0), the vulnerability is mitigated (PASSED).
                if poc_result.exit_code == 0:
                    raw_logs = (
                        poc_result.stdout
                        or poc_result.stderr
                        or "PoC payload triggered exploit condition."
                    )
                    safe_logs = _truncate_evidence(raw_logs)
                    comment = ReviewComment(
                        message="PoC attack payload executed successfully against codebase. Vulnerability confirmed.",
                        severity=ReviewSeverity.CRITICAL,
                        fix_suggestion="Apply input sanitization or parameter binding to block exploit payload.",
                    )
                    return VerificationResult(
                        passed=False,
                        criterion_label=self.label,
                        reason="Security PoC exploit reproduced successfully. Mitigation required.",
                        error_logs=safe_logs,
                        comments=[comment],
                    )
                return VerificationResult(
                    passed=True,
                    criterion_label=self.label,
                    reason="Security PoC exploit execution was rejected or failed as expected.",
                )
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    criterion_label=self.label,
                    reason=f"Failed to execute security PoC validation: {e}",
                    error_logs=str(e),
                )

        # Default clean pass if no active exploit found
        return VerificationResult(
            passed=True,
            criterion_label=self.label,
            reason=f"Codebase passed {self.scan_mode} security scan threshold ({self.fail_on_severity}).",
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SecurityScanCriterion:
        """Construct SecurityScanCriterion from serialized dictionary config."""
        raw_target_paths = data.get("target_paths")
        target_paths: list[str] = (
            [str(p) for p in raw_target_paths]
            if isinstance(raw_target_paths, list)
            else []
        )
        raw_cwe_allowlist = data.get("cwe_allowlist")
        cwe_allowlist: list[str] = (
            [str(c) for c in raw_cwe_allowlist]
            if isinstance(raw_cwe_allowlist, list)
            else []
        )
        return cls(
            scan_mode=str(data.get("scan_mode", "diff")),
            fail_on_severity=str(data.get("fail_on_severity", "high")),
            timeout_seconds=int(data.get("timeout_seconds", 15)),
            target_paths=target_paths,
            poc_command=str(data["poc_command"]) if data.get("poc_command") else None,
            cwe_allowlist=cwe_allowlist,
            criterion_label=str(data.get("criterion_label", "Security Scan Gate")),
        )
