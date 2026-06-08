"""Tests for global probe throttle — throttling, TTL, max entries, thread safety.

Covers: probe interval enforcement, TTL-based expiry, max entry enforcement,
clear, thread safety, and global singleton.
"""

from __future__ import annotations

import threading

import pytest

from myrm_agent_harness.toolkits.llms.fallback.probe_throttle import (
    GlobalProbeThrottle,
    get_global_probe_throttle,
)


class TestProbeThrottleInit:
    def test_default_params(self):
        pt = GlobalProbeThrottle()
        assert pt.min_interval_ms == 30_000
        assert pt.max_entries == 256

    def test_custom_params(self):
        pt = GlobalProbeThrottle(min_interval_ms=1000, max_entries=10)
        assert pt.min_interval_ms == 1000
        assert pt.max_entries == 10


class TestShouldProbe:
    def test_first_probe_allowed(self):
        pt = GlobalProbeThrottle(min_interval_ms=1000)
        assert pt.should_probe("model-a", now_ms=10000.0) is True

    def test_second_probe_throttled(self):
        pt = GlobalProbeThrottle(min_interval_ms=1000)
        pt.should_probe("model-a", now_ms=10000.0)
        assert pt.should_probe("model-a", now_ms=10500.0) is False

    def test_probe_after_interval(self):
        pt = GlobalProbeThrottle(min_interval_ms=1000)
        pt.should_probe("model-a", now_ms=10000.0)
        assert pt.should_probe("model-a", now_ms=11500.0) is True

    def test_different_models_independent(self):
        pt = GlobalProbeThrottle(min_interval_ms=1000)
        pt.should_probe("model-a", now_ms=10000.0)
        assert pt.should_probe("model-b", now_ms=10000.0) is True

    def test_boundary_exactly_at_interval(self):
        pt = GlobalProbeThrottle(min_interval_ms=1000)
        pt.should_probe("model-a", now_ms=10000.0)
        assert pt.should_probe("model-a", now_ms=11000.0) is True


class TestTTLExpiry:
    def test_expired_entries_pruned(self):
        pt = GlobalProbeThrottle(min_interval_ms=100, ttl_ms=500)
        pt.should_probe("old-model", now_ms=1000.0)
        # After TTL, entry should be expired
        assert pt.should_probe("old-model", now_ms=2000.0) is True


class TestMaxEntries:
    def test_evicts_oldest(self):
        pt = GlobalProbeThrottle(min_interval_ms=100, max_entries=3)
        pt.should_probe("a", now_ms=1000.0)
        pt.should_probe("b", now_ms=2000.0)
        pt.should_probe("c", now_ms=3000.0)
        pt.should_probe("d", now_ms=4000.0)  # should evict "a"
        # "a" was evicted so it should be allowed again
        assert pt.should_probe("a", now_ms=4100.0) is True


class TestClear:
    def test_clear_allows_reprobe(self):
        pt = GlobalProbeThrottle(min_interval_ms=100_000)
        base_ms = 200_000.0
        assert pt.should_probe("model-a", now_ms=base_ms) is True
        assert pt.should_probe("model-a", now_ms=base_ms + 1) is False
        pt.clear()
        # After clear, _last_probe is empty; default is 0, so (now_ms - 0) must > interval
        assert pt.should_probe("model-a", now_ms=base_ms + 2) is True


class TestGlobalSingleton:
    def test_returns_same_instance(self):
        a = get_global_probe_throttle()
        b = get_global_probe_throttle()
        assert a is b

    def test_is_probe_throttle(self):
        assert isinstance(get_global_probe_throttle(), GlobalProbeThrottle)


class TestThreadSafety:
    def test_concurrent_probes(self):
        pt = GlobalProbeThrottle(min_interval_ms=1)
        errors: list[Exception] = []

        def hammer():
            try:
                for i in range(50):
                    pt.should_probe(f"model-{i % 5}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
