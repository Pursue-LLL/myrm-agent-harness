"""Meter provider for metrics collection.

Provides access to OpenTelemetry Meter instances for creating metrics.

[INPUT]
- opentelemetry.metrics (POS: Metrics API)

[OUTPUT]
- get_meter: 获取 Meter 实例

[POS]
Meter provider. Wraps OpenTelemetry Meter acquisition logic.

"""

from __future__ import annotations

from opentelemetry.metrics import Meter, get_meter_provider


def get_meter(name: str, version: str = "1.0.0") -> Meter:
    """Get a Meter instance for creating metrics.

    Args:
        name: Meter name (typically module name)
        version: Meter version

    Returns:
        Meter instance
    """
    return get_meter_provider().get_meter(name, version)
