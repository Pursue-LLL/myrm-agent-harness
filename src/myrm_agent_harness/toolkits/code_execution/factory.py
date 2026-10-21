"""Code executor factory.

Creates LocalExecutor for code execution within the current container.


[INPUT]
- code_execution.config::ExecutionConfig, get_execution_config (POS: code execution configuration)
- code_execution.executors.base::CodeExecutor (POS: abstract code executor interface)

[OUTPUT]
- create_executor(): factory function that creates a CodeExecutor (LocalExecutor) instance

[POS]
Code executor factory. Creates LocalExecutor for in-container code execution based on configuration.
"""

import logging

from myrm_agent_harness.toolkits.code_execution.config import (
    ExecutionConfig,
    get_execution_config,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)


def create_executor(
    config: ExecutionConfig | None = None,
) -> CodeExecutor:
    """Create a code executor.

    Returns LocalExecutor for executing code in the current container.

    Args:
        config: Execution configuration (uses global config if None).

    Returns:
        LocalExecutor instance.
    """
    if config is None:
        config = get_execution_config()

    from myrm_agent_harness.toolkits.code_execution.executors.local import LocalExecutor

    logger.info("Creating LocalExecutor")
    return LocalExecutor(config)
