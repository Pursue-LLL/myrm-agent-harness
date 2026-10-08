# [INPUT]: DeterministicLedgerCompiler, DeterministicRuntimeStateLedgerInjectionSuite, LedgerInjectionResult, LedgerUpdatePolicy, QuotaConstraint, RuntimeLedgerConfig, RuntimeStateSnapshot, TailLedgerInjector, TodoProgress
# [OUTPUT]: test_deterministic_runtime_state_ledger_suite.py
# [POS]: tests/agent/context_management/test_deterministic_runtime_state_ledger_suite.py

"""Comprehensive unit tests for DeterministicRuntimeStateLedgerInjectionSuite.

Verifies:
1. Pure mathematical quota constraint calculations and exhaustion states.
2. Tool call extraction and counting directly from message records without LLM calls.
3. Priority-based tag condensation within strict token budgets.
4. Prompt cache preservation: system prompt prefix remains 100% immutable while tag updates at tail.
5. REPLACE policy replacing existing <agent_status> tags vs. APPEND policy appending.
6. End-to-end facade orchestration and violation warning generation.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.runtime_ledger import (
    DeterministicLedgerCompiler,
    DeterministicRuntimeStateLedgerInjectionSuite,
    LedgerInjectionResult,
    LedgerUpdatePolicy,
    QuotaConstraint,
    RuntimeLedgerConfig,
    RuntimeStateSnapshot,
    TailLedgerInjector,
    TodoProgress,
)


def test_quota_constraint_properties() -> None:
    """Verifies quota calculation and exhaustion detection."""
    normal_q = QuotaConstraint(name="phone_call", max_limit=3, used_count=1, unit="calls")
    assert normal_q.remaining == 2
    assert not normal_q.is_exhausted

    exhausted_q = QuotaConstraint(name="web_search", max_limit=5, used_count=5, unit="queries")
    assert exhausted_q.remaining == 0
    assert exhausted_q.is_exhausted

    over_q = QuotaConstraint(name="api_mutation", max_limit=2, used_count=3, unit="ops")
    assert over_q.remaining == 0
    assert over_q.is_exhausted


def test_deterministic_ledger_compiler_counting() -> None:
    """Verifies deterministic counting from simulated message records."""
    compiler = DeterministicLedgerCompiler()

    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Fetch user info and search news"},
        {
            "role": "assistant",
            "tool_calls": [
                {"name": "fetch_user", "arguments": "{}"},
                {"function": {"name": "search_news"}, "id": "call_123"},
            ],
        },
        {"role": "tool", "content": "user data"},
        {
            "role": "assistant",
            "tool_calls": [
                {"name": "fetch_user", "arguments": "{}"},
                {"function": {"name": "search_news"}, "id": "call_124"},
                {"name": "send_email", "arguments": "{}"},
            ],
        },
    ]

    counts = compiler.count_tool_calls_from_messages(messages)
    assert counts == {
        "fetch_user": 2,
        "search_news": 2,
        "send_email": 1,
    }


def test_deterministic_ledger_compiler_violations() -> None:
    """Verifies violation banner creation for exhausted quotas."""
    compiler = DeterministicLedgerCompiler()
    constraints = [
        QuotaConstraint(name="db_write", max_limit=2, used_count=2, unit="writes"),
        QuotaConstraint(name="http_request", max_limit=10, used_count=4, unit="requests"),
    ]
    snapshot = compiler.compile_snapshot(
        session_id="sess_001",
        turn_index=3,
        constraints=constraints,
    )
    violations = compiler.evaluate_constraint_violations(snapshot)
    assert len(violations) == 1
    assert "QUOTA EXHAUSTED" in violations[0]
    assert "db_write: used 2/2 writes" in violations[0]


def test_tail_ledger_injector_render_and_budget() -> None:
    """Verifies status tag formatting and priority budget pruning."""
    config = RuntimeLedgerConfig(
        max_ledger_tokens=40,  # ~160 chars budget
        enable_timestamp=False,
    )
    injector = TailLedgerInjector(config)

    constraints = [
        QuotaConstraint(name="scrape_page", max_limit=2, used_count=1),
    ]
    todos = [
        TodoProgress(step_id="1", title="Init repo", is_completed=True),
        TodoProgress(step_id="2", title="Deploy app", is_completed=False),
    ]
    tool_counts = {"scrape_page": 1, "read_file": 10, "grep_search": 5}
    milestones = ["Milestone A reached", "Milestone B approved", "Milestone C scheduled"]

    snapshot = RuntimeStateSnapshot(
        session_id="sess_abc",
        turn_index=4,
        tool_call_counts=tool_counts,
        constraints=constraints,
        todos=todos,
        current_timestamp_iso="",
        recent_milestones=milestones,
    )

    rendered = injector.render_status_tag(snapshot)
    assert "<agent_status>" in rendered
    assert "</agent_status>" in rendered
    # High priority items must be preserved
    assert "scrape_page" in rendered
    assert "Deploy app" in rendered
    # Condensed version limits characters within budget cap
    assert len(rendered) <= 160


def test_tail_ledger_injector_replace_policy() -> None:
    """Verifies REPLACE policy swaps out prior <agent_status> without prefix drift."""
    config = RuntimeLedgerConfig(update_policy=LedgerUpdatePolicy.REPLACE)
    injector = TailLedgerInjector(config)

    initial_prompt = "You are an AI assistant.\n\n<agent_status>\n[Turn: 1]\n- todo 1\n</agent_status>"
    new_snapshot = RuntimeStateSnapshot(
        session_id="sess_repl",
        turn_index=2,
        tool_call_counts={},
        constraints=(),
        todos=(TodoProgress(step_id="2", title="New task", is_completed=False),),
        current_timestamp_iso="2026-10-08T00:00:00Z",
    )

    injected, result = injector.inject_into_text(initial_prompt, new_snapshot)
    assert result.policy_used == LedgerUpdatePolicy.REPLACE
    assert "Turn: 2" in injected
    assert "[Turn: 1]" not in injected
    # Crucial prompt cache test: system prompt prefix is strictly preserved
    assert injected.startswith("You are an AI assistant.")
    # Must only have one opening and one closing tag
    assert injected.count("<agent_status>") == 1
    assert injected.count("</agent_status>") == 1


def test_tail_ledger_injector_append_policy() -> None:
    """Verifies APPEND policy maintains consecutive log entries when explicitly configured."""
    config = RuntimeLedgerConfig(update_policy=LedgerUpdatePolicy.APPEND)
    injector = TailLedgerInjector(config)

    base_prompt = "System instructions.\n\n<agent_status>\n[Turn: 1]\n</agent_status>"
    new_snapshot = RuntimeStateSnapshot(
        session_id="sess_app",
        turn_index=2,
        tool_call_counts={},
        constraints=(),
        todos=(),
        current_timestamp_iso="2026-10-08T00:00:00Z",
    )

    injected, result = injector.inject_into_text(base_prompt, new_snapshot)
    assert result.policy_used == LedgerUpdatePolicy.APPEND
    assert injected.count("<agent_status>") == 2
    assert "[Turn: 1]" in injected
    assert "Turn: 2" in injected



def test_deterministic_runtime_state_ledger_injection_suite_end_to_end() -> None:
    """Verifies end-to-end facade compilation, mounting, and violation checks."""
    suite = DeterministicRuntimeStateLedgerInjectionSuite()

    system_prompt = "You are a professional full-stack engineer operating in a sandbox."
    constraints = [
        QuotaConstraint(name="bash_command", max_limit=10, used_count=10, unit="runs"),
        QuotaConstraint(name="edit_file", max_limit=20, used_count=5, unit="edits"),
    ]
    todos = [
        TodoProgress(step_id="step_1", title="Write architecture", is_completed=True),
        TodoProgress(step_id="step_2", title="Run test suites", is_completed=False),
    ]

    out_prompt, res, snapshot = suite.compile_and_inject(
        prompt_text=system_prompt,
        session_id="session_live_01",
        turn_index=5,
        tool_call_counts={"bash_command": 10, "edit_file": 5},
        constraints=constraints,
        todos=todos,
        recent_milestones=["Architecture approved"],
    )

    # 1. Output string check
    assert out_prompt.startswith(system_prompt)
    assert "<agent_status>" in out_prompt
    assert "bash_command: used 10/10 runs (EXHAUSTED ❌)" in out_prompt
    assert "edit_file: used 5/20 edits (15 remaining)" in out_prompt
    assert "[✓] Write architecture" in out_prompt
    assert "[ ] Run test suites" in out_prompt
    assert "Architecture approved" in out_prompt
    assert "Tool Invocations: bash_command: 10, edit_file: 5" in out_prompt

    # 2. Result contract check
    assert res.injected_into_tail is True
    assert res.token_estimate > 0

    # 3. Violation alert check
    violations = suite.evaluate_violations(snapshot)
    assert len(violations) == 1
    assert "bash_command: used 10/10 runs" in violations[0]


def test_facade_count_and_inject_from_messages() -> None:
    """Verifies facade automatic tool invocation extraction directly from conversation history."""
    suite = DeterministicRuntimeStateLedgerInjectionSuite()

    raw_messages: list[dict[str, object]] = [
        {
            "role": "assistant",
            "tool_calls": [
                {"name": "query_database", "arguments": "select 1"},
                {"name": "query_database", "arguments": "select 2"},
            ],
        }
    ]

    base = "Current prompt tail."
    out_prompt, _, snap = suite.count_and_inject_from_messages(
        messages=raw_messages,
        base_prompt=base,
        session_id="sess_msg_scan",
        turn_index=1,
    )

    assert snap.tool_call_counts == {"query_database": 2}
    assert "query_database: 2" in out_prompt
