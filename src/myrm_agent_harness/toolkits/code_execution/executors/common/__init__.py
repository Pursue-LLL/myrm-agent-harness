"""Common executor components.

Shared utilities, service classes, and decorators for code executors.

Categories:
- Utilities: executor_utils, wrapper_script, subprocess_guard
- Services: VenvManager, CommandRewriter, GeneratedFilesScanner, ExecutionHelper
- Decorators: handle_execution_error
"""

from myrm_agent_harness.toolkits.code_execution.executors.common.command_rewriter import CommandRewriter
from myrm_agent_harness.toolkits.code_execution.executors.common.error_handler import handle_execution_error
from myrm_agent_harness.toolkits.code_execution.executors.common.execution_helper import (
    ExecutionHelper,
    get_execution_helper,
)
from myrm_agent_harness.toolkits.code_execution.executors.common.executor_utils import (
    IGNORED_ARTIFACT_PATTERNS,
    MAX_OUTPUT_CHARS,
    extract_short_error,
    should_filter_skill_resource,
    should_ignore_artifact,
    truncate_output,
)
from myrm_agent_harness.toolkits.code_execution.executors.common.exit_classify import classify_exit_code
from myrm_agent_harness.toolkits.code_execution.executors.common.file_scanner import (
    GeneratedFilesScanner,
    LocalFilesScanner,
)
from myrm_agent_harness.toolkits.code_execution.executors.common.subprocess_guard import (
    SubprocessTimeoutError,
    guarded_communicate,
)
from myrm_agent_harness.toolkits.code_execution.executors.common.venv_manager import VenvManager
from myrm_agent_harness.toolkits.code_execution.executors.common.wrapper_script import (
    generate_wrapper_script,
    parse_execution_output,
)

__all__ = [
    # Utilities
    "IGNORED_ARTIFACT_PATTERNS",
    "MAX_OUTPUT_CHARS",
    "CommandRewriter",
    "ExecutionHelper",
    "GeneratedFilesScanner",
    "LocalFilesScanner",
    # Exceptions
    "SubprocessTimeoutError",
    # Services
    "VenvManager",
    "classify_exit_code",
    "extract_short_error",
    "generate_wrapper_script",
    "get_execution_helper",
    "guarded_communicate",
    # Decorators
    "handle_execution_error",
    "parse_execution_output",
    "should_filter_skill_resource",
    "should_ignore_artifact",
    "truncate_output",
]
