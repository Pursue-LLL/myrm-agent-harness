"""Unit tests for mixed batch tool validation and role alternation guard suite.

Verifies:
- Pure valid batch dispatching.
- Fuzzy tool name repair, case normalization, and alias mapping.
- Mixed batch split execution (valid calls execute, unknown calls receive synthetic tool errors).
- 3-strike partial exit state machine for purely invalid tool calls.
- Tool-call ID deduplication across batch and session history.
- Mid-stream JSON truncation detection and refusal.
- Role alternation invariant enforcement (detecting illegal user insertions).
- Interrupted tool sequence automatic closure for graceful recovery.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.tool_validation import (
    MixedBatchToolValidator,
    RoleAlternationGuard,
    RoleAlternationViolationError,
    ToolCallEnvelope,
    ToolNameFuzzyRepairer,
    ToolValidationAction,
)


@pytest.fixture
def sample_valid_tools() -> frozenset[str]:
    return frozenset(
        {
            "read_file",
            "write_file",
            "execute_bash",
            "git_commit",
            "search_codebase",
        }
    )


@pytest.fixture
def fuzzy_repairer() -> ToolNameFuzzyRepairer:
    alias_map = {
        "bash": "execute_bash",
        "readfile": "read_file",
        "writefile": "write_file",
    }
    return ToolNameFuzzyRepairer(alias_map=alias_map, similarity_threshold=0.82)


def test_pure_valid_batch_dispatch(
    sample_valid_tools: frozenset[str],
    fuzzy_repairer: ToolNameFuzzyRepairer,
) -> None:
    validator = MixedBatchToolValidator(sample_valid_tools, fuzzy_repairer=fuzzy_repairer)
    calls = (
        ToolCallEnvelope(id="call_1", name="read_file", arguments='{"path": "a.py"}', index=0),
        ToolCallEnvelope(id="call_2", name="write_file", arguments='{"path": "b.py", "content": "x"}', index=1),
    )

    verdict = validator.validate_batch(calls)
    assert verdict.action == ToolValidationAction.OK
    assert len(verdict.executable_calls) == 2
    assert len(verdict.synthetic_results) == 0
    assert not verdict.is_mixed_batch
    assert verdict.strike_count == 0


def test_fuzzy_name_repair_and_alias_mapping(
    sample_valid_tools: frozenset[str],
    fuzzy_repairer: ToolNameFuzzyRepairer,
) -> None:
    validator = MixedBatchToolValidator(sample_valid_tools, fuzzy_repairer=fuzzy_repairer)
    calls = (
        ToolCallEnvelope(id="c1", name="READ_FILE", arguments='{"path": "foo"}', index=0),
        ToolCallEnvelope(id="c2", name="read-file", arguments='{"path": "bar"}', index=1),
        ToolCallEnvelope(id="c3", name="bash", arguments='{"cmd": "ls"}', index=2),
    )

    verdict = validator.validate_batch(calls)
    assert verdict.action == ToolValidationAction.OK
    assert len(verdict.executable_calls) == 3
    assert verdict.executable_calls[0].name == "read_file"
    assert verdict.executable_calls[1].name == "read_file"
    assert verdict.executable_calls[2].name == "execute_bash"
    assert len(verdict.repaired_names) == 3


def test_mixed_batch_split_execution_and_strike_preservation(
    sample_valid_tools: frozenset[str],
    fuzzy_repairer: ToolNameFuzzyRepairer,
) -> None:
    validator = MixedBatchToolValidator(sample_valid_tools, fuzzy_repairer=fuzzy_repairer)
    calls = (
        ToolCallEnvelope(id="call_valid", name="read_file", arguments='{"path": "ok.py"}', index=0),
        ToolCallEnvelope(id="call_invalid", name="launch_rocket_hyperdrive", arguments="{}", index=1),
    )

    verdict = validator.validate_batch(calls)
    assert verdict.action == ToolValidationAction.SPLIT_EXECUTE
    assert verdict.is_mixed_batch is True
    assert len(verdict.executable_calls) == 1
    assert verdict.executable_calls[0].name == "read_file"

    assert len(verdict.synthetic_results) == 1
    synth = verdict.synthetic_results[0]
    assert synth.tool_call_id == "call_invalid"
    assert synth.role == "tool"
    assert synth.is_error is True
    assert "Unknown tool 'launch_rocket_hyperdrive'" in synth.content

    # Strikes must remain 0 when at least one valid tool executed
    assert verdict.strike_count == 0
    assert validator.current_strikes == 0


def test_three_strike_partial_exit_and_counter_reset(
    sample_valid_tools: frozenset[str],
    fuzzy_repairer: ToolNameFuzzyRepairer,
) -> None:
    validator = MixedBatchToolValidator(
        sample_valid_tools,
        fuzzy_repairer=fuzzy_repairer,
        max_invalid_strikes=3,
    )
    bad_call = (
        ToolCallEnvelope(id="c_err", name="hallucinated_tool_xyz", arguments="{}", index=0),
    )

    # Strike 1
    v1 = validator.validate_batch(bad_call)
    assert v1.action == ToolValidationAction.RETRY_MODEL
    assert v1.strike_count == 1
    assert validator.current_strikes == 1

    # Strike 2
    v2 = validator.validate_batch(bad_call)
    assert v2.action == ToolValidationAction.RETRY_MODEL
    assert v2.strike_count == 2
    assert validator.current_strikes == 2

    # Strike 3 -> Terminal partial exit
    v3 = validator.validate_batch(bad_call)
    assert v3.action == ToolValidationAction.TERMINAL_PARTIAL_EXIT
    assert v3.strike_count == 3
    assert validator.current_strikes == 0  # Reset after exit
    assert v3.failure_reason is not None
    assert "Exceeded maximum consecutive invalid tool retries" in v3.failure_reason


def test_tool_call_id_uniquification(
    sample_valid_tools: frozenset[str],
) -> None:
    validator = MixedBatchToolValidator(sample_valid_tools)
    calls = (
        ToolCallEnvelope(id="call_0", name="read_file", arguments="{}", index=0),
        ToolCallEnvelope(id="call_0", name="read_file", arguments="{}", index=1),
        ToolCallEnvelope(id="call_0", name="read_file", arguments="{}", index=2),
    )
    taken_in_session = {"call_0"}

    verdict = validator.validate_batch(calls, taken_session_ids=taken_in_session)
    ids = [c.id for c in verdict.executable_calls]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert "call_0_dup1" in ids
    assert "call_0_dup2" in ids
    assert "call_0_dup3" in ids


def test_truncated_arguments_refusal(
    sample_valid_tools: frozenset[str],
) -> None:
    validator = MixedBatchToolValidator(sample_valid_tools)
    truncated_calls = (
        ToolCallEnvelope(
            id="cut_1",
            name="read_file",
            arguments='{"path": "/truncated/path/here',
            index=0,
        ),
    )

    verdict = validator.validate_batch(truncated_calls)
    assert verdict.action == ToolValidationAction.TERMINAL_PARTIAL_EXIT
    assert verdict.failure_reason is not None
    assert "Truncated tool arguments detected" in verdict.failure_reason


def test_role_alternation_guard_invariant_validation() -> None:
    # 1. Valid alternating sequence
    valid_msgs: list[dict[str, object]] = [
        {"role": "user", "content": "Read files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "read_file"}},
                {"id": "call_2", "function": {"name": "read_file"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "data1"},
        {"role": "tool", "tool_call_id": "call_2", "content": "data2"},
        {"role": "assistant", "content": "Files read successfully"},
    ]
    RoleAlternationGuard.validate_conversation_invariants(valid_msgs)

    # 2. Illegal user insertion right after tool_calls
    illegal_user_insertion: list[dict[str, object]] = [
        {"role": "user", "content": "Read files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {"name": "read_file"}}],
        },
        {"role": "user", "content": "Wait! Stop!"},  # Illegal: causes HTTP 400 at LLM API
    ]
    with pytest.raises(RoleAlternationViolationError, match="expected 'tool'"):
        RoleAlternationGuard.validate_conversation_invariants(illegal_user_insertion)

    # 3. Orphaned tool result without preceding tool_call
    orphaned_tool_result: list[dict[str, object]] = [
        {"role": "user", "content": "Hello"},
        {"role": "tool", "tool_call_id": "ghost_1", "content": "result"},
    ]
    with pytest.raises(RoleAlternationViolationError, match="Orphaned 'tool' message"):
        RoleAlternationGuard.validate_conversation_invariants(orphaned_tool_result)


def test_close_interrupted_tool_sequence() -> None:
    unclosed_msgs: list[dict[str, object]] = [
        {"role": "user", "content": "Start tasks"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "function": {"name": "task1"}},
                {"id": "c2", "function": {"name": "task2"}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "Done task 1"},
        # c2 was interrupted and left hanging!
    ]

    # Verify unclosed raises violation before fix
    with pytest.raises(RoleAlternationViolationError, match="open tool call"):
        RoleAlternationGuard.validate_conversation_invariants(unclosed_msgs)

    # Auto-close the open sequence
    closed_msgs = RoleAlternationGuard.close_interrupted_tool_sequence(
        unclosed_msgs,
        abort_reason="Operator cancelled execution",
    )

    # Now verify invariants pass cleanly
    RoleAlternationGuard.validate_conversation_invariants(closed_msgs)
    assert len(closed_msgs) == 4
    assert closed_msgs[3]["role"] == "tool"
    assert closed_msgs[3]["tool_call_id"] == "c2"
    assert "Operator cancelled execution" in str(closed_msgs[3]["content"])
