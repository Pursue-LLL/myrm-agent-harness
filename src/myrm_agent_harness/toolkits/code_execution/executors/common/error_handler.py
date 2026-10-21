"""Execution error handling decorator.

Provides unified exception handling for executors, reducing boilerplate.

[INPUT]
- toolkits.code_execution.executors.base::ExecutionContext, (POS: Code executor base classes.)

[OUTPUT]
- handle_execution_error: Decorator for unified execution error handling.

[POS]
Execution error handling decorator.
"""

import logging
import time
from collections.abc import Callable
from functools import wraps

from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext, ExecutionResult
from myrm_agent_harness.toolkits.code_execution.executors.common.execution_helper import ExecutionHelper

logger = logging.getLogger(__name__)


def handle_execution_error(executor_name: str) -> Callable:
    """Decorator for unified execution error handling.

    Automatically computes execution time, logs errors, and builds
    standardized error results.

    Args:
        executor_name: Executor name for logging.

    Returns:
        Decorator function.

    Example:
        ```python
        @handle_execution_error("LocalExecutor")
        async def execute(self, context: ExecutionContext) -> ExecutionResult:
            ...
        ```
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, context: ExecutionContext) -> ExecutionResult:
            start_time = time.time()
            try:
                return await func(self, context)
            except Exception as e:
                execution_time = time.time() - start_time
                error_msg = f"{type(e).__name__}: {e!s}"

                ExecutionHelper.log_execution_error(executor_name, error_msg, execution_time)

                return ExecutionHelper.build_error_result(
                    error=e,
                    execution_time=execution_time,
                    container_id=context.session_id,
                )

        return wrapper

    return decorator
