"""Tests for cache_breakpoint_validator module."""

from __future__ import annotations

from unittest.mock import patch

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pipeline.processors.cache_breakpoint_validator import (
    dedup_and_sort,
    enforce_max_breakpoints,
    filter_invalid,
    validate_breakpoints,
    validate_token_distances,
)


def _make_messages(n: int) -> list[HumanMessage | SystemMessage]:
    return [SystemMessage(content="system")] + [HumanMessage(content=f"msg {i}") for i in range(n - 1)]


class TestDedupAndSort:
    def test_removes_duplicates(self) -> None:
        assert dedup_and_sort([3, 1, 2, 1, 3]) == [1, 2, 3]

    def test_sorts(self) -> None:
        assert dedup_and_sort([5, 3, 1]) == [1, 3, 5]

    def test_empty(self) -> None:
        assert dedup_and_sort([]) == []


class TestFilterInvalid:
    def test_removes_negative(self) -> None:
        msgs = _make_messages(5)
        assert filter_invalid([-1, 0, 3], msgs) == [0, 3]

    def test_removes_out_of_range(self) -> None:
        msgs = _make_messages(5)
        assert filter_invalid([0, 4, 5, 100], msgs) == [0, 4]

    def test_empty_breakpoints(self) -> None:
        msgs = _make_messages(5)
        assert filter_invalid([], msgs) == []


class TestEnforceMaxBreakpoints:
    def test_no_trim_needed(self) -> None:
        msgs = _make_messages(10)
        assert enforce_max_breakpoints([0, 3, 9], msgs, max_breakpoints=4) == [0, 3, 9]

    def test_trims_to_max(self) -> None:
        msgs = _make_messages(10)
        result = enforce_max_breakpoints([0, 2, 4, 6, 9], msgs, max_breakpoints=4)
        assert len(result) == 4
        assert result[0] == 0
        assert result[-1] == 9

    def test_keeps_first_and_last(self) -> None:
        msgs = _make_messages(10)
        result = enforce_max_breakpoints([0, 2, 4, 6, 8, 9], msgs, max_breakpoints=3)
        assert result[0] == 0
        assert result[-1] == 9
        assert len(result) == 3

    def test_no_last_message_fallback(self) -> None:
        msgs = _make_messages(10)
        result = enforce_max_breakpoints([0, 2, 4, 6, 8], msgs, max_breakpoints=3)
        assert len(result) == 3
        assert result == [0, 2, 4]


class TestValidateTokenDistances:
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors"
        ".cache_breakpoint_validator.estimate_messages_tokens",
        return_value=2000,
    )
    def test_keeps_all_distant(self, mock_est: object) -> None:
        msgs = _make_messages(10)
        result = validate_token_distances([0, 5, 9], msgs, min_message_gap=3)
        assert result == [0, 5, 9]

    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors"
        ".cache_breakpoint_validator.estimate_messages_tokens",
        return_value=500,
    )
    def test_removes_too_close(self, mock_est: object) -> None:
        msgs = _make_messages(10)
        result = validate_token_distances([0, 1, 2], msgs, min_message_gap=5)
        assert 0 in result
        assert len(result) < 3

    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors"
        ".cache_breakpoint_validator.estimate_messages_tokens",
        return_value=500,
    )
    def test_keeps_last_message_unconditionally(self, mock_est: object) -> None:
        msgs = _make_messages(10)
        result = validate_token_distances([0, 9], msgs, min_message_gap=5)
        assert 9 in result

    def test_empty_breakpoints(self) -> None:
        assert validate_token_distances([], _make_messages(5), min_message_gap=3) == []

    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors"
        ".cache_breakpoint_validator.estimate_messages_tokens",
        return_value=500,
    )
    def test_message_gap_fallback(self, mock_est: object) -> None:
        msgs = _make_messages(20)
        result = validate_token_distances([0, 5], msgs, min_message_gap=3)
        assert 5 in result


class TestValidateBreakpoints:
    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors"
        ".cache_breakpoint_validator.estimate_messages_tokens",
        return_value=2000,
    )
    def test_full_pipeline(self, mock_est: object) -> None:
        msgs = _make_messages(10)
        result = validate_breakpoints(
            breakpoints=[9, 0, 0, 5, -1, 100], messages=msgs, min_message_gap=3, max_breakpoints=4
        )
        assert result == [0, 5, 9]

    def test_empty_breakpoints(self) -> None:
        assert validate_breakpoints([], _make_messages(5), min_message_gap=3, max_breakpoints=4) == []

    @patch(
        "myrm_agent_harness.agent.context_management.pipeline.processors"
        ".cache_breakpoint_validator.estimate_messages_tokens",
        return_value=2000,
    )
    def test_all_invalid_filtered(self, mock_est: object) -> None:
        msgs = _make_messages(5)
        result = validate_breakpoints(breakpoints=[-1, 100], messages=msgs, min_message_gap=3, max_breakpoints=4)
        assert result == []
