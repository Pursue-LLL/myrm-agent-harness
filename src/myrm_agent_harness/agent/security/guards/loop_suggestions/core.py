"""Core functions and static suggestions for loop detection.

[INPUT]
- (none)

[OUTPUT]
- get_severity_level: Determine severity level based on loop streak count.
- get_tool_suggestion: Get tool-specific suggestion or fallback to default.
- analyze_error_pattern: Analyze tool result content to identify common error patt...
- is_result_successful: Determine if a tool result indicates success (no error pa...
- analyze_warning_level: Analyze warning context to determine severity level.

[POS]
Core functions and static suggestions for loop detection.
"""

from __future__ import annotations

import re

from ..loop_guard_types import ErrorPattern, SuccessLevel, SuggestionPriority, ToolGroup, WarningLevel, get_tool_group

_TRIVIAL_TEST_PATTERNS: tuple[str, ...] = (
    "no tests ran",
    "collected 0 items",
    "no test files found",
    "no tests found",
    "tests: 0 total",
    "tests 0 passed",
    "running 0 tests",
    "0 passed; 0 failed",
    "ran 0 tests",
    "total tests: 0",
    "0 passing",
    "no test files",
    "0 passed",
)
_REAL_PASS_RE = re.compile(
    r"[1-9]\d*\s*(?:passed|passing)|^ok\s", re.MULTILINE,
)

TOOL_SUGGESTIONS: dict[str, str] = {
    "memory_recall_tool": (
        "Try: (1) different 'categories' filter (knowledge/event/preference/rule), "
        "(2) increase 'limit' to 10-15, (3) rephrase query with specific keywords, "
        "(4) use 'profile_key' for direct attribute access, "
        "or (5) the information may not be stored yet."
    ),
    "memory_save_tool": (
        "Check: (1) content is not empty, (2) category is correct, "
        "(3) importance value is reasonable (0.0-1.0), "
        "or (4) try a different memory type."
    ),
    "web_search_tool": (
        "Try: (1) different search keywords, (2) more specific query with context, "
        "(3) alternative phrasing, (4) combine with other tools (file_read, memory_recall), "
        "or (5) consider if web search is the right approach."
    ),
    "bash_code_execute_tool": (
        "Check: (1) command syntax is correct, (2) file/directory paths exist (use 'ls'), "
        "(3) file permissions (use 'ls -la'), (4) current working directory (use 'pwd'), "
        "or (5) try a different command to achieve the goal."
    ),
    "file_read_tool": (
        "Check: (1) file path is correct, (2) file exists (use bash 'ls'), "
        "(3) use 'glob_tool' to find the file, (4) current working directory, "
        "or (5) try reading a different file or use 'grep_tool' to search."
    ),
    "file_write_tool": (
        "Check: (1) file path is correct, (2) parent directory exists, "
        "(3) file permissions, (4) content is not empty, "
        "or (5) try a different file path."
    ),
    "file_edit_tool": (
        "Check: (1) file exists (use 'file_read_tool'), (2) search string is exact, "
        "(3) replacement string is different, (4) consider using 'file_write_tool' instead, "
        "or (5) verify the file content first."
    ),
    "glob_tool": (
        "Try: (1) different glob pattern, (2) broader pattern (e.g., '**/*.py'), "
        "(3) check if directory exists, (4) use 'bash' with 'find' command, "
        "or (5) verify the search path."
    ),
    "grep_tool": (
        "Try: (1) different search pattern, (2) case-insensitive search (-i flag), "
        "(3) broader file glob, (4) use 'bash' with 'rg' or 'grep' command, "
        "or (5) verify the search path."
    ),
    "web_fetch_tool": (
        "Check: (1) URL format is correct (include http:// or https://), "
        "(2) website is accessible (not 404/403), (3) network connectivity, "
        "(4) increase timeout if slow, (5) try 'web_search_tool' to find correct URL, "
        "or (6) check if page requires JavaScript (use browser_navigate_tool instead)."
    ),
    "browser_navigate_tool": (
        "Check: (1) URL format is correct (include http:// or https://), "
        "(2) website is accessible, (3) network connectivity, "
        "(4) wait_until parameter is appropriate (load/domcontentloaded/networkidle), "
        "or (5) try a different URL or use 'web_search_tool' to find it."
    ),
    "browser_interact_tool": (
        "Check: (1) use 'browser_snapshot_tool' to get current page structure and valid refs, "
        "(2) element ref exists on the page, (3) element is visible and interactable, "
        "(4) page has finished loading, (5) try a different action (click/type/fill), "
        "or (6) scroll to element first (use scrollIntoView)."
    ),
    "browser_snapshot_tool": (
        "Try: (1) wait longer for page to fully load (increase wait_until), "
        "(2) different selector or scope (try 'content', 'full', or specific selector), "
        "(3) use 'browser_inspect_tool' for quick metadata check first, "
        "(4) check if page has dynamic content (AJAX/SPA), "
        "(5) try 'browser_interact_tool' to trigger content load (scroll/click), "
        "or (6) verify page loaded successfully with 'browser_manage_tool' action='get_current_url'."
    ),
    "delegate_task_tool": (
        "Check: (1) subagent_type is valid (generalPurpose/explore/shell/browser-use/best-of-n-runner), "
        "(2) prompt is clear and specific, (3) timeout is reasonable (default 300s), "
        "(4) model selection is appropriate, (5) consider if subagent is needed or direct tools suffice, "
        "or (6) try a different subagent_type or break into smaller tasks."
    ),
    "skill_select_tool": (
        "Try: (1) different skill_id from the available list, "
        "(2) use 'discover_capability_tool' to find relevant skills, "
        "(3) verify skill parameters match task requirements, "
        "(4) check if skill description aligns with current goal, "
        "or (5) use direct tools (file_read, bash, web_search) instead of skills."
    ),
    "discover_capability_tool": (
        "Try: (1) different search keywords or phrasing, "
        "(2) broader query (remove specific technical terms), "
        "(3) more specific query (add context or domain), "
        "(4) use regex mode instead of bm25, (5) increase limit to see more results, "
        "or (6) check all available skills with 'skill_select_tool'."
    ),
}

