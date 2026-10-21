"""Test agent execution monitoring metrics (TTFA and tool execution counters).

Requires [observability] extra (prometheus-client); skipped on core-only dev sync.
"""

from __future__ import annotations

from unittest import mock

import pytest

pytest.importorskip("prometheus_client")

from myrm_agent_harness.observability.metrics import agent_metrics


@pytest.fixture(autouse=True)
def _reset_ttfa_start_time() -> None:
    """Isolate the TTFA ContextVar between tests."""
    agent_metrics._ttfa_start_time.set(None)
    yield
    agent_metrics._ttfa_start_time.set(None)


def test_record_ttfa_run_start_then_first_action_observes_histogram() -> None:
    """run_start followed by first_action records exactly one TTFA sample."""
    labels = mock.MagicMock()
    with mock.patch.object(agent_metrics.time_to_first_action_seconds, "labels", return_value=labels):
        agent_metrics.record_ttfa_run_start()
        agent_metrics.record_ttfa_first_action(agent_type="test-agent")

    labels.observe.assert_called_once()
    observed = labels.observe.call_args.args[0]
    assert observed >= 0


def test_record_ttfa_first_action_clears_start_time_after_first_sample() -> None:
    """The start time is cleared so only the FIRST action records a sample."""
    labels = mock.MagicMock()
    with mock.patch.object(agent_metrics.time_to_first_action_seconds, "labels", return_value=labels):
        agent_metrics.record_ttfa_run_start()
        agent_metrics.record_ttfa_first_action()
        agent_metrics.record_ttfa_first_action()

    assert labels.observe.call_count == 1
    assert agent_metrics._ttfa_start_time.get() is None


def test_record_ttfa_first_action_without_run_start_is_noop() -> None:
    """first_action without a prior run_start is a safe no-op."""
    with mock.patch.object(agent_metrics.time_to_first_action_seconds, "labels") as labels:
        agent_metrics.record_ttfa_first_action()

    labels.assert_not_called()


def test_record_ttfa_first_action_skips_when_metric_is_none() -> None:
    """When the histogram factory returned None (no prometheus_client), nothing is recorded."""
    with (
        mock.patch.object(agent_metrics.time_to_first_action_seconds, "labels") as labels,
        mock.patch.object(agent_metrics, "time_to_first_action_seconds", None),
    ):
        agent_metrics.record_ttfa_run_start()
        agent_metrics.record_ttfa_first_action()

    labels.assert_not_called()


def test_record_ttfa_first_action_swallows_lookup_error() -> None:
    """LookupError from the ContextVar is swallowed (defensive)."""
    fake_ctx = mock.MagicMock()
    fake_ctx.get.side_effect = LookupError
    with mock.patch.object(agent_metrics, "_ttfa_start_time", fake_ctx):
        agent_metrics.record_ttfa_first_action()  # must not raise


def test_record_ttfa_first_action_swallows_unexpected_error() -> None:
    """Unexpected errors inside the recording path are swallowed (defensive)."""
    fake_ctx = mock.MagicMock()
    fake_ctx.get.return_value = 1.0
    with (
        mock.patch.object(agent_metrics, "_ttfa_start_time", fake_ctx),
        mock.patch.object(
            agent_metrics.time_to_first_action_seconds,
            "labels",
            side_effect=RuntimeError("boom"),
        ),
    ):
        agent_metrics.record_ttfa_first_action()  # must not raise


def test_record_ttfa_run_start_sets_start_time() -> None:
    """run_start stores a timestamp that first_action consumes."""
    agent_metrics.record_ttfa_run_start()
    assert agent_metrics._ttfa_start_time.get() is not None
