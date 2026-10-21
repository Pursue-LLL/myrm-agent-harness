"""[INPUT] Harness agent_operations submodule exports.
[OUTPUT] Unit tests verifying Agent-Owned execution contexts, capability resolution, error isolation, and roster exports.
[POS] Unit tests for agent_operations fabric.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.agent_operations import (
    AgentOwnedExecutionContext,
    AgentOwnedOperationsFabric,
    AgentProviderConfig,
    AgentRosterEntry,
    AgentScopedError,
)


@pytest.fixture
def sample_provider_coder() -> AgentProviderConfig:
    return AgentProviderConfig(
        provider_name="deepseek",
        model_name="deepseek-coder",
        temperature=0.2,
        max_tokens=4096,
        timeout_seconds=45.0,
    )


@pytest.fixture
def sample_provider_reviewer() -> AgentProviderConfig:
    return AgentProviderConfig(
        provider_name="anthropic",
        model_name="claude-3-5-sonnet",
        temperature=0.5,
    )


def test_agent_owned_context_creation(sample_provider_coder: AgentProviderConfig) -> None:
    ctx = AgentOwnedExecutionContext(
        agent_id="coder_01",
        role="code_generator",
        session_id="chat_100",
        provider_config=sample_provider_coder,
        capabilities=["write_code", "run_linter"],
        allowlist=["tool_fs_write", "tool_bash_exec"],
    )

    assert ctx.agent_id == "coder_01"
    assert ctx.provider_config.model_name == "deepseek-coder"
    assert len(ctx.error_stack) == 0

    roster_entry = ctx.to_roster_entry()
    assert isinstance(roster_entry, AgentRosterEntry)
    assert roster_entry.agent_id == "coder_01"
    assert roster_entry.provider_model == "deepseek/deepseek-coder"
    assert roster_entry.is_healthy is True


def test_agent_scoped_capability_resolution(
    sample_provider_coder: AgentProviderConfig,
    sample_provider_reviewer: AgentProviderConfig,
) -> None:
    fabric = AgentOwnedOperationsFabric()

    agent_a = AgentOwnedExecutionContext(
        agent_id="worker_a",
        session_id="chat_1",
        provider_config=sample_provider_coder,
        allowlist=["tool_fs_write", "tool_git_commit"],
    )
    agent_b = AgentOwnedExecutionContext(
        agent_id="worker_b",
        session_id="chat_1",
        provider_config=sample_provider_reviewer,
        allowlist=["tool_read_file"],
    )

    fabric.register_agent(agent_a)
    fabric.register_agent(agent_b)

    # worker_a has tool_fs_write, worker_b does not
    assert fabric.resolve_capability("worker_a", "tool_fs_write") is True
    assert fabric.resolve_capability("worker_a", "tool_read_file") is False

    assert fabric.resolve_capability("worker_b", "tool_read_file") is True
    assert fabric.resolve_capability("worker_b", "tool_fs_write") is False

    # Unregistered agent always fails resolution
    assert fabric.resolve_capability("unknown_agent", "tool_fs_write") is False


def test_isolated_error_stack_prevents_cross_contamination(
    sample_provider_coder: AgentProviderConfig,
    sample_provider_reviewer: AgentProviderConfig,
) -> None:
    fabric = AgentOwnedOperationsFabric()

    agent_a = AgentOwnedExecutionContext(
        agent_id="worker_a",
        session_id="chat_2",
        provider_config=sample_provider_coder,
    )
    agent_b = AgentOwnedExecutionContext(
        agent_id="worker_b",
        session_id="chat_2",
        provider_config=sample_provider_reviewer,
    )

    fabric.register_agent(agent_a)
    fabric.register_agent(agent_b)

    # Record error strictly onto worker_a
    err_a = fabric.record_agent_error(
        agent_id="worker_a",
        operation="run_test",
        error_type="SyntaxError",
        message="invalid syntax at line 42",
        fatal=True,
    )

    assert isinstance(err_a, AgentScopedError)
    assert err_a.agent_id == "worker_a"
    assert err_a.fatal is True

    # Check isolation: worker_a has error, worker_b has 0 errors
    errors_a = fabric.get_agent_errors("worker_a")
    errors_b = fabric.get_agent_errors("worker_b")

    assert len(errors_a) == 1
    assert errors_a[0].error_type == "SyntaxError"
    assert len(errors_b) == 0

    roster = fabric.get_roster(session_id="chat_2")
    roster_dict = {entry.agent_id: entry for entry in roster}
    assert roster_dict["worker_a"].is_healthy is False
    assert roster_dict["worker_a"].error_count == 1
    assert roster_dict["worker_b"].is_healthy is True
    assert roster_dict["worker_b"].error_count == 0


def test_execute_isolated_operation_catches_and_records(
    sample_provider_coder: AgentProviderConfig,
) -> None:
    fabric = AgentOwnedOperationsFabric()
    agent = AgentOwnedExecutionContext(
        agent_id="worker_calc",
        session_id="chat_3",
        provider_config=sample_provider_coder,
    )
    fabric.register_agent(agent)

    # Successful isolated operation
    res = fabric.execute_isolated_operation(
        agent_id="worker_calc",
        operation_name="multiply",
        fn=lambda: 21 * 2,
    )
    assert res == 42
    assert len(fabric.get_agent_errors("worker_calc")) == 0

    # Failing isolated operation does NOT raise, but records into worker_calc error stack
    def buggy_call() -> int:
        raise ValueError("Division by zero in formula")

    res_fail = fabric.execute_isolated_operation(
        agent_id="worker_calc",
        operation_name="compute_ratio",
        fn=buggy_call,
        fatal_on_exception=True,
    )
    assert res_fail is None

    errors = fabric.get_agent_errors("worker_calc")
    assert len(errors) == 1
    assert errors[0].operation == "compute_ratio"
    assert errors[0].error_type == "ValueError"
    assert "Division by zero" in errors[0].message
    assert errors[0].fatal is True