DEFAULT_SUGGESTION = "consider a different approach or different parameters"


def get_severity_level(streak: int) -> tuple[str, str]:
    """Determine severity level based on loop streak count.

    Returns:
        (severity_label, emoji) tuple
    """
    if streak < 6:
        return "WARNING", ""
    elif streak < 10:
        return "ERROR", ""
    else:
        return "CRITICAL", ""


def get_tool_suggestion(tool_name: str) -> str:
    """Get tool-specific suggestion or fallback to default."""
    return TOOL_SUGGESTIONS.get(tool_name, DEFAULT_SUGGESTION)


def analyze_error_pattern(content: str) -> ErrorPattern:
    """Analyze tool result content to identify common error patterns."""
    if not content:
        return ErrorPattern.EMPTY_RESULT

    stripped = content.strip()
    if not stripped or stripped in ("[]", "{}", "null", "none"):
        return ErrorPattern.EMPTY_RESULT

    content_lower = content.lower()

    if "not found" in content_lower or "does not exist" in content_lower or "no such file" in content_lower:
        return ErrorPattern.FILE_NOT_FOUND

    if "permission denied" in content_lower or "access denied" in content_lower or "forbidden" in content_lower:
        return ErrorPattern.PERMISSION_DENIED

    if "timeout" in content_lower or "timed out" in content_lower or "deadline exceeded" in content_lower:
        return ErrorPattern.TIMEOUT

    if (
        "connection" in content_lower
        or "network" in content_lower
        or "unreachable" in content_lower
        or "refused" in content_lower
    ):
        return ErrorPattern.NETWORK_ERROR

    if (
        "invalid" in content_lower
        or "malformed" in content_lower
        or "syntax error" in content_lower
        or "parse error" in content_lower
    ):
        return ErrorPattern.INVALID_FORMAT

    if content_lower.startswith("error:") or content_lower.startswith("error "):
        return ErrorPattern.INVALID_FORMAT

    if "error:" in content_lower or "exception:" in content_lower:
        return ErrorPattern.INVALID_FORMAT

    if re.search(
        r"\b(?:Name|Type|Value|Key|Index|Attribute|Import|Module|Runtime|OS|IO|"
        r"Syntax|Indentation|Lookup|Zero|Overflow|Assertion|FileNotFound|"
        r"FileExists|Permission|IsADirectory|NotADirectory)Error\b",
        content,
    ):
        return ErrorPattern.INVALID_FORMAT

    return ErrorPattern.UNKNOWN


def is_result_successful(content: str) -> bool:
    """Determine if a tool result indicates success (no error patterns)."""
    if not content:
        return False

    error_pattern = analyze_error_pattern(content)
    return error_pattern == ErrorPattern.UNKNOWN


