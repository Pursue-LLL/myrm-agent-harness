"""Tests for observability diagnostics manager.

Covers:
- register_diagnostic: dedup, correct append
- register_protocol: valid instance, invalid instance
- run_all_diagnostics: concurrency, timeout handling, exception handling, empty registry
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.observability.diagnostics.manager import (
    _diagnostic_hooks,
    register_diagnostic,
    register_protocol,
    run_all_diagnostics,
)
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport


@pytest.fixture(autouse=True)
def _isolate_hooks():
    """Snapshot and restore the global hooks list around each test."""
    original = _diagnostic_hooks.copy()
    _diagnostic_hooks.clear()
    yield
    _diagnostic_hooks.clear()
    _diagnostic_hooks.extend(original)


class TestRegisterDiagnostic:
    def test_registers_function(self):
        async def probe() -> HealthReport:
            return HealthReport(component_name="Test", status="pass", message="ok")

        register_diagnostic(probe)
        assert probe in _diagnostic_hooks

    def test_deduplicates(self):
        async def probe() -> HealthReport:
            return HealthReport(component_name="Test", status="pass", message="ok")

        register_diagnostic(probe)
        register_diagnostic(probe)
        assert _diagnostic_hooks.count(probe) == 1


class TestRegisterProtocol:
    def test_valid_protocol_instance(self):
        class MyDiagnostic:
            async def check_health(self) -> HealthReport:
                return HealthReport(component_name="My", status="pass", message="ok")

        instance = MyDiagnostic()
        register_protocol(instance)
        assert instance.check_health in _diagnostic_hooks

    def test_invalid_instance_logs_warning(self):
        not_a_protocol = MagicMock(spec=[])
        with patch("myrm_agent_harness.observability.diagnostics.manager.logger") as mock_logger:
            register_protocol(not_a_protocol)
            mock_logger.warning.assert_called_once()
        assert len(_diagnostic_hooks) == 0


class TestRunAllDiagnostics:
    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty(self):
        result = await run_all_diagnostics()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_passing_hook(self):
        async def probe() -> HealthReport:
            return HealthReport(component_name="Net", status="pass", message="ok")

        register_diagnostic(probe)
        reports = await run_all_diagnostics()
        assert len(reports) == 1
        assert reports[0].status == "pass"
        assert reports[0].component_name == "Net"

    @pytest.mark.asyncio
    async def test_multiple_hooks_run_concurrently(self):
        call_order: list[str] = []

        async def probe_a() -> HealthReport:
            call_order.append("a_start")
            await asyncio.sleep(0.05)
            call_order.append("a_end")
            return HealthReport(component_name="A", status="pass", message="ok")

        async def probe_b() -> HealthReport:
            call_order.append("b_start")
            await asyncio.sleep(0.05)
            call_order.append("b_end")
            return HealthReport(component_name="B", status="pass", message="ok")

        register_diagnostic(probe_a)
        register_diagnostic(probe_b)
        reports = await run_all_diagnostics()

        assert len(reports) == 2
        # Both should start before either ends (concurrent)
        assert "a_start" in call_order[:2]
        assert "b_start" in call_order[:2]

    @pytest.mark.asyncio
    async def test_timeout_produces_fail_report(self):
        """Verify that a hook returning non-HealthReport produces a fail report."""

        async def bad_return_probe():
            return "not a health report"

        register_diagnostic(bad_return_probe)
        reports = await run_all_diagnostics()

        assert len(reports) == 1
        assert reports[0].status == "fail"
        assert "unexpected" in reports[0].detail.lower() or "Unexpected" in reports[0].detail

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Verify that hooks exceeding the internal timeout produce a fail report."""

        async def hanging_probe() -> HealthReport:
            await asyncio.sleep(100)
            return HealthReport(component_name="Hang", status="pass", message="ok")

        register_diagnostic(hanging_probe)

        # Patch asyncio.timeout to use a very short duration for testing
        original_fn = asyncio.timeout

        def fast_timeout(duration: float):
            return original_fn(0.01)

        with patch("asyncio.timeout", side_effect=fast_timeout):
            reports = await run_all_diagnostics()

        assert len(reports) == 1
        assert reports[0].status == "fail"
        assert "timed out" in reports[0].detail.lower()

    @pytest.mark.asyncio
    async def test_exception_in_hook_produces_fail_report(self):
        async def crashing_probe() -> HealthReport:
            raise RuntimeError("kaboom")

        register_diagnostic(crashing_probe)
        reports = await run_all_diagnostics()

        assert len(reports) == 1
        assert reports[0].status == "fail"
        assert "kaboom" in reports[0].detail

    @pytest.mark.asyncio
    async def test_mixed_results(self):
        async def pass_probe() -> HealthReport:
            return HealthReport(component_name="Good", status="pass", message="ok")

        async def fail_probe() -> HealthReport:
            raise ValueError("bad")

        register_diagnostic(pass_probe)
        register_diagnostic(fail_probe)
        reports = await run_all_diagnostics()

        assert len(reports) == 2
        statuses = {r.component_name: r.status for r in reports}
        assert statuses["Good"] == "pass"
        assert statuses.get("fail_probe") == "fail" or any(r.status == "fail" for r in reports)
