# [INPUT]: PostCompactionToolLoopGuardSuite, CompactionToolLedgerExtractor, LoopDetectionAction, RepeatedToolLoopError
# [OUTPUT]: test_post_compaction_tool_loop_guard_suite
# [POS]: tests.agent.context_management.test_post_compaction_loop_guard_suite
"""Unit test suite for Post-Compaction Tool Loop Guard Suite (Item 331).

Verifies boundary tool ledger extraction, prompt evidence synthesis,
context-aware soft reminders, repeated tool loop circuit breaking, and session isolation.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.post_compaction_loop_guard import (
    CompactionBoundaryLedger,
    CompactionToolLedgerExtractor,
    LoopDetectionAction,
    LoopGuardDecision,
    PostCompactionGuardConfig,
    PostCompactionToolLoopGuardSuite,
    ReexecutionDetector,
    RepeatedToolLoopError,
    format_boundary_ledger_prompt,
)


def _build_sample_messages() -> list[HumanMessage | AIMessage | ToolMessage]:
    """Helper constructing an execution sequence leading up to compaction."""
    return [
        HumanMessage(content="Please search codebase and check file status."),
        AIMessage(
            content="Searching codebase now.",
            tool_calls=[
                {
                    "id": "call_search_1",
                    "name": "search_code",
                    "args": {"query": "PostCompactionToolLoopGuard", "path": "src/"},
                }
            ],
        ),
        ToolMessage(
            content="Found 3 matches in context_management module.",
            tool_call_id="call_search_1",
        ),
        AIMessage(
            content="Checking git status.",
            tool_calls=[
                {
                    "id": "call_git_status_2",
                    "name": "run_command",
                    "args": {"command": "git status"},
                }
            ],
        ),
        ToolMessage(
            content="On branch main, working tree clean.",
            tool_call_id="call_git_status_2",
        ),
        HumanMessage(content="Looks good, please proceed."),
    ]


def test_compaction_tool_ledger_extractor_extracts_signatures() -> None:
    """Ensure ledger extractor correctly captures tool calls and outcome digests."""
    messages = _build_sample_messages()
    ledger: CompactionBoundaryLedger = CompactionToolLedgerExtractor.extract_ledger(
        session_id="session_test_001",
        messages=messages,
        compaction_turn_index=5,
        max_signatures=10,
    )

    assert ledger.session_id == "session_test_001"
    assert ledger.compaction_turn_index == 5
    assert len(ledger.signatures) == 2
    assert len(ledger.ledger_digest) == 64

    first_sig = ledger.signatures[0]
    assert first_sig.tool_name == "search_code"
    assert "Found 3 matches" in first_sig.result_digest
    assert first_sig.call_index == 1
    assert len(first_sig.arguments_hash) == 64

    second_sig = ledger.signatures[1]
    assert second_sig.tool_name == "run_command"
    assert "working tree clean" in second_sig.result_digest
    assert second_sig.call_index == 2


def test_format_boundary_ledger_prompt() -> None:
    """Ensure ledger formatter creates policy-compliant system prompt blocks."""
    messages = _build_sample_messages()
    ledger = CompactionToolLedgerExtractor.extract_ledger(
        session_id="session_test_001",
        messages=messages,
        compaction_turn_index=5,
        max_signatures=5,
    )
    prompt_block = format_boundary_ledger_prompt(ledger)

    assert "=== COMPACTED TOOL EXECUTION LEDGER ===" in prompt_block
    assert "CRITICAL POLICY" in prompt_block
    assert "search_code" in prompt_block
    assert "run_command" in prompt_block

    # Test empty ledger produces empty string
    empty_ledger = CompactionBoundaryLedger(
        session_id="empty_sess",
        compaction_turn_index=1,
        signatures=[],
        ledger_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    assert format_boundary_ledger_prompt(empty_ledger) == ""


def test_reexecution_detector_allows_unseen_tool() -> None:
    """Ensure novel tools executed post-compaction are unconditionally allowed."""
    detector = ReexecutionDetector()
    messages = _build_sample_messages()
    ledger = CompactionToolLedgerExtractor.extract_ledger(
        session_id="sess_allow",
        messages=messages,
        compaction_turn_index=10,
    )
    detector.register_boundary_ledger(ledger)

    decision: LoopGuardDecision = detector.evaluate_tool_call(
        session_id="sess_allow",
        tool_name="view_file",
        arguments={"path": "README.md"},
        current_turn=11,
    )
    assert decision.action == LoopDetectionAction.ALLOW
    assert decision.is_circuit_broken is False
    assert decision.repeat_count == 0


def test_reexecution_detector_soft_remind_on_first_repeat() -> None:
    """Ensure initial duplicate tool call returns REMIND_IN_CONTEXT warning."""
    detector = ReexecutionDetector(
        config=PostCompactionGuardConfig(soft_remind_threshold=1, hard_trip_threshold=3)
    )
    messages = _build_sample_messages()
    ledger = CompactionToolLedgerExtractor.extract_ledger(
        session_id="sess_remind",
        messages=messages,
        compaction_turn_index=10,
    )
    detector.register_boundary_ledger(ledger)

    # Agent attempts to re-execute git status right after compaction
    decision = detector.evaluate_tool_call(
        session_id="sess_remind",
        tool_name="run_command",
        arguments={"command": "git status"},
        current_turn=11,
    )

    assert decision.action == LoopDetectionAction.REMIND_IN_CONTEXT
    assert decision.repeat_count == 1
    assert decision.is_circuit_broken is False
    assert "[SYSTEM NOTICE: TOOL ALREADY EXECUTED]" in decision.injected_reminder
    assert "working tree clean" in decision.injected_reminder


def test_reexecution_detector_hard_trip_circuit_breaker() -> None:
    """Ensure stubborn repeated tool invocations trip the circuit breaker and raise error."""
    detector = ReexecutionDetector(
        config=PostCompactionGuardConfig(soft_remind_threshold=1, hard_trip_threshold=3)
    )
    messages = _build_sample_messages()
    ledger = CompactionToolLedgerExtractor.extract_ledger(
        session_id="sess_breaker",
        messages=messages,
        compaction_turn_index=10,
    )
    detector.register_boundary_ledger(ledger)

    # 1st repeat -> soft remind
    d1 = detector.evaluate_tool_call(
        session_id="sess_breaker",
        tool_name="run_command",
        arguments={"command": "git status"},
        current_turn=11,
    )
    assert d1.action == LoopDetectionAction.REMIND_IN_CONTEXT
    assert d1.repeat_count == 1

    # 2nd repeat -> soft remind
    d2 = detector.evaluate_tool_call(
        session_id="sess_breaker",
        tool_name="run_command",
        arguments={"command": "git status"},
        current_turn=11,
    )
    assert d2.action == LoopDetectionAction.REMIND_IN_CONTEXT
    assert d2.repeat_count == 2

    # 3rd repeat -> tripped circuit breaker (without raise)
    d3 = detector.evaluate_tool_call(
        session_id="sess_breaker",
        tool_name="run_command",
        arguments={"command": "git status"},
        current_turn=12,
        raise_on_trip=False,
    )
    assert d3.action == LoopDetectionAction.TRIPPED_CIRCUIT_BREAKER
    assert d3.repeat_count == 3
    assert d3.is_circuit_broken is True
    assert "CRITICAL: Tool 'run_command' was repeatedly called" in d3.injected_reminder

    # 4th repeat with raise_on_trip=True -> RepeatedToolLoopError
    with pytest.raises(RepeatedToolLoopError) as exc_info:
        detector.evaluate_tool_call(
            session_id="sess_breaker",
            tool_name="run_command",
            arguments={"command": "git status"},
            current_turn=12,
            raise_on_trip=True,
        )
    err = exc_info.value
    assert err.tool_name == "run_command"
    assert err.repeat_count == 4
    assert len(err.args_hash) == 64


def test_protection_window_turns_expiration() -> None:
    """Ensure guard becomes inactive when turns exceed protect_window_turns."""
    detector = ReexecutionDetector(
        config=PostCompactionGuardConfig(protect_window_turns=3)
    )
    messages = _build_sample_messages()
    ledger = CompactionToolLedgerExtractor.extract_ledger(
        session_id="sess_window",
        messages=messages,
        compaction_turn_index=10,
    )
    detector.register_boundary_ledger(ledger)

    # Turn 10 + 4 = 14 (exceeds window of 3 turns)
    decision = detector.evaluate_tool_call(
        session_id="sess_window",
        tool_name="run_command",
        arguments={"command": "git status"},
        current_turn=14,
    )
    assert decision.action == LoopDetectionAction.ALLOW
    assert decision.repeat_count == 0


def test_suite_facade_end_to_end_and_reset() -> None:
    """Ensure PostCompactionToolLoopGuardSuite coordinates ledger and detector lifecycle."""
    suite = PostCompactionToolLoopGuardSuite()
    messages = _build_sample_messages()

    ledger, prompt_block = suite.capture_compaction_boundary(
        session_id="sess_facade",
        messages=messages,
        compaction_turn_index=20,
    )
    assert ledger.session_id == "sess_facade"
    assert len(prompt_block) > 0
    assert suite.get_active_ledger("sess_facade") is not None

    # Intercept duplicate call
    decision = suite.intercept_tool_call(
        session_id="sess_facade",
        tool_name="search_code",
        arguments={"query": "PostCompactionToolLoopGuard", "path": "src/"},
        current_turn=21,
    )
    assert decision.action == LoopDetectionAction.REMIND_IN_CONTEXT
    assert decision.repeat_count == 1

    # Reset session
    suite.reset_session("sess_facade")
    assert suite.get_active_ledger("sess_facade") is None

    # After reset, the same call is allowed as there is no active ledger
    decision_after_reset = suite.intercept_tool_call(
        session_id="sess_facade",
        tool_name="search_code",
        arguments={"query": "PostCompactionToolLoopGuard", "path": "src/"},
        current_turn=21,
    )
    assert decision_after_reset.action == LoopDetectionAction.ALLOW
    assert decision_after_reset.repeat_count == 0
