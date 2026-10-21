"""Tests for toolkits.llms.fallback.probe_throttle — global probe throttling."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.fallback.probe_throttle import (
    GlobalProbeThrottle,
    get_global_probe_throttle,
)


class TestGlobalProbeThrottle:
    def test_first_probe_allowed(self) -> None:
        t = GlobalProbeThrottle(min_interval_ms=1000)
        assert t.should_probe("model-a", now_ms=100_000) is True

    def test_second_probe_throttled(self) -> None:
        t = GlobalProbeThrottle(min_interval_ms=1000)
        t.should_probe("model-a", now_ms=100_000)
        assert t.should_probe("model-a", now_ms=100_500) is False

    def test_probe_after_interval(self) -> None:
        t = GlobalProbeThrottle(min_interval_ms=1000)
        t.should_probe("model-a", now_ms=100_000)
        assert t.should_probe("model-a", now_ms=101_001) is True

    def test_different_models_independent(self) -> None:
        t = GlobalProbeThrottle(min_interval_ms=1000)
        t.should_probe("model-a", now_ms=100_000)
        assert t.should_probe("model-b", now_ms=100_000) is True

    def test_prune_expired(self) -> None:
        t = GlobalProbeThrottle(min_interval_ms=100, ttl_ms=500)
        t.should_probe("old-model", now_ms=100_000)
        t.should_probe("new-model", now_ms=100_600)
        assert "old-model" not in t._last_probe

    def test_enforce_max_entries(self) -> None:
        t = GlobalProbeThrottle(min_interval_ms=0, max_entries=3)
        for i in range(5):
            t.should_probe(f"model-{i}", now_ms=100_000 + float(i * 1000))
        assert len(t._last_probe) <= 3

    def test_clear(self) -> None:
        t = GlobalProbeThrottle()
        t.should_probe("model-a", now_ms=100_000)
        t.clear()
        assert len(t._last_probe) == 0
        assert t.should_probe("model-a", now_ms=100_000) is True


class TestGetGlobalThrottle:
    def test_returns_singleton(self) -> None:
        a = get_global_probe_throttle()
        b = get_global_probe_throttle()
        assert a is b
