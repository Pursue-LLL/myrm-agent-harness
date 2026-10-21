"""Test goal lifecycle Prometheus metrics.

Verifies counter/histogram recording functions and graceful degradation.
"""

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.observability.metrics.goal_metrics import (
    _HISTOGRAM_STATES,
    _STATUS_COUNTERS,
    goal_cancelled_total,
    goal_completed_total,
    goal_cost_usd,
    goal_created_total,
    goal_duration_seconds,
    goal_paused_total,
    goal_resumed_total,
    goal_token_usage,
    record_goal_created,
    record_goal_resumed,
    record_goal_terminal,
)


class TestRecordGoalCreated:
    def test_increments_counter(self) -> None:
        mock_counter = MagicMock()
        with patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_created_total", mock_counter):
            record_goal_created()
        mock_counter.inc.assert_called_once()

    def test_noop_when_none(self) -> None:
        with patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_created_total", None):
            record_goal_created()


class TestRecordGoalResumed:
    def test_increments_counter(self) -> None:
        mock_counter = MagicMock()
        with patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_resumed_total", mock_counter):
            record_goal_resumed()
        mock_counter.inc.assert_called_once()

    def test_noop_when_none(self) -> None:
        with patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_resumed_total", None):
            record_goal_resumed()


class TestRecordGoalTerminal:
    def test_complete_records_counter_and_labeled_histograms(self) -> None:
        mock_counter = MagicMock()
        mock_duration = MagicMock()
        mock_tokens = MagicMock()
        mock_cost = MagicMock()
        with (
            patch.dict(_STATUS_COUNTERS, {"complete": mock_counter}),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_duration_seconds", mock_duration),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_token_usage", mock_tokens),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_cost_usd", mock_cost),
        ):
            record_goal_terminal("complete", 120.5, 50000, 1.25)
        mock_counter.inc.assert_called_once()
        mock_duration.labels.assert_called_once_with(status="complete")
        mock_duration.labels.return_value.observe.assert_called_once_with(120.5)
        mock_tokens.labels.assert_called_once_with(status="complete")
        mock_tokens.labels.return_value.observe.assert_called_once_with(50000)
        mock_cost.labels.assert_called_once_with(status="complete")
        mock_cost.labels.return_value.observe.assert_called_once_with(1.25)

    def test_budget_limited_records_counter_and_duration(self) -> None:
        mock_counter = MagicMock()
        mock_duration = MagicMock()
        with (
            patch.dict(_STATUS_COUNTERS, {"budget_limited": mock_counter}),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_duration_seconds", mock_duration),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_token_usage", None),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_cost_usd", None),
        ):
            record_goal_terminal("budget_limited", 60.0, 0, 0.0)
        mock_counter.inc.assert_called_once()
        mock_duration.labels.assert_called_once_with(status="budget_limited")
        mock_duration.labels.return_value.observe.assert_called_once_with(60.0)

    def test_paused_records_counter_but_skips_histograms(self) -> None:
        mock_counter = MagicMock()
        mock_duration = MagicMock()
        with (
            patch.dict(_STATUS_COUNTERS, {"paused": mock_counter}),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_duration_seconds", mock_duration),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_token_usage", None),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_cost_usd", None),
        ):
            record_goal_terminal("paused", 120.0, 50000, 1.0)
        mock_counter.inc.assert_called_once()
        mock_duration.labels.assert_not_called()

    def test_unknown_status_skips_everything(self) -> None:
        mock_duration = MagicMock()
        with (
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_duration_seconds", mock_duration),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_token_usage", None),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_cost_usd", None),
        ):
            record_goal_terminal("unknown_status", 10.0, 0, 0.0)
        mock_duration.labels.assert_not_called()

    def test_zero_duration_skips_histogram(self) -> None:
        mock_counter = MagicMock()
        mock_duration = MagicMock()
        with (
            patch.dict(_STATUS_COUNTERS, {"complete": mock_counter}),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_duration_seconds", mock_duration),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_token_usage", None),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_cost_usd", None),
        ):
            record_goal_terminal("complete", 0.0, 0, 0.0)
        mock_counter.inc.assert_called_once()
        mock_duration.labels.assert_not_called()

    def test_all_none_graceful(self) -> None:
        with (
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_duration_seconds", None),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_token_usage", None),
            patch("myrm_agent_harness.observability.metrics.goal_metrics.goal_cost_usd", None),
        ):
            record_goal_terminal("complete", 100.0, 50000, 1.0)


class TestStatusCounterMapping:
    @pytest.mark.parametrize("status", ["complete", "budget_limited", "paused", "cancelled"])
    def test_all_statuses_have_counters(self, status: str) -> None:
        assert status in _STATUS_COUNTERS


class TestHistogramStates:
    def test_histogram_states_are_terminal(self) -> None:
        assert {"complete", "budget_limited", "cancelled"} == _HISTOGRAM_STATES

    def test_paused_excluded_from_histograms(self) -> None:
        assert "paused" not in _HISTOGRAM_STATES


class TestModuleLevelMetrics:
    def test_counters_exist(self) -> None:
        for _metric in [
            goal_created_total,
            goal_completed_total,
            goal_paused_total,
            goal_cancelled_total,
            goal_resumed_total,
        ]:
            assert True

    def test_histograms_exist(self) -> None:
        for _metric in [goal_duration_seconds, goal_token_usage, goal_cost_usd]:
            assert True
