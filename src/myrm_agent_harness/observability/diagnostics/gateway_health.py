"""Gateway Zero-Payload Redacted Health Export and Runtime Diagnostics Pack.

[INPUT]
- asyncio, time, sys, resource, psutil (Standard library runtime metrics + current process RSS)
- myrm_agent_harness.observability.diagnostics.manager::register_diagnostic (POS: 探针自动注册)
- myrm_agent_harness.observability.diagnostics.protocols::HealthReport (POS: 标准健康检查报告)
- myrm_agent_harness.infra.tracing.tracer::is_tracing_initialized (POS: OTLP trace SDK posture)
- myrm_agent_harness.infra.tracing.metrics.exporter::is_metrics_initialized (POS: OTLP metrics SDK posture)

[OUTPUT]
- GatewayHealthStatus: StrEnum (HEALTHY, DEGRADED, UNHEALTHY)
- GatewayVitals: Immutable dataclass capturing event loop lag, RSS memory, uptime, and active tasks
- GatewayRedactedHealthDTO: Standard zero-payload export contract strictly excluding all user prompts and chat content
- GatewayHealthInspector: Diagnostics engine measuring runtime vitals and OTLP assembly status

[POS]
Harness-level 24/7 gateway health monitor providing pure zero-payload redacted health export and event loop latency probing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

try:
    import resource
except ImportError:
    resource = None  # type: ignore

from myrm_agent_harness.observability.diagnostics.manager import register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

logger = logging.getLogger(__name__)

# Gateway process startup timestamp anchor
_START_TIME = time.time()


class GatewayHealthStatus(StrEnum):
    """Standardized operational status of the gateway runtime."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True, slots=True)
class GatewayVitals:
    """Immutable runtime physical vitals for long-running gateways.

    Attributes:
        event_loop_lag_ms: Observed event loop execution delay in milliseconds.
        memory_rss_mb: Process resident set size (RSS) in megabytes.
        uptime_seconds: Process uptime in seconds.
        active_tasks: Estimated number of concurrent running asyncio tasks.
    """

    event_loop_lag_ms: float
    memory_rss_mb: float
    uptime_seconds: float
    active_tasks: int

    def to_dict(self) -> dict[str, object]:
        """Serialize vitals to clean dictionary."""
        return {
            "event_loop_lag_ms": round(self.event_loop_lag_ms, 2),
            "memory_rss_mb": round(self.memory_rss_mb, 2),
            "uptime_seconds": round(self.uptime_seconds, 1),
            "active_tasks": self.active_tasks,
        }


