"""Execution helper utilities.

Provides common helper methods for executors: time formatting, result building, logging.

[INPUT]
- toolkits.code_execution.executors.base::ExecutionResult (POS: Code executor base classes.)

[OUTPUT]
- ExecutionHelper: Stateless execution helper.
- get_execution_helper: Return the module-level ExecutionHelper singleton.

[POS]
Execution helper utilities.
"""

import logging

from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionResult
from myrm_agent_harness.toolkits.code_execution.executors.common.executor_utils import extract_short_error

logger = logging.getLogger(__name__)


class ExecutionHelper:
    """Stateless execution helper.

    Provides time formatting, standardized result building, and logging utilities.
    All methods are static.
    """

    @staticmethod
    def format_execution_time(seconds: float) -> str:
        """Format execution time for display.

        Args:
            seconds: Execution time in seconds.

        Returns:
            Human-readable time string (ms or s).
        """
        if seconds < 1:
            return f"{seconds * 1000:.1f}ms"
        return f"{seconds:.2f}s"

    @staticmethod
    def build_success_result(
        stdout: str,
        stderr: str,
        execution_time: float,
        generated_files: list[str] | None = None,
        container_id: str | None = None,
        result: object | None = None,
    ) -> ExecutionResult:
        """Build a successful execution result.

        Args:
            stdout: Standard output.
            stderr: Standard error output.
            execution_time: Execution time in seconds.
            generated_files: List of generated files.
            container_id: Container/session ID.
            result: Execution result object.

        Returns:
            ExecutionResult instance.
        """
        return ExecutionResult(
            success=True,
            result=result,
            stdout=stdout,
            stderr=stderr,
            error=None,
            execution_time=execution_time,
            container_id=container_id,
            generated_files=generated_files or [],
        )

    @staticmethod
    def build_error_result(
        error: Exception | str,
        execution_time: float,
        container_id: str | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> ExecutionResult:
        """Build an error execution result.

        Args:
            error: Exception or error message string.
            execution_time: Execution time in seconds.
            container_id: Container/session ID.
            stdout: Standard output.
            stderr: Standard error output.

        Returns:
            ExecutionResult instance.
        """
        if isinstance(error, Exception):
            error_msg = f"{type(error).__name__}: {error!s}"
        else:
            error_msg = str(error)

        short_error = extract_short_error(error_msg)

        return ExecutionResult(
            success=False,
            result=None,
            stdout=stdout,
            stderr=stderr or error_msg,
            error=short_error,
            execution_time=execution_time,
            container_id=container_id,
            generated_files=[],
        )

    @staticmethod
    def log_execution_start(executor_name: str, code_type: str, code: str) -> None:
        """Log execution start.

        Args:
            executor_name: Executor name.
            code_type: Code type (Python/Bash).
            code: Code to execute.
        """
        icon = ""

        display_code = code
        if "# === User Code ===" in code:
            display_code = code.split("# === User Code ===", 1)[1].strip()

        logger.info(
            f"{icon} [{executor_name}] Executing {code_type}:\n{display_code}\n--------------------------------"
        )

    @staticmethod
    def log_execution_success(executor_name: str, execution_time: float) -> None:
        """Log execution success.

        Args:
            executor_name: Executor name.
            execution_time: Execution time in seconds.
        """
        time_display = ExecutionHelper.format_execution_time(execution_time)
        logger.info(f" [{executor_name}] Execution succeeded ({time_display})")

    @staticmethod
    def log_execution_error(executor_name: str, error: str, execution_time: float) -> None:
        """Log execution failure.

        Args:
            executor_name: Executor name.
            error: Error message.
            execution_time: Execution time in seconds.
        """
        time_display = ExecutionHelper.format_execution_time(execution_time)
        logger.error(f" [{executor_name}] Execution failed ({time_display}): {error}")


_helper_instance = ExecutionHelper()


def get_execution_helper() -> ExecutionHelper:
    """Return the module-level ExecutionHelper singleton."""
    return _helper_instance
