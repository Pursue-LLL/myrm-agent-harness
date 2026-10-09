"""Isolation for the process-global tracer and meter provider state used by the tracing tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from myrm_agent_harness.infra.tracing import tracer
from myrm_agent_harness.infra.tracing.metrics import exporter as metrics_exporter


def _reset_observability_singletons() -> None:
    tracer._initialized = False
    tracer._tracer_provider = None
    metrics_exporter._initialized = False
    metrics_exporter._meter_provider = None


@pytest.fixture(autouse=True, scope="module")
def _isolate_observability_singletons() -> Iterator[None]:
    """Hand the tracer and meter singletons back uninitialised when a module here finishes.

    ``setup_tracing``/``setup_metrics`` and several tests in this directory set the module-level
    ``_initialized`` flags (some with mock providers) and rely on a trailing shutdown to clear them.
    A failed assertion skips that shutdown, and ``test_concurrent_flush_observability_dual_channel``
    never shuts down at all, so the next module on the same xdist worker would inherit
    "tracing connected" (``GatewayHealthInspector.check_otlp_posture`` reads these flags).
    """
    _reset_observability_singletons()
    yield
    _reset_observability_singletons()
