"""Shell execution acceptance criterion.

[INPUT]
- toolkits.code_execution.executors.base::get_executor (POS: Sandbox executor acquisition)
- toolkits.code_execution.executors.models::ExecutionContext (POS: Execution parameters)
- .base::BaseCriterion, VerificationResult (POS: Base classes)

[OUTPUT]
- ShellCriterion: Verifies success by executing a shell command in the sandbox.

[POS]
Provides sandbox-isolated command verification with timeouts to prevent infinite loops.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from myrm_agent_harness.agent.goals.verification.base import (
    BaseCriterion,
    VerificationResult,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider


class ShellCriterion(BaseCriterion):
    """Verifies completion by executing a shell command in the current sandbox."""

    def __init__(self, command: str, timeout_seconds: int = 60, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.command = command
        self.timeout_seconds = timeout_seconds

    async def verify(
        self, goal_provider: GoalProvider | None = None
    ) -> VerificationResult:
        executor = get_executor()
        if not executor:
            return VerificationResult(
                passed=False,
                reason="System Error: Sandbox executor not found. Cannot verify.",
                error_logs="Missing execution environment.",
            )

        context = ExecutionContext(
            code=self.command,
            timeout=self.timeout_seconds,
        )

        try:
            result = await executor.execute_bash(context)
            if result.exit_code == 0:
                return VerificationResult(passed=True)

            error_msg = f"Command failed with exit code {result.exit_code}.\n"
            if result.stdout:
                error_msg += f"Stdout:\n{result.stdout}\n"
            if result.stderr:
                error_msg += f"Stderr:\n{result.stderr}\n"

            return VerificationResult(
                passed=False,
                reason=f"Shell command failed: {self.command}",
                error_logs=error_msg,
            )
        except Exception as e:
            return VerificationResult(
                passed=False,
                reason=f"Failed to execute verification command: {self.command}",
                error_logs=str(e),
            )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ShellCriterion:
        return cls(
            command=data["command"], timeout_seconds=data.get("timeout_seconds", 60)
        )
