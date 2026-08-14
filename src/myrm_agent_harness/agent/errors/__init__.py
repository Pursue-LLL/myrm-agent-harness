"""Agent execution errors with unified diagnostics.

Provides base classes for all tool execution errors with structured
diagnostic information including execution phase, command context,
and intelligently truncated output previews.
"""

from .agent_errors import AgentBusyError
from .diagnostics import DiagnosticResult, ErrorContext, LLMErrorDiagnostic
from .fault_side import (
    FaultSide,
    classify_diagnostic_fault_side,
    classify_fault_side,
    classify_llm_fault_side,
    classify_tool_fault_side,
)
from .tool_error_category import ToolErrorCategory
from .tool_execution_error import ExecutionPhase, ToolExecutionError

__all__ = [
    "AgentBusyError",
    "DiagnosticResult",
    "ErrorContext",
    "ExecutionPhase",
    "FaultSide",
    "LLMErrorDiagnostic",
    "ToolErrorCategory",
    "ToolExecutionError",
    "classify_diagnostic_fault_side",
    "classify_fault_side",
    "classify_llm_fault_side",
    "classify_tool_fault_side",
]
