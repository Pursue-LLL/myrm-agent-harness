"""Tests for taint_tracker module."""

from myrm_agent_harness.agent.security.guards.taint_tracker import (
    TAINT_SINK_POLICIES,
    TaintLabel,
    TaintTracker,
    get_taint_tracker,
    reset_taint_tracker,
)
from myrm_agent_harness.agent.security.tool_registry import resolve_safety_metadata


class TestTaintLabel:
    def test_values(self):
        assert TaintLabel.EXTERNAL_NETWORK == "external_network"
        assert TaintLabel.SECRET == "secret"


class TestTaintSources:
    def test_web_fetch_is_external(self):
        meta = resolve_safety_metadata("web_fetch_tool")
        assert meta.taint_label == TaintLabel.EXTERNAL_NETWORK

    def test_web_search_is_external(self):
        meta = resolve_safety_metadata("web_search_tool")
        assert meta.taint_label == TaintLabel.EXTERNAL_NETWORK


class TestTaintSinkPolicies:
    def test_bash_blocks_external(self):
        assert TaintLabel.EXTERNAL_NETWORK in TAINT_SINK_POLICIES["bash_tool"]
        assert TaintLabel.EXTERNAL_NETWORK in TAINT_SINK_POLICIES["bash_code_execute_tool"]

    def test_file_write_blocks_external(self):
        assert TaintLabel.EXTERNAL_NETWORK in TAINT_SINK_POLICIES["file_write_tool"]
        assert TaintLabel.EXTERNAL_NETWORK in TAINT_SINK_POLICIES["file_edit_tool"]

    def test_web_search_not_a_sink(self):
        assert "web_search_tool" not in TAINT_SINK_POLICIES


class TestTaintTracker:
    def test_empty_tracker(self):
        tracker = TaintTracker()
        assert not tracker.is_tainted
        assert tracker.labels == frozenset()

    def test_record_label(self):
        tracker = TaintTracker()
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        assert tracker.is_tainted
        assert TaintLabel.EXTERNAL_NETWORK in tracker.labels

    def test_record_idempotent(self):
        tracker = TaintTracker()
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        assert len(tracker.labels) == 1

    def test_record_tool_output_known_source(self):
        tracker = TaintTracker()
        tracker.record_tool_output("web_fetch_tool")
        assert TaintLabel.EXTERNAL_NETWORK in tracker.labels

    def test_record_tool_output_unknown_tool(self):
        tracker = TaintTracker()
        tracker.record_tool_output("some_safe_tool")
        assert not tracker.is_tainted

    def test_check_sink_no_taint(self):
        tracker = TaintTracker()
        assert tracker.check_sink("bash_tool") is None

    def test_check_sink_with_conflict(self):
        tracker = TaintTracker()
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        conflict = tracker.check_sink("bash_tool")
        assert TaintLabel.EXTERNAL_NETWORK in conflict

    def test_check_sink_no_conflict(self):
        tracker = TaintTracker()
        tracker.record(TaintLabel.SECRET)
        assert tracker.check_sink("bash_tool") is None

    def test_check_sink_unknown_tool(self):
        tracker = TaintTracker()
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        assert tracker.check_sink("web_search_tool") is None

    def test_full_attack_chain(self):
        """Simulate: web_fetch → taint → bash_tool blocked."""
        tracker = TaintTracker()
        tracker.record_tool_output("web_fetch_tool")
        assert TaintLabel.EXTERNAL_NETWORK in tracker.check_sink("bash_tool")
        assert TaintLabel.EXTERNAL_NETWORK in tracker.check_sink("file_write_tool")
        assert tracker.check_sink("web_search_tool") is None

    def test_multiple_labels(self):
        tracker = TaintTracker()
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        tracker.record(TaintLabel.SECRET)
        assert len(tracker.labels) == 2
        assert TaintLabel.EXTERNAL_NETWORK in tracker.check_sink("bash_tool")


class TestContextVar:
    def test_get_creates_new(self):
        reset_taint_tracker()
        tracker = get_taint_tracker()
        assert isinstance(tracker, TaintTracker)
        assert not tracker.is_tainted

    def test_get_returns_same(self):
        reset_taint_tracker()
        t1 = get_taint_tracker()
        t2 = get_taint_tracker()
        assert t1 is t2

    def test_reset_clears_state(self):
        reset_taint_tracker()
        tracker = get_taint_tracker()
        tracker.record(TaintLabel.EXTERNAL_NETWORK)
        assert tracker.is_tainted

        reset_taint_tracker()
        new_tracker = get_taint_tracker()
        assert not new_tracker.is_tainted
        assert new_tracker is not tracker

def test_record_tool_output_invalid_label():
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.agent.security.guards.taint_tracker import TaintTracker

    tracker = TaintTracker()
    with patch("myrm_agent_harness.agent.security.tool_registry.resolve_safety_metadata") as mock_resolve:
        mock_meta = MagicMock()
        mock_meta.taint_label = "invalid_label_xyz"
        mock_resolve.return_value = mock_meta

        tracker.record_tool_output("some_tool")
        assert not tracker.labels

def test_record_tool_output_extractor_exception():
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.agent.security.guards.taint_tracker import TaintLabel, TaintTracker

    tracker = TaintTracker()
    with patch("myrm_agent_harness.agent.security.tool_registry.resolve_safety_metadata") as mock_resolve:
        mock_meta = MagicMock()
        mock_meta.taint_label = "external_network"
        def bad_extractor(args):
            raise ValueError("extractor failed")
        mock_meta.taint_extractor = bad_extractor
        mock_resolve.return_value = mock_meta

        tracker.record_tool_output("some_tool", {"url": "http://example.com"})

        assert TaintLabel.EXTERNAL_NETWORK in tracker.labels
        assert tracker._taints[TaintLabel.EXTERNAL_NETWORK] == set()

def test_record_tool_output_string_extractor():
    from unittest.mock import MagicMock, patch

    from myrm_agent_harness.agent.security.guards.taint_tracker import TaintLabel, TaintTracker

    tracker = TaintTracker()
    with patch("myrm_agent_harness.agent.security.tool_registry.resolve_safety_metadata") as mock_resolve:
        mock_meta = MagicMock()
        mock_meta.taint_label = "external_network"
        mock_meta.taint_extractor = "url"
        mock_resolve.return_value = mock_meta

        tracker.record_tool_output("some_tool", {"url": "http://example.com"})

        assert TaintLabel.EXTERNAL_NETWORK in tracker.labels
        assert "http://example.com" in tracker._taints[TaintLabel.EXTERNAL_NETWORK]

def test_get_taint_tracker_lookup_error():
    import contextvars

    from myrm_agent_harness.agent.security.guards.taint_tracker import _taint_tracker_var, get_taint_tracker

    # Create a new context to force LookupError
    ctx = contextvars.Context()
    def run_in_ctx():
        tracker = get_taint_tracker()
        assert tracker is not None
        assert _taint_tracker_var.get() is tracker

    ctx.run(run_in_ctx)

def test_add_taint_duplicate_source():
    from myrm_agent_harness.agent.security.guards.taint_tracker import TaintLabel, TaintTracker
    tracker = TaintTracker()
    tracker.record(TaintLabel.EXTERNAL_NETWORK, "src1")
    tracker.record(TaintLabel.EXTERNAL_NETWORK, "src1")
    assert tracker._taints[TaintLabel.EXTERNAL_NETWORK] == {"src1"}
