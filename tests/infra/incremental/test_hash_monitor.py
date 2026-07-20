"""Unit tests for HashMonitor."""

from myrm_agent_harness.infra.incremental.hash_monitor import HashMonitor


class TestHashMonitor:
    """Test hash-based incremental change detection."""

    def test_baseline_run_returns_empty_delta(self) -> None:
        monitor = HashMonitor(last_hash=None)

        delta = monitor.compute_delta("hello world")
        assert delta == ""
        assert monitor.is_baseline()

        monitor.update_baseline(delta)
        assert not monitor.is_baseline()

    def test_unchanged_content_returns_empty_delta(self) -> None:
        monitor = HashMonitor(last_hash=None)
        first = monitor.compute_delta("hello world")
        monitor.update_baseline(first)

        second = monitor.compute_delta("hello world")
        assert second == ""

    def test_changed_content_returns_full_output(self) -> None:
        monitor = HashMonitor(last_hash=None)
        first = monitor.compute_delta("alpha")
        monitor.update_baseline(first)

        delta = monitor.compute_delta("beta")
        assert delta == "beta"

    def test_state_serialization_roundtrip(self) -> None:
        monitor1 = HashMonitor(last_hash=None)
        first = monitor1.compute_delta("alpha")
        monitor1.update_baseline(first)
        monitor1.compute_delta("beta")
        monitor1.update_baseline("beta")

        state = monitor1.get_state_data()
        monitor2 = HashMonitor.from_state_data(state)

        assert monitor2.compute_delta("beta") == ""
        assert monitor2.compute_delta("gamma") == "gamma"
