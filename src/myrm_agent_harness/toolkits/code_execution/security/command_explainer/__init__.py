"""Shell command span extraction for approval UI highlighting."""

from myrm_agent_harness.toolkits.code_execution.security.command_explainer.extract import (
    MAX_COMMAND_SPAN_SOURCE_CHARS,
    build_shell_approval_fields,
    extract_command_spans,
    extract_shell_command_text,
    is_shell_approval_tool,
)
from myrm_agent_harness.toolkits.code_execution.security.command_explainer.types import (
    CommandSpan,
    SpanRiskLevel,
)

__all__ = [
    "CommandSpan",
    "MAX_COMMAND_SPAN_SOURCE_CHARS",
    "SpanRiskLevel",
    "build_shell_approval_fields",
    "extract_command_spans",
]
