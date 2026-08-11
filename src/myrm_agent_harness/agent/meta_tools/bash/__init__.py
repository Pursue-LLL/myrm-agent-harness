"""Bash tool module.

Provides persistent Bash session with DI-based execution orchestration.
See _ARCH.md for file index and module structure.
"""

from .bash_code_execute_tool import create_bash_code_execute_tool
from ._executor.executor import BashExecutionError, BashExecutor
from .bash_process_tools import BASH_PROCESS_TOOL_NAME, create_bash_process_tool

__all__ = [
    "BASH_PROCESS_TOOL_NAME",
    "BashExecutionError",
    "BashExecutor",
    "create_bash_code_execute_tool",
    "create_bash_process_tool",
]
