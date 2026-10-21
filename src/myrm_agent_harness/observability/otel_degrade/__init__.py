"""
[INPUT]: OtelPostureState, OtelDegradeStatus, NoOpSpan, NoOpTracer, NoOpMeter, GracefulOtelRuntime.
[OUTPUT]: Public exports for OpenTelemetry graceful degrade and zero hard-dependency primitives.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/otel_degrade/__init__.py
"""

from .models import OtelDegradeStatus, OtelPostureState
from .runtime import (
    GracefulOtelRuntime,
    NoOpCounter,
    NoOpMeter,
    NoOpSpan,
    NoOpTracer,
)

__all__ = [
    "OtelPostureState",
    "OtelDegradeStatus",
    "NoOpSpan",
    "NoOpTracer",
    "NoOpCounter",
    "NoOpMeter",
    "GracefulOtelRuntime",
]
