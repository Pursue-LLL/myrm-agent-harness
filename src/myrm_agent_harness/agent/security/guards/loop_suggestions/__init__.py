"""Loop detection suggestion generation.

Routes tool-specific suggestion generation to specialized modules.

[INPUT]

[OUTPUT]
- generate_dynamic_suggestion(): context-aware suggestion string
- evaluate_success_level(): tool result success evaluation
- get_severity_level(): severity classification by streak count

[POS]
Suggestion generation subsystem for LoopGuard. Analyzes parameters and
error patterns from recent calls to generate targeted, priority-sorted
advice for 16 tools across 8 specialized modules.
"""

from __future__ import annotations

from collections.abc import Callable

from ..loop_guard_types import CallRecord
from .bash import suggest_bash
from .browser import suggest_browser_snapshot
from .core import (
    DEFAULT_SUGGESTION,
    TOOL_SUGGESTIONS,
    analyze_error_pattern,
    analyze_warning_level,
    evaluate_success_level,
    get_severity_level,
    get_tool_suggestion,
    is_result_successful,
    prioritize_suggestions,
)
from .file import suggest_file_read
from .memory import suggest_memory_recall
from .meta import suggest_skill_search, suggest_skill_select, suggest_spawn_subagent
from .web import suggest_web_search

__all__ = [
    "DEFAULT_SUGGESTION",
    "TOOL_SUGGESTIONS",
    "analyze_error_pattern",
    "analyze_warning_level",
    "evaluate_success_level",
    "generate_dynamic_suggestion",
    "get_severity_level",
    "get_tool_suggestion",
    "is_result_successful",
    "prioritize_suggestions",
]

_SuggestFn = Callable[[list[CallRecord], dict[str, float] | None], str]

_DYNAMIC_GENERATORS: dict[str, _SuggestFn] = {
    "memory_search_tool": suggest_memory_recall,
    "file_read_tool": suggest_file_read,
    "web_search_tool": suggest_web_search,
    "bash_code_execute_tool": suggest_bash,
    "delegate_task_tool": suggest_spawn_subagent,
    "browser_snapshot_tool": suggest_browser_snapshot,
    "skill_select_tool": suggest_skill_select,
    "discover_capability_tool": suggest_skill_search,
}


def generate_dynamic_suggestion(
    tool_name: str, recent_calls: list[CallRecord], quality_scores: dict[str, float] | None = None
) -> str:
    """Generate context-aware suggestions based on recent attempts.

    Analyzes parameters and error patterns from recent calls to provide
    targeted advice about what hasn't been tried yet.
    """
    relevant_calls = [c for c in recent_calls if c.tool_name == tool_name]

    if not relevant_calls:
        return get_tool_suggestion(tool_name)

    generator = _DYNAMIC_GENERATORS.get(tool_name)
    if generator is not None:
        return generator(relevant_calls, quality_scores)

    return get_tool_suggestion(tool_name)
