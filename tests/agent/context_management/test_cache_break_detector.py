"""Unit tests for cache_break_detector module."""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
    CacheBreakDetector,
    _compute_system_prompt_hash,
    _compute_tool_hashes,
    _diff_tool_hashes,
    get_cache_break_detector,
    init_cache_break_detector,
    reset_cache_break_detector,
)


class TestComputeSystemPromptHash:
    def test_single_system_message(self) -> None:
        msgs = [SystemMessage(content="You are helpful")]
        h1 = _compute_system_prompt_hash(msgs)
        h2 = _compute_system_prompt_hash(msgs)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_content_different_hash(self) -> None:
        h1 = _compute_system_prompt_hash([SystemMessage(content="A")])
        h2 = _compute_system_prompt_hash([SystemMessage(content="B")])
        assert h1 != h2

    def test_no_system_messages(self) -> None:
        h = _compute_system_prompt_hash([HumanMessage(content="hello")])
        assert len(h) == 64

    def test_multiple_system_messages(self) -> None:
        msgs = [SystemMessage(content="A"), SystemMessage(content="B")]
        h1 = _compute_system_prompt_hash(msgs)
        msgs2 = [SystemMessage(content="A"), SystemMessage(content="C")]
        h2 = _compute_system_prompt_hash(msgs2)
        assert h1 != h2


class TestComputeToolHashes:
    def test_basic(self) -> None:
        tools = [("bash", '{"type":"object"}'), ("read", '{"type":"object"}')]
        agg, per = _compute_tool_hashes(tools)
        assert len(agg) == 64
        assert "bash" in per
        assert "read" in per

    def test_order_independent(self) -> None:
        tools1 = [("bash", '{"a":1}'), ("read", '{"b":2}')]
        tools2 = [("read", '{"b":2}'), ("bash", '{"a":1}')]
        agg1, _ = _compute_tool_hashes(tools1)
        agg2, _ = _compute_tool_hashes(tools2)
        assert agg1 == agg2

    def test_schema_change_detected(self) -> None:
        tools1 = [("bash", '{"v":1}')]
        tools2 = [("bash", '{"v":2}')]
        agg1, _ = _compute_tool_hashes(tools1)
        agg2, _ = _compute_tool_hashes(tools2)
        assert agg1 != agg2

    def test_empty(self) -> None:
        agg, per = _compute_tool_hashes([])
        assert len(agg) == 64
        assert per == {}


class TestDiffToolHashes:
    def test_no_changes(self) -> None:
        prev = {"bash": "abc", "read": "def"}
        curr = {"bash": "abc", "read": "def"}
        assert _diff_tool_hashes(prev, curr) == ()

    def test_schema_changed(self) -> None:
        prev = {"bash": "abc", "read": "def"}
        curr = {"bash": "xyz", "read": "def"}
        assert _diff_tool_hashes(prev, curr) == ("bash",)

    def test_tool_added(self) -> None:
        prev = {"bash": "abc"}
        curr = {"bash": "abc", "read": "def"}
        assert _diff_tool_hashes(prev, curr) == ("read",)

    def test_tool_removed(self) -> None:
        prev = {"bash": "abc", "read": "def"}
        curr = {"bash": "abc"}
        assert _diff_tool_hashes(prev, curr) == ("read",)


