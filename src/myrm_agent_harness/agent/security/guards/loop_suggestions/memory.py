"""Memory tool suggestions for loop detection.

[INPUT]
- (none)

[OUTPUT]
- suggest_memory_recall: Generate dynamic suggestion for memory_recall based on tr...

[POS]
Memory tool suggestions for loop detection.
"""

from __future__ import annotations

import contextlib

from ..loop_guard_types import CallRecord, ErrorPattern, SuggestionPriority
from .core import analyze_error_pattern, prioritize_suggestions


def suggest_memory_recall(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for memory_recall based on tried parameters and errors."""
    tried_categories: set[str] = set()
    tried_limits: set[int] = set()
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        args = call.args
        if "categories" in args:
            cats = args["categories"]
            if isinstance(cats, list):
                tried_categories.update(cats)
            elif isinstance(cats, str):
                tried_categories.add(cats)
        if "limit" in args:
            with contextlib.suppress(ValueError, TypeError):
                tried_limits.add(int(args["limit"]))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.EMPTY_RESULT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "use 'profile_key' for direct attribute access"))
        suggestions.append((SuggestionPriority.MEDIUM, "rephrase query with different keywords"))
        suggestions.append((SuggestionPriority.LOW, "the information may not be stored yet"))
        return prioritize_suggestions(suggestions, quality_scores)

    all_categories = {"knowledge", "event", "preference", "rule"}
    untried_categories = all_categories - tried_categories

    if untried_categories:
        cats_str = "/".join(sorted(untried_categories))
        suggestions.append((SuggestionPriority.HIGH, f"try untried categories: {cats_str}"))

    if tried_limits and max(tried_limits) < 15:
        suggestions.append((SuggestionPriority.MEDIUM, f"increase limit (tried: {max(tried_limits)}, try 15+)"))

    if not suggestions:
        suggestions.append((SuggestionPriority.MEDIUM, "try 'profile_key' for direct attribute access"))
        suggestions.append((SuggestionPriority.LOW, "the information may not be stored yet"))

    return prioritize_suggestions(suggestions, quality_scores)
