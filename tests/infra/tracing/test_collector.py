"""Tests for myrm_agent_harness.infra.tracing.metrics.collector."""

from __future__ import annotations

from unittest.mock import MagicMock

from opentelemetry.metrics import Meter

from myrm_agent_harness.infra.tracing.metrics.collector import MetricsCollector


def _make_meter() -> tuple[Meter, MagicMock, MagicMock, MagicMock]:
    meter = MagicMock(spec=Meter)
    counter = MagicMock()
    gauge = MagicMock()
    histogram = MagicMock()
    meter.create_counter.return_value = counter
    meter.create_gauge.return_value = gauge
    meter.create_histogram.return_value = histogram
    return meter, counter, gauge, histogram


def test_counter_creates_and_records() -> None:
    meter, counter, _, _ = _make_meter()
    col = MetricsCollector(meter)
    col.counter("c1", 2, {"k": "v"})
    meter.create_counter.assert_called_once_with("c1")
    counter.add.assert_called_once_with(2, attributes={"k": "v"})


def test_gauge_creates_and_records() -> None:
    meter, _, gauge, _ = _make_meter()
    col = MetricsCollector(meter)
    col.gauge("g1", 3.5, None)
    meter.create_gauge.assert_called_once_with("g1")
    gauge.record.assert_called_once_with(3.5, attributes={})


def test_histogram_creates_and_records() -> None:
    meter, _, _, histogram = _make_meter()
    col = MetricsCollector(meter)
    col.histogram("h1", 9.0, {"a": "b"})
    meter.create_histogram.assert_called_once_with("h1")
    histogram.record.assert_called_once_with(9.0, attributes={"a": "b"})


def test_same_name_reuses_cached_instruments() -> None:
    meter, counter, _, _ = _make_meter()
    col = MetricsCollector(meter)
    col.counter("same", 1, None)
    col.counter("same", 2, None)
    meter.create_counter.assert_called_once_with("same")
    assert counter.add.call_count == 2
