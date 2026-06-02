"""Tests for myrm_agent_harness.utils.token_economics.tracker."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

import myrm_agent_harness.utils.token_economics.tracker as tt
from myrm_agent_harness.utils.token_economics.cache_economics import compute_prompt_cache_stats


def _cleanup_module_state() -> None:
    tt.reset_token_tracker()
    tt._TOKEN_TRACKING_CALLBACK_CLASS = None
    if "TokenTrackingCallback" in tt.__dict__:
        del tt.__dict__["TokenTrackingCallback"]


@pytest.fixture(autouse=True)
def _reset_token_tracker_autouse() -> None:
    _cleanup_module_state()
    yield
    _cleanup_module_state()


@pytest.fixture
def litellm_stub() -> types.ModuleType:
    saved: dict[str, types.ModuleType] = {}
    keys = (
        "litellm",
        "litellm.integrations",
        "litellm.integrations.custom_logger",
    )
    for k in keys:
        if k in sys.modules:
            saved[k] = sys.modules.pop(k)

    class CustomLogger:
        pass

    litellm_mod = types.ModuleType("litellm")
    litellm_mod.callbacks = []
    litellm_mod.completion_cost = lambda **kwargs: 0.001
    integ = types.ModuleType("litellm.integrations")
    cl = types.ModuleType("litellm.integrations.custom_logger")
    cl.CustomLogger = CustomLogger
    integ.custom_logger = cl
    litellm_mod.integrations = integ

    for k, mod in (
        ("litellm", litellm_mod),
        ("litellm.integrations", integ),
        ("litellm.integrations.custom_logger", cl),
    ):
        sys.modules[k] = mod

    yield litellm_mod

    for k in keys:
        sys.modules.pop(k, None)
    for k, v in saved.items():
        sys.modules[k] = v


class TestTokenUsageAdd:
    def test_add_basic_accumulation(self) -> None:
        u = tt.TokenUsage()
        u.add({"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        u.add({"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9})
        assert u.prompt_tokens == 5
        assert u.completion_tokens == 7
        assert u.total_tokens == 12

    def test_add_none_like_values(self) -> None:
        u = tt.TokenUsage()
        u.add(
            {
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }
        )
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_add_cached_via_prompt_tokens_details(self) -> None:
        u = tt.TokenUsage()
        u.add({"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 3}})
        assert u.cached_tokens == 3

    def test_add_reasoning_via_completion_tokens_details(self) -> None:
        u = tt.TokenUsage()
        u.add({"completion_tokens_details": {"reasoning_tokens": 7}})
        assert u.reasoning_tokens == 7

    def test_add_reasoning_top_level_when_details_empty(self) -> None:
        u = tt.TokenUsage()
        u.add({"completion_tokens_details": {}, "reasoning_tokens": 11})
        assert u.reasoning_tokens == 11

    def test_add_skips_non_dict_prompt_tokens_details(self) -> None:
        u = tt.TokenUsage()
        u.add({"prompt_tokens_details": None, "prompt_tokens": 1})
        assert u.cached_tokens == 0

    def test_add_skips_non_dict_completion_tokens_details_uses_top(self) -> None:
        u = tt.TokenUsage()
        u.add({"completion_tokens_details": None, "reasoning_tokens": 4})
        assert u.reasoning_tokens == 4


class TestTokenUsageToDictAndCache:
    def test_to_dict(self) -> None:
        u = tt.TokenUsage(
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
            cached_tokens=4,
            reasoning_tokens=5,
        )
        assert u.to_dict() == {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
            "cached_tokens": 4,
            "cache_write_tokens": 0,
            "reasoning_tokens": 5,
            "citation_tokens": 0,
        }

    def test_get_cache_effectiveness_zero_prompt(self) -> None:
        u = tt.TokenUsage()
        assert compute_prompt_cache_stats(0, 0) == u.get_cache_effectiveness()

    def test_get_cache_effectiveness_non_trivial(self) -> None:
        u = tt.TokenUsage(prompt_tokens=100, cached_tokens=50)
        stats = u.get_cache_effectiveness()
        assert stats["cache_hit_rate"] == 0.5
        assert "cost_savings_pct" in stats
        assert "cost_savings_absolute" in stats


class TestTokenTracker:
    def test_record_usage_call_count_and_pending(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        assert tr.call_count == 1
        assert len(tr.pending_events) == 1
        assert tr.pending_events[0]["call_index"] == 1
        assert tr.pending_events[0]["usage"] == tr.usage.to_dict()

        tr.record({"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2})
        assert tr.call_count == 2
        assert tr.pending_events[1]["call_index"] == 2
        assert tr.pending_events[1]["usage"]["prompt_tokens"] == 3

    def test_get_usage(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 5})
        assert tr.get_usage() is tr.usage

    def test_get_and_clear_pending_events(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 1})
        ev = tr.get_and_clear_pending_events()
        assert len(ev) == 1
        assert tr.pending_events == []
        assert tr.get_and_clear_pending_events() == []

    def test_model_usage_breakdown(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 10, "completion_tokens": 5}, model_name="gpt-4o")
        tr.record({"prompt_tokens": 20, "completion_tokens": 10}, model_name="claude-3.5")
        tr.record({"prompt_tokens": 5, "completion_tokens": 3}, model_name="gpt-4o")
        assert "gpt-4o" in tr.model_usage
        assert "claude-3.5" in tr.model_usage
        assert tr.model_usage["gpt-4o"].prompt_tokens == 15
        assert tr.model_usage["claude-3.5"].prompt_tokens == 20

    def test_cost_accumulation(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 10}, cost_usd=0.001)
        tr.record({"prompt_tokens": 20}, cost_usd=0.002)
        assert tr.total_cost_usd == 0.003

    def test_latency_stats(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"completion_tokens": 100}, duration_ms=100.0, ttft_ms=10.0)
        tr.record({"completion_tokens": 200}, duration_ms=200.0, ttft_ms=20.0)
        stats = tr.get_latency_stats()
        assert stats.call_count == 2
        assert stats.avg_ms == 150.0
        assert stats.min_ms == 100.0
        assert stats.max_ms == 200.0
        assert stats.avg_ttft_ms == 15.0
        assert stats.avg_tokens_per_second > 0

    def test_latency_stats_empty(self) -> None:
        tr = tt.TokenTracker()
        stats = tr.get_latency_stats()
        assert stats.call_count == 0
        assert stats.avg_ms == 0.0

    def test_error_tracking(self) -> None:
        tr = tt.TokenTracker()
        tr.record_error("timeout")
        tr.record_error("rate_limit")
        assert tr.error_count == 2
        assert tr.last_error == "rate_limit"

    def test_merge(self) -> None:
        parent = tt.TokenTracker()
        parent.record(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            model_name="gpt-4o",
            cost_usd=0.01,
            duration_ms=100.0,
        )

        child = tt.TokenTracker()
        child.record(
            {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            model_name="claude-3.5",
            cost_usd=0.02,
            duration_ms=200.0,
        )
        child.record_error("test_error")

        parent.merge(child)
        assert parent.usage.prompt_tokens == 30
        assert parent.usage.completion_tokens == 15
        assert parent.call_count == 2
        assert parent.total_cost_usd == 0.03
        assert parent.error_count == 1
        assert "gpt-4o" in parent.model_usage
        assert "claude-3.5" in parent.model_usage
        assert len(parent.call_durations_ms) == 2

    def test_merge_cost_status_upgrade(self) -> None:
        parent = tt.TokenTracker()
        parent.record({"prompt_tokens": 10}, cost_status="unknown")
        assert parent.cost_status == "unknown"

        child = tt.TokenTracker()
        child.record({"prompt_tokens": 20}, cost_usd=0.01, cost_status="actual")

        parent.merge(child)
        assert parent.cost_status == "actual"

        parent2 = tt.TokenTracker()
        parent2.record({"prompt_tokens": 10}, cost_status="estimated")
        child2 = tt.TokenTracker()
        child2.record({"prompt_tokens": 5}, cost_status="unknown")
        parent2.merge(child2)
        assert parent2.cost_status == "estimated"

    def test_to_dict_complete(self) -> None:
        tr = tt.TokenTracker()
        tr.record(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            model_name="gpt-4o",
            cost_usd=0.001,
            duration_ms=100.0,
            ttft_ms=10.0,
        )
        d = tr.to_dict()
        assert d["call_count"] == 1
        assert d["total_cost_usd"] == 0.001
        assert "latency" in d
        assert "model_breakdown" in d
        assert d["model_breakdown"]["gpt-4o"]["prompt_tokens"] == 10

    def test_pending_event_includes_model_and_cost(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 10}, model_name="test-model", cost_usd=0.005)
        events = tr.get_and_clear_pending_events()
        assert events[0]["model_name"] == "test-model"
        assert events[0]["cost_usd"] == 0.005

    def test_last_call_snapshot(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        tr.record({"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30})
        last = tr.usage.last_call
        assert last is not None
        assert last.prompt_tokens == 20
        assert last.completion_tokens == 10

    def test_cache_write_tokens_extraction(self) -> None:
        tr = tt.TokenTracker()
        tr.record({"prompt_tokens": 100, "cache_creation_input_tokens": 50})
        assert tr.usage.cache_write_tokens == 50


class TestModuleLevelApi:
    def test_init_get_reset(self) -> None:
        assert tt.get_token_tracker() is None
        a = tt.init_token_tracker()
        assert tt.get_token_tracker() is a
        tt.reset_token_tracker()
        assert tt.get_token_tracker() is None

    def test_record_token_usage_and_pending(self) -> None:
        tt.init_token_tracker()
        tt.record_token_usage({"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3})
        events = tt.get_pending_token_events()
        assert len(events) == 1
        assert events[0]["call_index"] == 1
        assert tt.get_pending_token_events() == []

    def test_record_token_usage_without_tracker(self) -> None:
        tt.record_token_usage({"prompt_tokens": 99})

    def test_record_finish_reason(self) -> None:
        tt.init_token_tracker()
        tt.record_finish_reason("stop")
        assert cast(tt.TokenTracker, tt.get_token_tracker()).last_finish_reason == "stop"
        tt.record_finish_reason("length")
        assert cast(tt.TokenTracker, tt.get_token_tracker()).last_finish_reason == "length"

    def test_get_pending_token_events_no_tracker(self) -> None:
        assert tt.get_pending_token_events() == []


class TestLiteLLMCallback:
    def test_get_token_tracking_callback_class_lazy_and_cached(self, litellm_stub: types.ModuleType) -> None:
        c1 = tt._get_token_tracking_callback_class()
        c2 = tt._get_token_tracking_callback_class()
        assert c1 is c2

    def test_setup_token_tracking_callback_registers(self, litellm_stub: types.ModuleType) -> None:
        cls = tt._get_token_tracking_callback_class()
        tt.setup_token_tracking_callback()
        assert len(litellm_stub.callbacks) == 1
        assert isinstance(litellm_stub.callbacks[0], cls)

    def test_getattr_token_tracking_callback_deferred_export(self, litellm_stub: types.ModuleType) -> None:
        cls = tt.TokenTrackingCallback
        assert cls is tt._get_token_tracking_callback_class()
        assert tt.TokenTrackingCallback is cls

    def test_getattr_unknown_raises(self) -> None:
        with pytest.raises(AttributeError, match=r"has no attribute 'MissingAttr'"):
            tt.MissingAttr

    def test_log_success_event_non_streaming_dict_usage(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        resp = SimpleNamespace(usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7})
        cb.log_success_event({"stream": False}, resp, None, None)
        assert cast(tt.TokenTracker, tt.get_token_tracker()).usage.prompt_tokens == 3

    def test_log_success_event_skips_streaming(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        resp = SimpleNamespace(usage={"prompt_tokens": 9})
        cb.log_success_event({"stream": True}, resp, None, None)
        assert cast(tt.TokenTracker, tt.get_token_tracker()).usage.prompt_tokens == 0

    def test_log_success_event_model_dump_path(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()

        class UsageModel:
            def model_dump(self) -> dict[str, int]:
                return {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}

        resp = SimpleNamespace(usage=UsageModel())
        cb.log_success_event({}, resp, None, None)
        assert cast(tt.TokenTracker, tt.get_token_tracker()).usage.total_tokens == 3

    def test_log_success_event_attr_fallback(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        usage_obj = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        resp = SimpleNamespace(usage=usage_obj)
        cb.log_success_event({}, resp, None, None)
        u = cast(tt.TokenTracker, tt.get_token_tracker()).usage
        assert u.prompt_tokens == 10 and u.total_tokens == 30

    def test_log_success_event_empty_usage_no_record(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        resp = SimpleNamespace()
        cb.log_success_event({}, resp, None, None)
        assert cast(tt.TokenTracker, tt.get_token_tracker()).call_count == 0

    def test_log_success_event_usage_attr_none(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        resp = SimpleNamespace(usage=None)
        cb.log_success_event({}, resp, None, None)
        assert cast(tt.TokenTracker, tt.get_token_tracker()).call_count == 0

    def test_setup_token_tracking_callback_skips_if_callback_already_in_list(
        self, monkeypatch: pytest.MonkeyPatch, litellm_stub: types.ModuleType
    ) -> None:
        cls = tt._get_token_tracking_callback_class()
        shared = cls()

        def _new(_cls: type[object]) -> object:
            return shared

        monkeypatch.setattr(cls, "__new__", _new)
        litellm_stub.callbacks.append(shared)
        tt.setup_token_tracking_callback()
        assert len(litellm_stub.callbacks) == 1

    def test_is_streaming_call(self, litellm_stub: types.ModuleType) -> None:
        cb = tt._get_token_tracking_callback_class()()
        assert cb._is_streaming_call({"stream": True}) is True
        assert cb._is_streaming_call({"stream": False}) is False

    @pytest.mark.asyncio
    async def test_async_log_success_event_delegates(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        resp = SimpleNamespace(usage={"prompt_tokens": 1})
        mock = MagicMock(wraps=cb.log_success_event)
        cb.log_success_event = mock
        await cb.async_log_success_event({"stream": False}, resp, 1.0, 2.0)
        mock.assert_called_once_with({"stream": False}, resp, 1.0, 2.0)

    @pytest.mark.asyncio
    async def test_async_log_success_event_records(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        resp = SimpleNamespace(usage={"prompt_tokens": 5})
        await cb.async_log_success_event({}, resp, None, None)
        assert cast(tt.TokenTracker, tt.get_token_tracker()).usage.prompt_tokens == 5

    def test_log_failure_event(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        cb.log_failure_event({"exception": ValueError("rate limit")}, None, None, None)
        tracker = cast(tt.TokenTracker, tt.get_token_tracker())
        assert tracker.error_count == 1
        assert "rate limit" in (tracker.last_error or "")

    @pytest.mark.asyncio
    async def test_async_log_failure_event(self, litellm_stub: types.ModuleType) -> None:
        tt.init_token_tracker()
        cb = tt._get_token_tracking_callback_class()()
        await cb.async_log_failure_event({"exception": RuntimeError("timeout")}, None, None, None)
        tracker = cast(tt.TokenTracker, tt.get_token_tracker())
        assert tracker.error_count == 1


class TestCoerceEdgeCases:
    def test_coerce_float(self) -> None:
        from myrm_agent_harness.utils.coercion import parse_int

        assert parse_int(3.7, 0, min_val=0) == 3
        assert parse_int(-1.5, 0, min_val=0) == 0

    def test_coerce_nan(self) -> None:
        from myrm_agent_harness.utils.coercion import parse_int

        assert parse_int(float("nan"), 0, min_val=0) == 0

    def test_coerce_bool(self) -> None:
        from myrm_agent_harness.utils.coercion import parse_int

        assert parse_int(True, 0, min_val=0) == 0
        assert parse_int(False, 0, min_val=0) == 0

    def test_coerce_string(self) -> None:
        from myrm_agent_harness.utils.coercion import parse_int

        assert parse_int("123", 0, min_val=0) == 123
        assert parse_int("abc", 0, min_val=0) == 0


class TestToolContextModuleLevel:
    def test_push_pop_with_tracker(self) -> None:
        tt.init_token_tracker()
        tt.push_tool_context("search")
        tracker = cast(tt.TokenTracker, tt.get_token_tracker())
        assert tracker.tool_stack == ["search"]
        tt.pop_tool_context()
        assert tracker.tool_stack == []

    def test_push_pop_without_tracker(self) -> None:
        tt.push_tool_context("search")
        tt.pop_tool_context()

    def test_record_error_module_level(self) -> None:
        tt.init_token_tracker()
        tt.record_token_error("test error")
        tracker = cast(tt.TokenTracker, tt.get_token_tracker())
        assert tracker.error_count == 1

    def test_record_error_without_tracker(self) -> None:
        tt.record_token_error("no tracker")

    def test_record_finish_reason_without_tracker(self) -> None:
        tt.record_finish_reason("stop")


class TestSemanticAliases:
    def test_input_output_net_input(self) -> None:
        u = tt.TokenUsage(prompt_tokens=100, completion_tokens=50, cached_tokens=30)
        assert u.input_tokens == 100
        assert u.output_tokens == 50
        assert u.net_input_tokens == 70


class TestToolUsageMerge:
    def test_merge_tool_usage(self) -> None:
        parent = tt.TokenTracker()
        parent.push_tool("search")
        parent.record({"prompt_tokens": 10, "completion_tokens": 5})
        parent.pop_tool()

        child = tt.TokenTracker()
        child.push_tool("search")
        child.record({"prompt_tokens": 20, "completion_tokens": 10})
        child.pop_tool()

        parent.merge(child)
        assert "search" in parent.tool_usage
        assert parent.tool_usage["search"].prompt_tokens == 30

    def test_merge_new_tool_from_child(self) -> None:
        parent = tt.TokenTracker()

        child = tt.TokenTracker()
        child.push_tool("browser")
        child.record({"prompt_tokens": 15})
        child.pop_tool()

        parent.merge(child)
        assert "browser" in parent.tool_usage
        assert parent.tool_usage["browser"].prompt_tokens == 15


class TestTrimList:
    def test_trim_triggers_on_threshold(self) -> None:
        data: list[float] = list(range(1001))
        tt._trim_list(data)
        assert len(data) <= 501


class TestCitationTopLevel:
    def test_citation_tokens_top_level_fallback(self) -> None:
        u = tt.TokenUsage()
        u.add({"prompt_tokens": 100, "citation_tokens": 15})
        assert u.citation_tokens == 15


class TestAppendToLedger:
    def test_append_without_ledger(self) -> None:
        tt.append_to_ledger({"prompt_tokens": 10}, "gpt-4o", 100.0, 0.001)

    def test_append_with_ledger(self) -> None:
        tt.init_token_tracker()
        mock_ledger = MagicMock()
        tt.set_usage_ledger(mock_ledger)
        tt.append_to_ledger({"prompt_tokens": 10}, "gpt-4o", 100.0, 0.001)
        mock_ledger.append.assert_called_once()
        assert tt.get_usage_ledger() is mock_ledger


