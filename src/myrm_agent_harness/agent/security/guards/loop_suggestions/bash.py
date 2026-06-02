"""Bash tool suggestions for loop detection.

[INPUT]
- (none)

[OUTPUT]
- suggest_bash: Generate dynamic suggestion for bash_code_execute_tool wi...

[POS]
Bash tool suggestions for loop detection.
"""

from __future__ import annotations

from ..loop_guard_types import CallRecord, ErrorPattern, SuggestionPriority
from .core import analyze_error_pattern, get_tool_suggestion, prioritize_suggestions


def suggest_bash(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for bash_code_execute_tool with error analysis."""
    tried_commands: list[str] = []
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if "command" in call.args:
            tried_commands.append(str(call.args["command"])[:50])

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.FILE_NOT_FOUND in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "verify paths exist with 'ls'"))
        suggestions.append((SuggestionPriority.MEDIUM, "check current directory with 'pwd'"))
        suggestions.append((SuggestionPriority.LOW, "use absolute paths instead of relative"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.PERMISSION_DENIED in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "check permissions with 'ls -la'"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify you have execute permissions"))
        suggestions.append((SuggestionPriority.LOW, "try with 'sudo' if appropriate"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.INVALID_FORMAT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "verify command syntax"))
        suggestions.append((SuggestionPriority.MEDIUM, "check for typos"))
        suggestions.append((SuggestionPriority.LOW, "test command parts individually"))
        return prioritize_suggestions(suggestions, quality_scores)

    if len(tried_commands) > 2:
        suggestions.append((SuggestionPriority.HIGH, "verify paths exist with 'ls'"))
        suggestions.append((SuggestionPriority.MEDIUM, "check permissions with 'ls -la'"))
        suggestions.append((SuggestionPriority.MEDIUM, "confirm current directory with 'pwd'"))
        suggestions.append((SuggestionPriority.LOW, "break down into smaller steps"))
        return prioritize_suggestions(suggestions, quality_scores)

    return get_tool_suggestion("bash_code_execute_tool")
