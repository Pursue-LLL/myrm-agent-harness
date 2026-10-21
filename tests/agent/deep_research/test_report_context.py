"""Report-context assembly tests for ``helpers.format_research_context`` and ``compact_orch_messages``."""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.deep_research.helpers import (
    compact_orch_messages,
    format_research_context,
)

_SEPARATOR = "\n\n---\n\n"
_TRUNCATION_MARKER = "[Truncated — prioritizing most recent research]"


def _results(count: int, body_chars: int) -> list[dict[str, object]]:
    return [{"task": f"task-{i}", "result": f"r{i}-" + "x" * body_chars} for i in range(1, count + 1)]


def test_empty_results_return_empty_context() -> None:
    assert format_research_context([], max_chars=1_000) == ""


def test_within_budget_numbers_tasks_in_given_order() -> None:
    context = format_research_context(_results(3, 5), max_chars=10_000)

    assert context == _SEPARATOR.join(f"## Research Task {i}: task-{i}\n\nr{i}-xxxxx" for i in (1, 2, 3))


def test_missing_task_and_result_use_placeholders() -> None:
    context = format_research_context([{}], max_chars=1_000)

    assert context == "## Research Task 1: Unknown task\n\nNo result"


def test_over_budget_keeps_newest_whole_and_drops_oldest() -> None:
    results = _results(4, 300)
    newest = f"## Research Task 4: task-4\n\n{results[3]['result']}"
    budget = 2 * (len(newest) + len(_SEPARATOR))

    context = format_research_context(results, max_chars=budget)

    assert len(context) <= budget
    assert context.endswith(newest)
    assert "Research Task 3: task-3" in context
    assert "Research Task 1" not in context
    assert context.index("Research Task 3") < context.index("Research Task 4")


def test_over_budget_truncates_next_older_result_with_marker() -> None:
    results = _results(2, 400)
    newest = f"## Research Task 2: task-2\n\n{results[1]['result']}"
    budget = len(newest) + len(_SEPARATOR) + 200

    context = format_research_context(results, max_chars=budget)

    older, kept_newest = context.split(_SEPARATOR, 1)
    assert kept_newest == newest
    assert older.startswith("## Research Task 1: task-1")
    assert older.endswith(_TRUNCATION_MARKER)
    assert len(context) <= budget


def test_budget_too_small_for_any_result_returns_empty_context() -> None:
    assert format_research_context(_results(2, 400), max_chars=50) == ""


def test_compaction_replaces_old_tool_results_and_keeps_recent_messages() -> None:
    messages: list[BaseMessage] = [SystemMessage(content="system")]
    for i in range(20):
        messages.append(ToolMessage(content=f"head-{i}\n" + "y" * 20_000, tool_call_id=f"tc-{i}"))
    messages.append(HumanMessage(content="latest"))
    recent_before = [m.content for m in messages[-12:]]

    compact_orch_messages(messages)

    compacted = [m for m in messages if isinstance(m, ToolMessage) and "compacted" in str(m.content)]
    assert compacted
    assert all("(full result available in report context)" in str(m.content) for m in compacted)
    assert messages[0].content == "system"
    assert [m.content for m in messages[-12:]] == recent_before
