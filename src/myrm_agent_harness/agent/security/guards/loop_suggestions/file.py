"""File tool suggestions for loop detection.

[INPUT]
- (none)

[OUTPUT]
- suggest_file_read: Generate dynamic suggestion for file_read_tool with error...

[POS]
File tool suggestions for loop detection.
"""

from __future__ import annotations

from ..loop_guard_types import CallRecord, ErrorPattern, SuggestionPriority
from .core import analyze_error_pattern, get_tool_suggestion, prioritize_suggestions


def suggest_file_read(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for file_read_tool with error analysis."""
    tried_paths: set[str] = set()
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if "path" in call.args:
            tried_paths.add(str(call.args["path"]))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.FILE_NOT_FOUND in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "use 'glob_tool' to find the correct path"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify parent directory exists with bash 'ls'"))
        suggestions.append((SuggestionPriority.LOW, "check current working directory with 'pwd'"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.PERMISSION_DENIED in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "check file permissions with 'ls -la'"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify you have read access"))
        suggestions.append((SuggestionPriority.LOW, "try a different file path"))
        return prioritize_suggestions(suggestions, quality_scores)

    if len(tried_paths) > 2:
        suggestions.append((SuggestionPriority.HIGH, "use 'glob_tool' to find the file"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify parent directory exists"))
        suggestions.append((SuggestionPriority.LOW, "check current working directory with bash 'pwd'"))
        return prioritize_suggestions(suggestions, quality_scores)

    return get_tool_suggestion("file_read_tool")
