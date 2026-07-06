"""Unit tests for agent.orchestration signals, hooks, and registry integration."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.orchestration.hooks import (
    COMPLETION_CHECK_TOOL_NAME,
    RUNTIME_HOOK_NAMES,
    is_runtime_hook,
)
from myrm_agent_harness.agent.orchestration.signals.catalog import (
    DEEP_RESEARCH_SIGNAL_NAMES,
    ORCHESTRATION_SIGNAL_NAMES,
    VERIFIER_SIGNAL_NAMES,
)
from myrm_agent_harness.agent.orchestration.signals.deep_research import (
    DISPATCH_TOOL_NAME,
    FINALIZE_TOOL_NAME,
    THINK_TOOL_NAME,
    build_orchestrator_tools,
    build_signal_schema,
    DispatchResearchInput,
)
from myrm_agent_harness.agent.orchestration.signals.verifier import (
    SUBMIT_VERDICT_SIGNAL_NAME,
    create_submit_verdict_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


def test_runtime_hook_ssot() -> None:
    assert COMPLETION_CHECK_TOOL_NAME == "_completion_check"
    assert RUNTIME_HOOK_NAMES == frozenset({COMPLETION_CHECK_TOOL_NAME})


def test_is_runtime_hook_membership() -> None:
    assert is_runtime_hook(COMPLETION_CHECK_TOOL_NAME) is True
    assert is_runtime_hook("dispatch_research") is False
    assert is_runtime_hook("web_search_tool") is False


def test_orchestration_signal_names_disjoint_from_hooks() -> None:
    assert not ORCHESTRATION_SIGNAL_NAMES & RUNTIME_HOOK_NAMES
    assert DEEP_RESEARCH_SIGNAL_NAMES | VERIFIER_SIGNAL_NAMES == ORCHESTRATION_SIGNAL_NAMES


def test_build_signal_schema_shape() -> None:
    schema = build_signal_schema(
        DISPATCH_TOOL_NAME,
        "Dispatch research sub-agent",
        DispatchResearchInput,
    )
    assert schema["type"] == "function"
    function = schema["function"]
    assert function["name"] == DISPATCH_TOOL_NAME
    assert function["description"] == "Dispatch research sub-agent"
    params = function["parameters"]
    assert "properties" in params
    assert "task" in params["properties"]
    assert "title" not in params


def test_build_orchestrator_tools_include_think() -> None:
    tools = build_orchestrator_tools(include_think=True)
    names = [tool["function"]["name"] for tool in tools]
    assert names == [DISPATCH_TOOL_NAME, THINK_TOOL_NAME, FINALIZE_TOOL_NAME]


def test_build_orchestrator_tools_exclude_think() -> None:
    tools = build_orchestrator_tools(include_think=False)
    names = [tool["function"]["name"] for tool in tools]
    assert names == [DISPATCH_TOOL_NAME, FINALIZE_TOOL_NAME]


def test_create_submit_verdict_tool_writes_context() -> None:
    context: dict[str, object] = {}
    verdict_tool = create_submit_verdict_tool(context)
    assert verdict_tool.name == SUBMIT_VERDICT_SIGNAL_NAME

    result = verdict_tool.invoke(
        {
            "passed": True,
            "summary": "All checks passed",
            "findings": [{"severity": "info", "detail": "none"}],
            "confidence": "HIGH",
        }
    )
    assert result == "Verdict submitted successfully. Please complete your response."
    verdict = context["_verifier_verdict"]
    assert verdict.passed is True
    assert verdict.summary == "All checks passed"
    assert verdict.confidence == "HIGH"


class TestRegisterRuntimeHook:
    def test_register_runtime_hook_success(self) -> None:
        from langchain_core.tools import tool

        @tool(COMPLETION_CHECK_TOOL_NAME)
        def _completion_check(reason: str = "") -> str:
            """Middleware completion guard hook."""
            return reason or "ok"

        reg = ToolRegistry()
        reg.register_runtime_hook(_completion_check, source=ToolSource.MIDDLEWARE)
        assert reg.has_tool(COMPLETION_CHECK_TOOL_NAME)
        runtime_names = {tool.name for tool in reg.get_runtime_tools()}
        assert COMPLETION_CHECK_TOOL_NAME in runtime_names
        assert COMPLETION_CHECK_TOOL_NAME not in {tool.name for tool in reg.resolve()}

    def test_register_runtime_hook_rejects_non_ssot_name(self) -> None:
        from unittest.mock import MagicMock

        reg = ToolRegistry()
        bad_tool = MagicMock()
        bad_tool.name = "dispatch_research"
        with pytest.raises(ValueError, match="RUNTIME_HOOK_NAMES"):
            reg.register_runtime_hook(bad_tool)