@dataclass(frozen=True, slots=True)
class GatewayRedactedHealthDTO:
    """Zero-Payload Redacted Health Export Contract.

    Physical Security Invariant:
    This DTO contract strictly contains only service health, numeric vitals,
    and sanitized status diagnostics. It physically excludes prompts, messages,
    tool arguments, return values, and trace spans to guarantee zero data leakage.

    Attributes:
        status: High-level GatewayHealthStatus.
        vitals: GatewayVitals snapshot.
        otlp_endpoint_configured: Whether an OTLP export endpoint is configured.
        otlp_connected: Whether OpenTelemetry tracer/exporter is initialized.
        redacted_diagnostics: Actionable remediation hints and health notes.
    """

    status: GatewayHealthStatus
    vitals: GatewayVitals
    otlp_endpoint_configured: bool
    otlp_connected: bool
    redacted_diagnostics: Sequence[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize safe zero-payload health DTO."""
        return {
            "status": str(self.status),
            "vitals": self.vitals.to_dict(),
            "otlp_endpoint_configured": self.otlp_endpoint_configured,
            "otlp_connected": self.otlp_connected,
            "redacted_diagnostics": list(self.redacted_diagnostics),
        }


class GatewayHealthInspector:
    """Engine measuring runtime event loop latency, memory consumption, and OTLP posture."""

    EVENT_LOOP_WARN_MS = 200.0
    EVENT_LOOP_ERROR_MS = 1000.0
    MEMORY_WARN_MB = 2048.0
    MEMORY_ERROR_MB = 4096.0

    @classmethod
    def get_process_rss_mb(cls) -> float:
        """Measure current process Resident Set Size in megabytes."""
        if psutil is not None:
            try:
                rss_bytes = psutil.Process().memory_info().rss
                return round(rss_bytes / (1024.0 * 1024.0), 2)
            except Exception:
                pass
        if resource is None:
            return 0.0
        try:
            raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Fallback only: ru_maxrss is peak RSS on Linux (kilobytes), not live RSS.
            if sys.platform == "darwin":
                return round(raw_rss / (1024.0 * 1024.0), 2)
            return round(raw_rss / 1024.0, 2)
        except Exception:
            return 0.0

    @classmethod
    async def measure_event_loop_lag(cls) -> float:
        """Measure async event loop lag by measuring execution scheduling jitter."""
        try:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            # Yield control for nominal 1ms
            await asyncio.sleep(0.001)
            t1 = loop.time()
            elapsed_ms = (t1 - t0) * 1000.0
            # Lag is the difference above the intended 1ms sleep
            lag_ms = max(0.0, elapsed_ms - 1.0)
            return round(lag_ms, 3)
        except Exception:
            return 0.0

    @classmethod
    def check_otlp_posture(cls) -> tuple[bool, bool]:
        """Check OTLP export environment configuration and SDK initialization status."""
        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        is_configured = bool(otlp_endpoint and otlp_endpoint.strip())

        is_connected = False
        try:
            from myrm_agent_harness.infra.tracing.tracer import is_tracing_initialized

            is_connected = is_tracing_initialized()
        except ImportError:
            pass
        if not is_connected:
            try:
                from myrm_agent_harness.infra.tracing.metrics.exporter import is_metrics_initialized

                is_connected = is_metrics_initialized()
            except ImportError:
                pass

        return is_configured, is_connected

    @classmethod
    async def collect_vitals(cls) -> GatewayVitals:
        """Capture current physical vitals snapshot."""
        lag_ms = await cls.measure_event_loop_lag()
        rss_mb = cls.get_process_rss_mb()
        uptime = max(0.0, time.time() - _START_TIME)

        try:
            # Count active asyncio tasks in current loop
            tasks = len(asyncio.all_tasks())
        except Exception:
            tasks = 1

        return GatewayVitals(
            event_loop_lag_ms=lag_ms,
            memory_rss_mb=rss_mb,
            uptime_seconds=uptime,
            active_tasks=tasks,
        )

    @classmethod
    async def inspect(cls) -> GatewayRedactedHealthDTO:
        """Perform comprehensive zero-payload health inspection."""
        vitals = await cls.collect_vitals()
        otlp_conf, otlp_conn = cls.check_otlp_posture()

        diagnostics: list[str] = []
        status = GatewayHealthStatus.HEALTHY

        # 1. Event loop latency evaluation
        if vitals.event_loop_lag_ms >= cls.EVENT_LOOP_ERROR_MS:
            status = GatewayHealthStatus.UNHEALTHY
            diagnostics.append(
                f"Critical event loop lag detected ({vitals.event_loop_lag_ms:.1f}ms >= {cls.EVENT_LOOP_ERROR_MS}ms). "
                "Event loop is severely blocked by synchronous work."
            )
        elif vitals.event_loop_lag_ms >= cls.EVENT_LOOP_WARN_MS:
            if status != GatewayHealthStatus.UNHEALTHY:
                status = GatewayHealthStatus.DEGRADED
            diagnostics.append(
                f"Elevated event loop lag ({vitals.event_loop_lag_ms:.1f}ms >= {cls.EVENT_LOOP_WARN_MS}ms). "
                "Potential CPU contention or task backlog."
            )

        # 2. Memory RSS evaluation
        if vitals.memory_rss_mb >= cls.MEMORY_ERROR_MB:
            status = GatewayHealthStatus.UNHEALTHY
            diagnostics.append(
                f"Process RSS memory critical ({vitals.memory_rss_mb:.1f}MB >= {cls.MEMORY_ERROR_MB}MB). "
                "High risk of OOM termination."
            )
        elif vitals.memory_rss_mb >= cls.MEMORY_WARN_MB:
            if status != GatewayHealthStatus.UNHEALTHY:
                status = GatewayHealthStatus.DEGRADED
            diagnostics.append(
                f"Process RSS memory elevated ({vitals.memory_rss_mb:.1f}MB >= {cls.MEMORY_WARN_MB}MB). "
                "Consider recycling idle sessions or compacting state DB."
            )

        # 3. OTLP posture note
        if otlp_conf and not otlp_conn:
            diagnostics.append(
                "OTLP endpoint configured but OpenTelemetry tracing or metrics SDK is not actively connected."
            )

        if not diagnostics:
            diagnostics.append("Gateway vitals and event loop scheduling are operating nominally.")

        return GatewayRedactedHealthDTO(
            status=status,
            vitals=vitals,
            otlp_endpoint_configured=otlp_conf,
            otlp_connected=otlp_conn,
            redacted_diagnostics=diagnostics,
        )


async def check_gateway_runtime_health() -> HealthReport:
    """Standard diagnostic probe function integrating GatewayHealthInspector into /health/doctor."""
    dto = await GatewayHealthInspector.inspect()

    level_map = {
        GatewayHealthStatus.HEALTHY: "pass",
        GatewayHealthStatus.DEGRADED: "warn",
        GatewayHealthStatus.UNHEALTHY: "fail",
    }
    status_str = level_map.get(dto.status, "pass")

    summary_msg = (
        f"Gateway Runtime: {dto.status} | "
        f"Lag: {dto.vitals.event_loop_lag_ms:.1f}ms | "
        f"RSS: {dto.vitals.memory_rss_mb:.1f}MB | "
        f"Tasks: {dto.vitals.active_tasks}"
    )
    detail_msg = "; ".join(dto.redacted_diagnostics)

    fix_suggestion = (
        "Inspect synchronous blocking operations or compact long-running agent state."
        if status_str != "pass"
        else ""
    )

    return HealthReport(
        component_name="GatewayRuntime",
        status=status_str,
        message=summary_msg,
        detail=detail_msg,
        fix_suggestion=fix_suggestion,
    )


register_diagnostic(check_gateway_runtime_health)
