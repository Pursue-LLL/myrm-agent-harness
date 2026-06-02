"""Built-in job runners.

``ShellJobRunner`` is the framework-provided runner for shell-type cron jobs.
Agent runners live in the application layer (they depend on ``AgentFactory``).

Security: two-layer defense-in-depth:
1. ``shell_command_analyzer`` — pattern-based threat detection (BLOCK/ESCALATE)
2. ``safe_exec`` — structural defense: direct exec for simple commands,
   shell fallback only when shell syntax is genuinely needed

[INPUT]
- (none)

[OUTPUT]
- ShellJobRunner: Executes shell commands with timeout and safety checks.

[POS]
Built-in job runners.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.safe_exec import safe_exec
from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import has_block_threat
from myrm_agent_harness.toolkits.cron.types import CronJob, JobResult

logger = logging.getLogger(__name__)

_SHELL_TIMEOUT = 120


class ShellJobRunner:
    """Executes shell commands with timeout and safety checks."""

    async def run(self, job: CronJob, *, context: str = "") -> JobResult:
        if not job.command:
            return JobResult(success=False, error="shell job requires a command")

        threat = has_block_threat(job.command)
        if threat:
            return JobResult(
                success=False,
                error=f"command blocked: {threat.detail} (evidence: {threat.evidence})",
            )

        try:
            result = await safe_exec(job.command, timeout=_SHELL_TIMEOUT)

            if result.returncode == 0:
                return JobResult(
                    success=True,
                    output=result.stdout,
                    exit_code=0,
                )
            if result.returncode == 1:
                return JobResult(
                    success=True,
                    output=result.stdout,
                    exit_code=1,
                )
            return JobResult(
                success=False,
                output=result.stdout,
                error=result.stderr or f"exit code {result.returncode}",
                exit_code=result.returncode,
            )

        except TimeoutError:
            return JobResult(
                success=False,
                error=f"shell command timed out after {_SHELL_TIMEOUT}s",
                exit_code=124,
            )
        except Exception as exc:
            logger.warning("Shell job %s failed: %s", job.id, exc)
            return JobResult(
                success=False,
                error=str(exc),
                exit_code=1,
            )


class RouterJobRunner:
    """Zero-LLM passthrough runner.

    Directly returns the incoming context (e.g., from Webhook payload or PreFlightCondition)
    as the output, skipping any LLM or shell execution.
    """

    async def run(self, job: CronJob, *, context: str = "") -> JobResult:
        return JobResult(
            success=True,
            output=context,
            exit_code=0,
        )
