"""Agent execution errors with unified diagnostics.

Provides the agent run-loop exceptions, structured LLM and tool error
diagnostics, and deterministic fault-side attribution.
"""

from myrm_agent_harness.utils.errors import ToolErrorCategory

from .agent_errors import (
    AgentBusyError,
    RunawayCircuitBreakException,
    ToolStuckException,
)
from .diagnostics import DiagnosticResult, ErrorContext, LLMErrorDiagnostic
from .fault_side import (
    FaultSide,
    classify_diagnostic_fault_side,
    classify_fault_side,
    classify_llm_fault_side,
    classify_tool_fault_side,
)
from .operator_error_sanitizer import (
    OperatorErrorCode,
    OperatorErrorSanitizer,
    SanitizedOperatorError,
)

__all__ = [
    "AgentBusyError",
    "DiagnosticResult",
    "ErrorContext",
    "FaultSide",
    "LLMErrorDiagnostic",
    "OperatorErrorCode",
    "OperatorErrorSanitizer",
    "RunawayCircuitBreakException",
    "SanitizedOperatorError",
    "ToolErrorCategory",
    "ToolStuckException",
    "classify_diagnostic_fault_side",
    "classify_fault_side",
    "classify_llm_fault_side",
    "classify_tool_fault_side",
]