class TestCacheBreakDetector:
    @pytest.fixture()
    def detector(self) -> CacheBreakDetector:
        return CacheBreakDetector()

    @pytest.fixture()
    def msgs(self) -> list[SystemMessage | HumanMessage | AIMessage]:
        return [
            SystemMessage(content="You are helpful"),
            HumanMessage(content="Hi"),
            AIMessage(content="Hello"),
        ]

    def test_first_call_no_break(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(10000)
        assert event is None

    def test_stable_cache_no_break(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(9800)
        assert event is None

    def test_significant_drop_triggers_break(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)

        msgs2 = [SystemMessage(content="Changed system prompt"), HumanMessage(content="Hi")]
        detector.record_prompt_state(msgs2, "claude-3-sonnet")
        event = detector.check_cache_break(5000)
        assert event is not None
        assert event.prev_cache_read == 10000
        assert event.curr_cache_read == 5000
        assert event.token_drop == 5000
        assert "system prompt changed" in event.reasons
        assert len(event.suggested_actions) > 0
        assert any("dynamic content" in a.lower() for a in event.suggested_actions)

    def test_model_change_attribution(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs, "claude-3-opus")
        event = detector.check_cache_break(0)
        assert event is not None
        assert any("model changed" in r for r in event.reasons)
        assert "claude-3-sonnet" in event.reasons[0]
        assert "claude-3-opus" in event.reasons[0]
        assert len(event.suggested_actions) > 0
        assert any("model" in a.lower() for a in event.suggested_actions)

    def test_tool_count_change(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet", [("bash", "{}")])
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs, "claude-3-sonnet", [("bash", "{}"), ("read", "{}")])
        event = detector.check_cache_break(3000)
        assert event is not None
        assert any("tools changed" in r for r in event.reasons)

    def test_tool_schema_change(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet", [("bash", '{"v":1}')])
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs, "claude-3-sonnet", [("bash", '{"v":2}')])
        event = detector.check_cache_break(3000)
        assert event is not None
        assert any("tool schema changed" in r for r in event.reasons)
        assert any("bash" in r for r in event.reasons)
        assert len(event.suggested_actions) > 0
        assert any("tool" in a.lower() for a in event.suggested_actions)

    def test_compaction_resets_baseline(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        detector.notify_compaction()
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(2000)
        assert event is None

    @patch("myrm_agent_harness.agent.context_management.infra.cache_break_detector.time")
    def test_ttl_5min_attribution(
        self, mock_time: object, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector = CacheBreakDetector()
        mock_time.monotonic = lambda: 0.0  # type: ignore[attr-defined]
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        mock_time.monotonic = lambda: 400.0  # type: ignore[attr-defined]
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(3000)
        assert event is not None
        assert any("5min TTL" in r for r in event.reasons)
        assert len(event.suggested_actions) > 0
        assert any("compaction" in a.lower() for a in event.suggested_actions)

    @patch("myrm_agent_harness.agent.context_management.infra.cache_break_detector.time")
    def test_ttl_1hour_attribution(
        self, mock_time: object, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector = CacheBreakDetector()
        mock_time.monotonic = lambda: 0.0  # type: ignore[attr-defined]
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        mock_time.monotonic = lambda: 4000.0  # type: ignore[attr-defined]
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(3000)
        assert event is not None
        assert any("1h TTL" in r for r in event.reasons)
        assert len(event.suggested_actions) > 0
        assert any("shorter sessions" in a.lower() for a in event.suggested_actions)

    def test_server_side_attribution(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(3000)
        assert event is not None
        assert any("server-side" in r for r in event.reasons)
        assert len(event.suggested_actions) > 0
        assert any("no action needed" in a.lower() for a in event.suggested_actions)

    def test_below_min_token_drop_no_break(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(3000)
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(1500)
        assert event is None

    def test_cache_creation_tokens_recorded(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        msgs2 = [SystemMessage(content="New"), HumanMessage(content="Hi")]
        detector.record_prompt_state(msgs2, "claude-3-sonnet")
        event = detector.check_cache_break(0, cache_creation_tokens=8000)
        assert event is not None
        assert event.cache_creation_tokens == 8000

    def test_multiple_reasons(self, detector: CacheBreakDetector) -> None:
        msgs1 = [SystemMessage(content="A"), HumanMessage(content="Hi")]
        detector.record_prompt_state(msgs1, "model-a", [("bash", "{}")])
        detector.check_cache_break(10000)
        msgs2 = [SystemMessage(content="B"), HumanMessage(content="Hi")]
        detector.record_prompt_state(msgs2, "model-b", [("bash", '{"new":1}'), ("read", "{}")])
        event = detector.check_cache_break(0)
        assert event is not None
        assert len(event.reasons) >= 2

    def test_no_tools_provided(
        self, detector: CacheBreakDetector, msgs: list[SystemMessage | HumanMessage | AIMessage]
    ) -> None:
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs, "claude-3-sonnet")
        event = detector.check_cache_break(9900)
        assert event is None

    def test_pending_changes_cleared_after_check(self, detector: CacheBreakDetector) -> None:
        msgs1 = [SystemMessage(content="A")]
        msgs2 = [SystemMessage(content="B")]
        detector.record_prompt_state(msgs1, "m")
        detector.check_cache_break(10000)
        detector.record_prompt_state(msgs2, "m")
        detector.check_cache_break(9900)
        assert detector._state.pending_changes is None


class TestContextVarLifecycle:
    def test_init_get_reset(self) -> None:
        reset_cache_break_detector()
        assert get_cache_break_detector() is None

        d = init_cache_break_detector()
        assert get_cache_break_detector() is d

        reset_cache_break_detector()
        assert get_cache_break_detector() is None

    def test_independent_instances(self) -> None:
        d1 = init_cache_break_detector()
        d2 = init_cache_break_detector()
        assert d1 is not d2
        assert get_cache_break_detector() is d2
