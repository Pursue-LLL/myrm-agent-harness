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

    def test_json_key_order_and_whitespace_do_not_trigger_delta(self) -> None:
        monitor = HashMonitor(last_hash=None)
        first = monitor.compute_delta('{"b":2,"a":1}')
        monitor.update_baseline(first)

        delta = monitor.compute_delta('{ "a": 1, "b": 2 }')
        assert delta == ""

    def test_asset_array_order_drift_does_not_trigger_delta(self) -> None:
        monitor = HashMonitor(last_hash=None)
        first = monitor.compute_delta('[{"asset":"BTC","confidence":80},{"asset":"ETH","confidence":70}]')
        monitor.update_baseline(first)

        # Same semantic content, different order + key ordering.
        delta = monitor.compute_delta('[{"confidence":70,"asset":"ETH"},{"confidence":80,"asset":"BTC"}]')
        assert delta == ""

    def test_non_asset_array_keeps_order_sensitivity(self) -> None:
        monitor = HashMonitor(last_hash=None)
        first = monitor.compute_delta('[1,2,3]')
        monitor.update_baseline(first)

        delta = monitor.compute_delta('[3,2,1]')
        assert delta == "[3,2,1]"

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
