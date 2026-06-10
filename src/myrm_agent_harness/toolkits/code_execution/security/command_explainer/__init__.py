"""Shell command span extraction and human-readable explanations for approval UI."""

from myrm_agent_harness.toolkits.code_execution.security.command_explainer.extract import (
    MAX_COMMAND_SPAN_SOURCE_CHARS,
    build_shell_approval_fields,
    extract_command_spans,
    extract_shell_command_text,
    is_shell_approval_tool,
)
from myrm_agent_harness.toolkits.code_execution.security.command_explainer.humanize import (
    humanize_command,
)
from myrm_agent_harness.toolkits.code_execution.security.command_explainer.types import (
    CommandSpan,
    SpanRiskLevel,
)

__all__ = [
    "MAX_COMMAND_SPAN_SOURCE_CHARS",
    "CommandSpan",
    "SpanRiskLevel",
    "build_shell_approval_fields",
    "extract_command_spans",
    "humanize_command",
]
