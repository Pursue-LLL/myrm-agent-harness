"""Unit tests for SetMonitor."""

from myrm_agent_harness.infra.incremental.set_monitor import SetMonitor


class TestSetMonitor:
    """Test SetMonitor set-based incremental detection."""

    def test_baseline_run_returns_empty_delta(self) -> None:
        """First run (baseline) should return empty delta."""
        monitor = SetMonitor(seen=None)

        assert monitor.is_baseline()

        output = "url1\nurl2\nurl3"
        delta = monitor.compute_delta(output)

        assert delta == ""
        assert monitor.is_baseline()

    def test_baseline_update_marks_not_baseline(self) -> None:
        """Updating baseline should mark monitor as not baseline."""
        monitor = SetMonitor(seen=None)

        output = "url1\nurl2\nurl3"
        delta = monitor.compute_delta(output)
        monitor.update_baseline(delta)

        assert not monitor.is_baseline()

    def test_no_new_items_returns_empty_delta(self) -> None:
        """No new items should return empty delta."""
        monitor = SetMonitor(seen={"url1", "url2", "url3"})

        output = "url1\nurl2\nurl3"
        delta = monitor.compute_delta(output)

        assert delta == ""

    def test_new_items_returns_sorted_delta(self) -> None:
        """New items should be returned sorted."""
        monitor = SetMonitor(seen={"url1", "url2"})

        output = "url1\nurl2\nurl3\nurl4"
        delta = monitor.compute_delta(output)

        assert delta == "url3\nurl4"

    def test_update_baseline_adds_new_items(self) -> None:
        """Updating baseline should add new items to seen set."""
        monitor = SetMonitor(seen={"url1", "url2"})

        output = "url1\nurl2\nurl3\nurl4"
        delta = monitor.compute_delta(output)
        monitor.update_baseline(delta)

        output2 = "url1\nurl2\nurl3\nurl4"
        delta2 = monitor.compute_delta(output2)

        assert delta2 == ""

    def test_empty_output_returns_empty_delta(self) -> None:
        """Empty output should return empty delta."""
        monitor = SetMonitor(seen={"url1"})

        delta = monitor.compute_delta("")
        assert delta == ""

        delta = monitor.compute_delta("   \n  \n  ")
        assert delta == ""

    def test_whitespace_handling(self) -> None:
        """Whitespace should be stripped from items."""
        monitor = SetMonitor(seen={"url1"})

        output = "  url1  \n  url2  \n\n  url3  "
        delta = monitor.compute_delta(output)

        assert delta == "url2\nurl3"

    def test_state_serialization_roundtrip(self) -> None:
        """State should survive serialization roundtrip."""
        monitor1 = SetMonitor(seen={"url1", "url2", "url3"})
        monitor1.update_baseline("")

        state_data = monitor1.get_state_data()
        monitor2 = SetMonitor.from_state_data(state_data)

        output = "url1\nurl2\nurl3\nurl4"
        delta = monitor2.compute_delta(output)

        assert delta == "url4"

    def test_baseline_state_serialization(self) -> None:
        """Baseline state should be preserved in serialization."""
        monitor1 = SetMonitor(seen=None)

        state_data = monitor1.get_state_data()
        assert state_data["is_baseline"] is True

        monitor2 = SetMonitor.from_state_data(state_data)
        assert monitor2.is_baseline()

    def test_incremental_updates(self) -> None:
        """Multiple incremental updates should accumulate correctly."""
        monitor = SetMonitor(seen=None)

        output1 = "url1\nurl2"
        delta1 = monitor.compute_delta(output1)
        assert delta1 == ""
        monitor.update_baseline(delta1)

        output2 = "url1\nurl2\nurl3"
        delta2 = monitor.compute_delta(output2)
        assert delta2 == "url3"
        monitor.update_baseline(delta2)

        output3 = "url1\nurl2\nurl3\nurl4\nurl5"
        delta3 = monitor.compute_delta(output3)
        assert delta3 == "url4\nurl5"
        monitor.update_baseline(delta3)

        output4 = "url1\nurl2\nurl3\nurl4\nurl5"
        delta4 = monitor.compute_delta(output4)
        assert delta4 == ""

    def test_duplicate_items_in_output(self) -> None:
        """Duplicate items in output should be deduplicated."""
        monitor = SetMonitor(seen={"url1"})

        output = "url1\nurl2\nurl2\nurl3\nurl3\nurl3"
        delta = monitor.compute_delta(output)

        assert delta == "url2\nurl3"

    def test_invalid_state_data_resets_to_empty(self) -> None:
        """Invalid state data should reset to empty set."""
        state_data = {"seen": "not a list", "is_baseline": False}
        monitor = SetMonitor.from_state_data(state_data)

        output = "url1\nurl2"
        delta = monitor.compute_delta(output)

        assert delta == "url1\nurl2"

    def test_very_long_urls(self) -> None:
        """Should handle very long URLs correctly."""
        long_url = "https://example.com/" + "a" * 1000
        monitor = SetMonitor(seen={"url1"})

        output = f"url1\n{long_url}"
        delta = monitor.compute_delta(output)

        assert delta == long_url

    def test_unicode_items(self) -> None:
        """Should handle unicode characters correctly."""
        monitor = SetMonitor(seen={"文章1"})

        output = "文章1\n文章2\n文章3"
        delta = monitor.compute_delta(output)

        assert delta == "文章2\n文章3"

    def test_empty_lines_ignored(self) -> None:
        """Empty lines should be ignored."""
        monitor = SetMonitor(seen={"url1"})

        output = "url1\n\n\nurl2\n\n"
        delta = monitor.compute_delta(output)

        assert delta == "url2"