def analyze_warning_level(content: str) -> WarningLevel:
    """Analyze warning context to determine severity level."""
    if not content:
        return WarningLevel.NO_WARN

    content_lower = content.lower()

    match = re.search(r"\b(warning|warn)\b", content_lower)

    if not match:
        return WarningLevel.NO_WARN

    warn_idx = match.start()

    context_start = max(0, warn_idx - 50)
    context_end = min(len(content_lower), warn_idx + 100)
    context = content_lower[context_start:context_end]

    critical_keywords = ["error", "fail", "critical", "fatal", "exception"]
    if any(kw in context for kw in critical_keywords):
        return WarningLevel.CRITICAL_WARN

    info_keywords = ["info", "note", "hint", "tip", "this is fine", "ok", "success"]
    if any(kw in context for kw in info_keywords):
        return WarningLevel.INFO_WARN

    deprecated_keywords = ["deprecated", "obsolete", "legacy", "old"]
    if any(kw in context for kw in deprecated_keywords):
        return WarningLevel.NORMAL_WARN

    return WarningLevel.NORMAL_WARN


def evaluate_success_level(tool_name: str, result_content: str) -> SuccessLevel:
    """Evaluate success level with tool-specific criteria."""
    if not result_content:
        return SuccessLevel.FAILURE

    error_pattern = analyze_error_pattern(result_content)
    tool_group = get_tool_group(tool_name)
    content_lower = result_content.lower()

    if error_pattern == ErrorPattern.EMPTY_RESULT:
        if tool_group in (ToolGroup.SEARCH, ToolGroup.MEMORY):
            return SuccessLevel.EMPTY_OK
        return SuccessLevel.FAILURE

    if error_pattern != ErrorPattern.UNKNOWN:
        return SuccessLevel.FAILURE

    if tool_group == ToolGroup.BROWSER:
        if "404" in content_lower or "403" in content_lower or "not found" in content_lower:
            return SuccessLevel.FAILURE
        if "200" in content_lower and len(result_content.strip()) < 50:
            return SuccessLevel.EMPTY_OK

    if tool_group == ToolGroup.WRITE and ("partial" in content_lower or "incomplete" in content_lower):
        return SuccessLevel.PARTIAL_SUCCESS

    if (
        tool_group == ToolGroup.EXECUTE
        and ("exit_code" in content_lower or "exit code" in content_lower)
        and ("exit_code: 0" in content_lower or "exit code: 0" in content_lower)
        and "stderr" in content_lower
    ):
        return SuccessLevel.PARTIAL_SUCCESS

    warning_level = analyze_warning_level(result_content)

    if warning_level == WarningLevel.CRITICAL_WARN:
        return SuccessLevel.FAILURE
    elif warning_level == WarningLevel.NORMAL_WARN:
        return SuccessLevel.PARTIAL_SUCCESS
    elif warning_level == WarningLevel.INFO_WARN:
        return SuccessLevel.FULL_SUCCESS

    if tool_group == ToolGroup.EXECUTE and any(
        pat in content_lower for pat in _TRIVIAL_TEST_PATTERNS
    ) and not _REAL_PASS_RE.search(content_lower):
        return SuccessLevel.EMPTY_OK

    return SuccessLevel.FULL_SUCCESS


def prioritize_suggestions(
    suggestions: list[tuple[SuggestionPriority, str]], quality_scores: dict[str, float] | None = None
) -> str:
    """Format suggestions with priority indicators, adjusted by quality scores."""
    if not suggestions:
        return DEFAULT_SUGGESTION

    if quality_scores:
        adjusted_suggestions = []
        for priority, text in suggestions:
            quality = quality_scores.get(text, 0.0)

            if quality < -0.3:
                continue
            elif quality > 0.5 and priority == SuggestionPriority.MEDIUM:
                priority = SuggestionPriority.HIGH
            elif quality < 0.0 and priority == SuggestionPriority.HIGH:
                priority = SuggestionPriority.MEDIUM

            adjusted_suggestions.append((priority, text))

        suggestions = adjusted_suggestions if adjusted_suggestions else suggestions

    suggestions.sort(key=lambda x: ["high", "medium", "low"].index(x[0].value))

    formatted = []
    for priority, text in suggestions:
        formatted.append(f"{priority.emoji} {text}")

    return " | ".join(formatted)
