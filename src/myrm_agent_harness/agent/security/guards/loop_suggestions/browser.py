"""Browser tool suggestions for loop detection.

[INPUT]
- (none)

[OUTPUT]
- suggest_browser_snapshot: Generate dynamic suggestion for browser_snapshot with err...

[POS]
Browser tool suggestions for loop detection.
"""

from __future__ import annotations

from ..loop_guard_types import CallRecord, ErrorPattern, SuggestionPriority
from .core import analyze_error_pattern, prioritize_suggestions


def suggest_browser_snapshot(recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None) -> str:
    """Generate dynamic suggestion for browser_snapshot with error analysis."""
    tried_scopes: set[str] = set()
    error_patterns: list[ErrorPattern] = []

    for call in recent_calls:
        if call.args.get("scope"):
            tried_scopes.add(str(call.args["scope"]))

        if call.result_content:
            error_patterns.append(analyze_error_pattern(call.result_content))

    suggestions: list[tuple[SuggestionPriority, str]] = []

    if ErrorPattern.TIMEOUT in error_patterns:
        suggestions.append((SuggestionPriority.HIGH, "wait longer for page to fully load (increase wait_until)"))
        suggestions.append((SuggestionPriority.MEDIUM, "check if page has dynamic content (AJAX/SPA)"))
        suggestions.append((SuggestionPriority.LOW, "try 'browser_inspect' first"))
        return prioritize_suggestions(suggestions, quality_scores)

    if ErrorPattern.EMPTY_RESULT in error_patterns:
        suggestions.append(
            (SuggestionPriority.HIGH, "verify page loaded successfully with 'browser_manage' action='get_current_url'")
        )
        suggestions.append((SuggestionPriority.MEDIUM, "try 'browser_interact' to trigger content load (scroll/click)"))
        suggestions.append((SuggestionPriority.LOW, "use different selector or scope"))
        return prioritize_suggestions(suggestions, quality_scores)

    all_scopes = {"content", "full", "metadata"}
    untried_scopes = all_scopes - tried_scopes

    if untried_scopes and len(tried_scopes) >= 1:
        scopes_str = "/".join(sorted(untried_scopes))
        suggestions.append((SuggestionPriority.HIGH, f"try different scope: {scopes_str}"))

    if len(recent_calls) > 2:
        suggestions.append((SuggestionPriority.MEDIUM, "use 'browser_inspect' for quick metadata check"))
        suggestions.append((SuggestionPriority.LOW, "verify page has finished loading"))

    if not suggestions:
        suggestions.append((SuggestionPriority.MEDIUM, "wait longer for page load"))
        suggestions.append((SuggestionPriority.LOW, "try different selector"))

    return prioritize_suggestions(suggestions, quality_scores)
