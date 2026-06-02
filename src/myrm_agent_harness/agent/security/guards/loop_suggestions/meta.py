"""Meta tool suggestions (subagent, skill) for loop detection.

[INPUT]
- (none)

[OUTPUT]
- suggest_spawn_subagent: Generate dynamic suggestion for delegate_task with error ...
- suggest_skill_select: Generate dynamic suggestion for skill_select_tool with er...
- suggest_skill_search: Generate dynamic suggestion for discover_capability with er...

[POS]
Meta tool suggestions (subagent, skill) for loop detection.
"""

from __future__ import annotations

from ..loop_guard_types import CallRecord, ErrorPattern, SuggestionPriority
from .core import analyze_error_pattern, prioritize_suggestions


def suggest_spawn_subagent(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for delegate_task with error analysis."""
    tried_types: set[str] = set()
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if "subagent_type" in call.args:
            tried_types.add(str(call.args["subagent_type"]))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.TIMEOUT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "increase timeout or break task into smaller subtasks"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify task is achievable within time limit"))
        suggestions.append((SuggestionPriority.LOW, "try a different subagent_type"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.INVALID_FORMAT in error_patterns or ErrorPattern.PERMISSION_DENIED in error_patterns:
        suggestions.append(
            (
                SuggestionPriority.HIGH,
                "verify subagent_type is valid (generalPurpose/explore/shell/browser-use/best-of-n-runner)",
            )
        )
        suggestions.append((SuggestionPriority.MEDIUM, "check prompt clarity and specificity"))
        suggestions.append((SuggestionPriority.LOW, "try with different model"))
        return prioritize_suggestions(suggestions, quality_scores)

    all_types = {"generalPurpose", "explore", "shell", "browser-use", "best-of-n-runner"}
    untried_types = all_types - tried_types

    if untried_types and len(tried_types) >= 2:
        types_str = "/".join(sorted(untried_types)[:3])
        suggestions.append((SuggestionPriority.HIGH, f"try different subagent_type: {types_str}"))

    if len(recent_calls) > 2:
        suggestions.append((SuggestionPriority.HIGH, "consider if subagent is needed or use direct tools instead"))
        suggestions.append((SuggestionPriority.MEDIUM, "break task into smaller, more specific subtasks"))

    if not suggestions:
        suggestions.append((SuggestionPriority.MEDIUM, "verify prompt is clear and specific"))
        suggestions.append((SuggestionPriority.LOW, "check timeout and model settings"))

    return prioritize_suggestions(suggestions, quality_scores)


def suggest_skill_select(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for skill_select_tool with error analysis."""
    tried_skills: set[str] = set()
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if "skill_names" in call.args:
            names = call.args["skill_names"]
            if isinstance(names, list):
                tried_skills.update(str(n) for n in names)
            else:
                tried_skills.add(str(names))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.FILE_NOT_FOUND in error_patterns or ErrorPattern.INVALID_FORMAT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "use 'discover_capability_tool' to find available skills"))
        suggestions.append((SuggestionPriority.MEDIUM, "verify skill_id exists in the skill registry"))
        suggestions.append((SuggestionPriority.LOW, "check skill parameters match requirements"))
        return prioritize_suggestions(suggestions, quality_scores)

    if len(tried_skills) > 2:
        suggestions.append(
            (SuggestionPriority.HIGH, "consider using direct tools (file_read, bash, web_search) instead")
        )
        suggestions.append((SuggestionPriority.MEDIUM, "verify skill description aligns with current goal"))
        suggestions.append((SuggestionPriority.LOW, "use 'discover_capability_tool' to find alternative skills"))
        return prioritize_suggestions(suggestions, quality_scores)

    if not suggestions:
        suggestions.append((SuggestionPriority.MEDIUM, "use 'discover_capability_tool' to find relevant skills"))
        suggestions.append((SuggestionPriority.LOW, "verify skill parameters"))

    return prioritize_suggestions(suggestions, quality_scores)


def suggest_skill_search(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for discover_capability with error analysis."""
    tried_queries: list[str] = []
    tried_modes: set[str] = set()
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if "query" in call.args:
            tried_queries.append(str(call.args["query"]))
        if "mode" in call.args:
            tried_modes.add(str(call.args["mode"]))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.EMPTY_RESULT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "try broader query (remove specific technical terms)"))
        suggestions.append((SuggestionPriority.MEDIUM, "use 'skill_select_tool' to browse all skills"))
        suggestions.append((SuggestionPriority.LOW, "the skill may not exist yet"))
        return prioritize_suggestions(suggestions, quality_scores)

    if "regex" not in tried_modes and "bm25" in tried_modes:
        suggestions.append((SuggestionPriority.HIGH, "try mode='regex' for pattern matching"))

    if len(tried_queries) > 2:
        suggestions.append((SuggestionPriority.HIGH, "use 'skill_select_tool' to browse all available skills"))
        suggestions.append((SuggestionPriority.MEDIUM, "more specific query with domain/context"))
        suggestions.append((SuggestionPriority.LOW, "consider using direct tools instead"))
        return prioritize_suggestions(suggestions, quality_scores)

    if not suggestions:
        suggestions.append((SuggestionPriority.MEDIUM, "try different keywords or phrasing"))
        suggestions.append((SuggestionPriority.LOW, "increase limit to see more results"))

    return prioritize_suggestions(suggestions, quality_scores)
