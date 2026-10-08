"""Unit tests for Governance Assembly Path Assertion & Zero-Bypass Guard Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.governance_assembly import (
    GovernanceAssemblyProbe,
    IngressSource,
    RecordingChatModel,
    RecordingTurn,
    RuntimeZeroBypassWatchdog,
    SyntheticToolCall,
    UngovernedToolExecutionError,
    is_governance_wrapped,
    wrap_with_governance,
)


def sample_read_tool(path: str = "") -> str:
    return f"read::{path}"


def sample_write_tool(path: str = "", content: str = "") -> str:
    return f"write::{path}::{content}"


def test_wrap_with_governance_and_signature_detection() -> None:
    """Test wrapping a tool and checking its governance signature."""
    assert not is_governance_wrapped(sample_read_tool)

    governed = wrap_with_governance(
        sample_read_tool,
        tool_name="read_file",
        ingress_source=IngressSource.INTERACTIVE_CHAT,
    )
    assert is_governance_wrapped(governed)
    assert governed(path="config.json") == "read::config.json"


def test_watchdog_zero_bypass_enforcement() -> None:
    """Test watchdog blocks naked unwrapped tools and permits governed ones."""
    watchdog = RuntimeZeroBypassWatchdog()

    governed = wrap_with_governance(
        sample_write_tool,
        tool_name="write_file",
        ingress_source=IngressSource.REST_API,
    )

    # 1. Governed tool executes successfully
    res = watchdog.execute_governed_tool(governed, "write_file", path="a.txt", content="hello")
    assert res == "write::a.txt::hello"

    # 2. Naked unwrapped tool is blocked immediately
    with pytest.raises(UngovernedToolExecutionError, match="Naked tool execution detected"):
        watchdog.execute_governed_tool(sample_write_tool, "write_file", path="a.txt", content="hello")


def test_watchdog_detects_incomplete_middleware_chain() -> None:
    """Test watchdog rejects tools wrapped with an incomplete middleware list."""
    watchdog = RuntimeZeroBypassWatchdog()

    partial_governed = wrap_with_governance(
        sample_read_tool,
        tool_name="read_file",
        ingress_source=IngressSource.INTERACTIVE_CHAT,
        middlewares=["EStopCheck"],  # Missing LoopGuard, ToolInterceptorMiddleware, TripartiteLedgerGate
    )

    with pytest.raises(UngovernedToolExecutionError, match="governance chain is incomplete"):
        watchdog.verify_tool(partial_governed, "read_file")


def test_probe_multi_ingress_coverage_matrix() -> None:
    """Test probe tracking and 100% compliance calculation."""
    probe = GovernanceAssemblyProbe()

    probe.record_invocation(
        tool_name="query_db",
        ingress_source=IngressSource.INTERACTIVE_CHAT,
        applied_middlewares=["EStopCheck", "LoopGuard", "ToolInterceptorMiddleware", "TripartiteLedgerGate"],
        is_governed=True,
    )
    probe.record_invocation(
        tool_name="sync_metrics",
        ingress_source=IngressSource.BACKGROUND_CRON,
        applied_middlewares=["EStopCheck", "LoopGuard", "ToolInterceptorMiddleware", "TripartiteLedgerGate"],
        is_governed=True,
    )
    probe.record_invocation(
        tool_name="subagent_search",
        ingress_source=IngressSource.SUBAGENT_DAG,
        applied_middlewares=["EStopCheck", "LoopGuard", "ToolInterceptorMiddleware", "TripartiteLedgerGate"],
        is_governed=True,
    )

    report = probe.generate_matrix_report()
    assert report.total_invocations == 3
    assert report.governed_invocations == 3
    assert report.bypassed_invocations == 0
    assert report.coverage_ratio == 1.0
    assert report.is_fully_compliant is True
    assert report.traces_by_ingress["INTERACTIVE_CHAT"] == 1
    assert report.traces_by_ingress["BACKGROUND_CRON"] == 1
    assert report.traces_by_ingress["SUBAGENT_DAG"] == 1


def test_probe_reports_violation_on_bypassed_path() -> None:
    """Test probe correctly identifies and reports bypassed unshielded path."""
    probe = GovernanceAssemblyProbe()

    probe.record_invocation(
        tool_name="leak_secret",
        ingress_source=IngressSource.SUBAGENT_DAG,
        applied_middlewares=(),
        is_governed=False,
        bypassed_guards=("ToolInterceptorMiddleware",),
    )

    report = probe.generate_matrix_report()
    assert report.is_fully_compliant is False
    assert report.bypassed_invocations == 1
    assert len(report.violations) == 1
    assert "Path violation on [SUBAGENT_DAG]" in report.violations[0]


def test_recording_model_zero_cost_assembly_workflows() -> None:
    """Test offline verification across Web Chat, Cron, and Subagent DAG scenarios."""
    watchdog = RuntimeZeroBypassWatchdog()
    probe = GovernanceAssemblyProbe()

    gov_read = wrap_with_governance(sample_read_tool, "read_file", IngressSource.INTERACTIVE_CHAT)
    gov_write = wrap_with_governance(sample_write_tool, "write_file", IngressSource.INTERACTIVE_CHAT)
    tools = {"read_file": gov_read, "write_file": gov_write}

    # Scenario 1: Interactive Chat
    script_chat = [
        RecordingTurn(
            role="assistant",
            content="Checking file...",
            tool_calls=(SyntheticToolCall(tool_name="read_file", tool_args={"path": "main.py"}),),
        ),
    ]
    model_chat = RecordingChatModel(script_chat)
    chat_res = model_chat.execute_scripted_workflow(
        ingress_source=IngressSource.INTERACTIVE_CHAT,
        watchdog=watchdog,
        probe=probe,
        tools=tools,
        prompts=["Please check main.py"],
    )
    assert chat_res == ["read::main.py"]

    # Scenario 2: Background Cron
    script_cron = [
        RecordingTurn(
            role="assistant",
            content="Running hourly backup...",
            tool_calls=(SyntheticToolCall(tool_name="write_file", tool_args={"path": "bak.tar", "content": "data"}),),
        ),
    ]
    model_cron = RecordingChatModel(script_cron)
    cron_res = model_cron.execute_scripted_workflow(
        ingress_source=IngressSource.BACKGROUND_CRON,
        watchdog=watchdog,
        probe=probe,
        tools=tools,
        prompts=["[CRON_TRIGGER_00:00]"],
    )
    assert cron_res == ["write::bak.tar::data"]

    # Scenario 3: Subagent DAG
    script_subagent = [
        RecordingTurn(
            role="assistant",
            content="Subagent delegating read...",
            tool_calls=(SyntheticToolCall(tool_name="read_file", tool_args={"path": "subtask.md"}),),
        ),
    ]
    model_subagent = RecordingChatModel(script_subagent)
    subagent_res = model_subagent.execute_scripted_workflow(
        ingress_source=IngressSource.SUBAGENT_DAG,
        watchdog=watchdog,
        probe=probe,
        tools=tools,
        prompts=["[DAG_NODE_2_START]"],
    )
    assert subagent_res == ["read::subtask.md"]

    # Assert matrix coverage across all three ingress pathways
    report = probe.generate_matrix_report()
    assert report.is_fully_compliant is True
    assert report.total_invocations == 3
    assert set(report.traces_by_ingress.keys()) == {"INTERACTIVE_CHAT", "BACKGROUND_CRON", "SUBAGENT_DAG"}


def test_recording_model_catches_naked_tool_in_dag() -> None:
    """Test that if a DAG node invokes a naked tool, the watchdog immediately stops execution."""
    watchdog = RuntimeZeroBypassWatchdog()
    probe = GovernanceAssemblyProbe()

    # Raw tool without governance wrapper
    tools = {"raw_write": sample_write_tool}

    script = [
        RecordingTurn(
            role="assistant",
            content="Subagent attempting naked call...",
            tool_calls=(SyntheticToolCall(tool_name="raw_write", tool_args={"path": "secret.env", "content": "key"}),),
        ),
    ]
    model = RecordingChatModel(script)

    with pytest.raises(UngovernedToolExecutionError, match="Naked tool execution detected"):
        model.execute_scripted_workflow(
            ingress_source=IngressSource.SUBAGENT_DAG,
            watchdog=watchdog,
            probe=probe,
            tools=tools,
            prompts=["Delegated task"],
        )
