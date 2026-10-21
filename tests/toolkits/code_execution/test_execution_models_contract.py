"""Regression tests for execution model contracts."""

from myrm_agent_harness.toolkits.code_execution.executors.models import (
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    MCPCommunicationConfig,
)


def test_execution_result_derives_success_from_exit_code() -> None:
    success_result = ExecutionResult(exit_code=0)
    failure_result = ExecutionResult(error="boom")

    assert success_result.success is True
    assert failure_result.success is False


def test_execution_metrics_record_counts_errors_and_duration() -> None:
    metrics = ExecutionMetrics()

    metrics.record(ExecutionResult(success=True, execution_time=1.25), "python")
    metrics.record(ExecutionResult(success=False, execution_time=0.5, error="blocked"), "bash")

    assert metrics.execution_count == 2
    assert metrics.error_count == 1
    assert metrics.total_time_ms == 1750.0


def test_execution_context_accepts_runtime_contract_fields() -> None:
    context = ExecutionContext(
        code="print('ok')",
        session_id="session-123",
        workspace_root="/tmp/workspace",
        active_skills=["lint"],
        allow_network=True,
        allowed_hosts=frozenset({"example.com"}),
        mcp_config=[],
    )

    assert context.session_id == "session-123"
    assert context.workspace_root == "/tmp/workspace"
    assert context.active_skills == ["lint"]
    assert context.allow_network is True
    assert context.allowed_hosts == frozenset({"example.com"})
    assert context.mcp_config == []


def test_execution_context_default_timeout_is_60() -> None:
    """Timeout must be >= IPC client timeout and consistent with LocalExecutionConfig."""
    context = ExecutionContext(code="echo ok")
    assert context.timeout == 60


def test_executor_config_default_timeout_is_60() -> None:
    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutorConfig

    config = ExecutorConfig()
    assert config.timeout == 60


def test_mcp_communication_config_supports_proxy_flags() -> None:
    config = MCPCommunicationConfig(
        socket_path="/tmp/myrm-agent.sock",
        skip_local_proxy=True,
    )

    assert config.socket_path == "/tmp/myrm-agent.sock"
    assert config.skip_local_proxy is True
