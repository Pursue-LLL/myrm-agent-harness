"""Tests for runtime_diagnostics_tool.

Covers:
- All-pass scenario
- Mixed status (fail/warn/pass)
- include_passed filtering
- Empty diagnostics (no probes registered)
- Unknown status normalization
- Summary message generation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.observability.diagnostics.protocols import HealthReport


def _make_report(
    name: str, status: str, message: str = "ok", fix: str | None = None, detail: str | None = None,
) -> HealthReport:
    return HealthReport(component_name=name, status=status, message=message, detail=detail, fix_suggestion=fix)


@pytest.fixture()
def all_pass_reports() -> list[HealthReport]:
    return [
        _make_report("Network", "pass", "Network is healthy."),
        _make_report("Database", "pass", "SQLite responsive."),
        _make_report("WorkspaceStorage", "pass", "Writable."),
    ]


@pytest.fixture()
def mixed_reports() -> list[HealthReport]:
    return [
        _make_report("Network", "pass"),
        _make_report("Database", "fail", "DB locked", "Check WAL"),
        _make_report("VectorDB", "warn", "Qdrant slow", "Restart Qdrant"),
    ]


@pytest.mark.asyncio
async def test_all_pass_returns_pass_status(all_pass_reports: list[HealthReport]) -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=all_pass_reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["overall_status"] == "pass"
    assert result["read_only"] is True
    assert result["status_counts"]["pass"] == 3
    assert result["status_counts"]["fail"] == 0
    assert result["status_counts"]["warn"] == 0
    assert len(result["components"]) == 0


@pytest.mark.asyncio
async def test_all_pass_with_include_passed(all_pass_reports: list[HealthReport]) -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=all_pass_reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": True})

    assert len(result["components"]) == 3
    assert all(c["status"] == "pass" for c in result["components"])


@pytest.mark.asyncio
async def test_mixed_status_returns_fail(mixed_reports: list[HealthReport]) -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=mixed_reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["overall_status"] == "fail"
    assert result["status_counts"]["fail"] == 1
    assert result["status_counts"]["warn"] == 1
    assert result["status_counts"]["pass"] == 1
    assert len(result["components"]) == 2
    component_names = {c["component_name"] for c in result["components"]}
    assert "Database" in component_names
    assert "VectorDB" in component_names
    assert "Network" not in component_names


@pytest.mark.asyncio
async def test_warn_only_returns_warn_status() -> None:
    reports = [_make_report("SystemResources", "warn", "Memory high")]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["overall_status"] == "warn"
    assert "warning" in result["summary"].lower()


@pytest.mark.asyncio
async def test_empty_diagnostics() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=[],
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["overall_status"] == "pass"
    assert result["summary"] == "Runtime diagnostics passed."
    assert len(result["components"]) == 0


@pytest.mark.asyncio
async def test_unknown_status_normalized_to_warn() -> None:
    dirty_report = HealthReport.model_construct(
        component_name="Custom", status="UNKNOWN", message="Something weird", detail=None, fix_suggestion=None,
    )
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=[dirty_report],
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["overall_status"] == "warn"
    assert result["components"][0]["status"] == "warn"


@pytest.mark.asyncio
async def test_fix_suggestion_included() -> None:
    reports = [_make_report("Database", "fail", "Locked", "Run checkpoint")]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["components"][0]["fix_suggestion"] == "Run checkpoint"


@pytest.mark.asyncio
async def test_summary_message_for_failures() -> None:
    reports = [
        _make_report("A", "fail", "err1"),
        _make_report("B", "fail", "err2"),
    ]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert "2 failing" in result["summary"]


@pytest.mark.asyncio
async def test_default_parameter_excludes_passed(mixed_reports: list[HealthReport]) -> None:
    """invoke without explicit include_passed defaults to False."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=mixed_reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({})

    assert all(c["status"] != "pass" for c in result["components"])
    assert result["status_counts"]["pass"] == 1


@pytest.mark.asyncio
async def test_fix_suggestion_none_when_absent() -> None:
    reports = [_make_report("Network", "fail", "Timeout")]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["components"][0]["fix_suggestion"] is None


@pytest.mark.asyncio
async def test_multiple_fail_and_warn_counts() -> None:
    reports = [
        _make_report("A", "fail", "e1"),
        _make_report("B", "fail", "e2"),
        _make_report("C", "warn", "w1"),
        _make_report("D", "warn", "w2"),
        _make_report("E", "pass"),
    ]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["overall_status"] == "fail"
    assert result["status_counts"] == {"pass": 1, "fail": 2, "warn": 2}
    assert len(result["components"]) == 4


@pytest.mark.asyncio
async def test_component_order_preserved() -> None:
    reports = [
        _make_report("Z", "fail", "z"),
        _make_report("A", "warn", "a"),
    ]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    names = [c["component_name"] for c in result["components"]]
    assert names == ["Z", "A"]


@pytest.mark.asyncio
async def test_detail_field_included_in_output() -> None:
    reports = [_make_report("DB", "fail", "Database error.", fix="Restart", detail="sqlite3.OperationalError: locked")]
    with patch(
        "myrm_agent_harness.agent.meta_tools.diagnostics_tool.run_all_diagnostics",
        new_callable=AsyncMock,
        return_value=reports,
    ):
        from myrm_agent_harness.agent.meta_tools.diagnostics_tool import runtime_diagnostics_tool

        result = await runtime_diagnostics_tool.ainvoke({"include_passed": False})

    assert result["components"][0]["detail"] == "sqlite3.OperationalError: locked"
    assert result["components"][0]["message"] == "Database error."
