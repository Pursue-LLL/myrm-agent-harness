"""Tests for gateway zero-payload redacted health export and runtime diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.observability.diagnostics.gateway_health import (
    GatewayHealthInspector,
    GatewayHealthStatus,
    GatewayRedactedHealthDTO,
    GatewayVitals,
    check_gateway_runtime_health,
)


class TestGatewayHealthInspectorVitals:
    @pytest.mark.asyncio
    async def test_measure_event_loop_lag_non_negative(self) -> None:
        lag_ms = await GatewayHealthInspector.measure_event_loop_lag()
        assert lag_ms >= 0.0

    def test_get_process_rss_mb_uses_psutil_current_rss(self) -> None:
        memory_info = type("MemInfo", (), {"rss": 256 * 1024 * 1024})()
        with patch("myrm_agent_harness.observability.diagnostics.gateway_health.psutil") as mock_psutil:
            mock_psutil.Process.return_value.memory_info.return_value = memory_info
            rss_mb = GatewayHealthInspector.get_process_rss_mb()
        assert rss_mb == 256.0


class TestGatewayHealthInspectorOtlpPosture:
    def test_otlp_not_configured_when_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
        configured, connected = GatewayHealthInspector.check_otlp_posture()
        assert configured is False
        assert connected is False

    def test_otlp_configured_and_tracing_connected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        with patch(
            "myrm_agent_harness.infra.tracing.tracer.is_tracing_initialized",
            return_value=True,
        ):
            configured, connected = GatewayHealthInspector.check_otlp_posture()
        assert configured is True
        assert connected is True

    def test_otlp_configured_metrics_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        with (
            patch(
                "myrm_agent_harness.infra.tracing.tracer.is_tracing_initialized",
                return_value=False,
            ),
            patch(
                "myrm_agent_harness.infra.tracing.metrics.exporter.is_metrics_initialized",
                return_value=True,
            ),
        ):
            configured, connected = GatewayHealthInspector.check_otlp_posture()
        assert configured is True
        assert connected is True


class TestGatewayHealthInspectorInspect:
    @pytest.mark.asyncio
    async def test_healthy_when_vitals_nominal(self) -> None:
        vitals = GatewayVitals(
            event_loop_lag_ms=5.0,
            memory_rss_mb=256.0,
            uptime_seconds=120.0,
            active_tasks=4,
        )
        with (
            patch.object(GatewayHealthInspector, "collect_vitals", AsyncMock(return_value=vitals)),
            patch.object(GatewayHealthInspector, "check_otlp_posture", return_value=(False, False)),
        ):
            dto = await GatewayHealthInspector.inspect()

        assert dto.status == GatewayHealthStatus.HEALTHY
        assert dto.vitals.active_tasks == 4
        assert "operating nominally" in dto.redacted_diagnostics[0]

    @pytest.mark.asyncio
    async def test_unhealthy_on_critical_event_loop_lag(self) -> None:
        vitals = GatewayVitals(
            event_loop_lag_ms=1500.0,
            memory_rss_mb=256.0,
            uptime_seconds=120.0,
            active_tasks=2,
        )
        with (
            patch.object(GatewayHealthInspector, "collect_vitals", AsyncMock(return_value=vitals)),
            patch.object(GatewayHealthInspector, "check_otlp_posture", return_value=(False, False)),
        ):
            dto = await GatewayHealthInspector.inspect()

        assert dto.status == GatewayHealthStatus.UNHEALTHY
        assert any("event loop lag" in note.lower() for note in dto.redacted_diagnostics)

    @pytest.mark.asyncio
    async def test_degraded_on_memory_warn_threshold(self) -> None:
        vitals = GatewayVitals(
            event_loop_lag_ms=5.0,
            memory_rss_mb=GatewayHealthInspector.MEMORY_WARN_MB + 10.0,
            uptime_seconds=120.0,
            active_tasks=2,
        )
        with (
            patch.object(GatewayHealthInspector, "collect_vitals", AsyncMock(return_value=vitals)),
            patch.object(GatewayHealthInspector, "check_otlp_posture", return_value=(False, False)),
        ):
            dto = await GatewayHealthInspector.inspect()

        assert dto.status == GatewayHealthStatus.DEGRADED
        assert any("RSS memory elevated" in note for note in dto.redacted_diagnostics)

    @pytest.mark.asyncio
    async def test_dto_to_dict_excludes_sensitive_fields(self) -> None:
        dto = GatewayRedactedHealthDTO(
            status=GatewayHealthStatus.HEALTHY,
            vitals=GatewayVitals(1.0, 100.0, 60.0, 1),
            otlp_endpoint_configured=False,
            otlp_connected=False,
            redacted_diagnostics=("Gateway vitals nominal.",),
        )
        payload = dto.to_dict()
        assert set(payload.keys()) == {
            "status",
            "vitals",
            "otlp_endpoint_configured",
            "otlp_connected",
            "redacted_diagnostics",
        }
        assert "prompt" not in str(payload).lower()


class TestCheckGatewayRuntimeHealthProbe:
    @pytest.mark.asyncio
    async def test_probe_uses_health_report_contract(self) -> None:
        dto = GatewayRedactedHealthDTO(
            status=GatewayHealthStatus.DEGRADED,
            vitals=GatewayVitals(250.0, 512.0, 300.0, 8),
            otlp_endpoint_configured=True,
            otlp_connected=False,
            redacted_diagnostics=("Elevated event loop lag.",),
        )
        with patch.object(GatewayHealthInspector, "inspect", AsyncMock(return_value=dto)):
            report = await check_gateway_runtime_health()

        assert report.component_name == "GatewayRuntime"
        assert report.status == "warn"
        assert "Gateway Runtime" in report.message
        assert report.fix_suggestion


class TestGatewayHealthRegistration:
    def test_probe_registered_in_diagnostic_manager(self) -> None:
        import myrm_agent_harness.observability.diagnostics.manager as manager_module

        hook_names = [
            getattr(hook, "__name__", "")
            for hook in manager_module._diagnostic_hooks
        ]
        assert "check_gateway_runtime_health" in hook_names
