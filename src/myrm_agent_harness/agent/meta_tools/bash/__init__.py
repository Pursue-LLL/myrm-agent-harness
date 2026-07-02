"""Bash tool module.

Provides persistent Bash session with DI-based execution orchestration.
See _ARCH.md for file index and module structure.
"""

from .bash_executor import BashExecutionError, BashExecutor
from .bash_process_tools import (
    create_bash_process_kill_tool,
    create_bash_process_list_tool,
    create_bash_process_output_tool,
)
from .bash_code_execute_tool import create_bash_code_execute_tool
from .command_classifier import CommandClassifier, CommandType, RiskLevel
from .sensitive_parameter_redactor import SensitiveParameterRedactor

__all__ = [
    "BashExecutionError",
    "BashExecutor",
    "CommandClassifier",
    "CommandType",
    "RiskLevel",
    "SensitiveParameterRedactor",
    "create_bash_process_kill_tool",
    "create_bash_process_list_tool",
    "create_bash_process_output_tool",
    "create_bash_code_execute_tool",
]
