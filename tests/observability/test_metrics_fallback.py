"""Test metrics factory fallback paths when prometheus_client is unavailable.

Covers the degraded (no-op) behavior that keeps the framework importable and
safe on core-only environments, including the module-level import fallback.
"""

from __future__ import annotations

from unittest import mock

import pytest

pytest.importorskip("prometheus_client")

from myrm_agent_harness.observability import metrics


def test_require_prometheus_raises_when_unavailable() -> None:
    """_require_prometheus raises RuntimeError when prometheus_client is missing."""
    with (
        mock.patch.object(metrics, "PROMETHEUS_AVAILABLE", False),
        pytest.raises(RuntimeError, match="prometheus_client is required"),
    ):
        metrics._require_prometheus("example_counter")


def test_factories_return_none_when_unavailable() -> None:
    """create_* factories return None instead of raising without prometheus_client."""
    with mock.patch.object(metrics, "PROMETHEUS_AVAILABLE", False):
        assert metrics.create_counter("fallback_total", "Test") is None
        assert metrics.create_gauge("fallback_gauge", "Test") is None
        assert metrics.create_histogram("fallback_duration_seconds", "Test") is None


def test_get_or_create_returns_noop_when_unavailable() -> None:
    """get_or_create_* return a no-op metric that never raises."""
    with mock.patch.object(metrics, "PROMETHEUS_AVAILABLE", False):
        counter = metrics.get_or_create_counter("fallback_counter_total", "Test")
        hist = metrics.get_or_create_histogram("fallback_histogram_seconds", "Test", labelnames=("kind",))
        assert isinstance(counter, metrics._NoOpMetric)
        assert isinstance(hist, metrics._NoOpMetric)
        counter.inc()
        counter.inc(3)
        counter.labels(kind="x").inc()
        hist.observe(2.0)
        hist.labels(kind="x").observe(1.0)


def test_module_import_fallback_without_prometheus_client() -> None:
    """The module imports cleanly when prometheus_client cannot be imported."""
    import importlib

    real_import = __import__

    def _block_prometheus(name: str, *args: object, **kwargs: object) -> object:
        if name == "prometheus_client":
            raise ImportError("prometheus_client blocked for test")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=_block_prometheus):
        importlib.reload(metrics)
        assert metrics.PROMETHEUS_AVAILABLE is False
        assert metrics.create_counter("probe_total", "p") is None
        noop = metrics.get_or_create_counter("probe_noop_total", "p")
        noop.inc()

    importlib.reload(metrics)
    assert metrics.PROMETHEUS_AVAILABLE is True
