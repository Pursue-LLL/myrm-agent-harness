"""Web tool suggestions for loop detection.

[INPUT]
- (none)

[OUTPUT]
- suggest_web_search: Generate dynamic suggestion for web_search_tool with erro...

[POS]
Web tool suggestions for loop detection.
"""

from __future__ import annotations

from ..loop_guard_types import CallRecord, ErrorPattern, SuggestionPriority
from .core import analyze_error_pattern, get_tool_suggestion, prioritize_suggestions


def suggest_web_search(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for web_search_tool with error analysis."""
    tried_queries: list[str] = []
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if "questions" in call.args:
            qs = call.args["questions"]
            if isinstance(qs, list) and qs:
                tried_queries.append(str(qs[0]))
        elif "query" in call.args:
            tried_queries.append(str(call.args["query"]))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.NETWORK_ERROR in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "check network connectivity"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify proxy settings"))
        suggestions.append((SuggestionPriority.LOW, "try again later"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.TIMEOUT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "use more specific keywords"))
        suggestions.append((SuggestionPriority.MEDIUM, "break into smaller queries"))
        suggestions.append((SuggestionPriority.LOW, "check network connectivity"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.EMPTY_RESULT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "broader or alternative keywords"))
        suggestions.append((SuggestionPriority.MEDIUM, "combine with other tools (file_read, memory_recall)"))
        suggestions.append((SuggestionPriority.LOW, "consider if web search is the right approach"))
        return prioritize_suggestions(suggestions, quality_scores)

    if len(tried_queries) > 2:
        suggestions.append((SuggestionPriority.HIGH, "combine with other tools for context"))
        suggestions.append((SuggestionPriority.MEDIUM, "more specific query with domain/technology names"))
        suggestions.append((SuggestionPriority.LOW, "consider if web search is the right approach"))
        return prioritize_suggestions(suggestions, quality_scores)

    return get_tool_suggestion("web_search_tool")
