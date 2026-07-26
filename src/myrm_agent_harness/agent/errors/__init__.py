"""Agent execution errors with unified diagnostics.

Provides base classes for all tool execution errors with structured
diagnostic information including execution phase, command context,
and intelligently truncated output previews.
"""

from .agent_errors import AgentBusyError
from .diagnostics import DiagnosticResult, ErrorContext, LLMErrorDiagnostic
from .tool_error_category import ToolErrorCategory
from .tool_execution_error import ExecutionPhase, ToolExecutionError

__all__ = [
    "AgentBusyError",
    "DiagnosticResult",
    "ErrorContext",
    "ExecutionPhase",
    "LLMErrorDiagnostic",
    "ToolErrorCategory",
    "ToolExecutionError",
]
