"""Unit tests for Heterogeneous External Agent Adapter and Subagent Bundle Manager (Item 75)."""

import asyncio

import pytest

from myrm_agent_harness.agent.sub_agents.external_bundle import (
    BatchDispatchTask,
    ConcurrencyLimitExceededError,
    ExternalAgentBundleRegistry,
    ExternalAgentTypeEnum,
    ExternalBundleNotFoundError,
    ExternalBundleProfileSpec,
    ExternalBundleSecurityViolationError,
    ExternalSubagentMultiplexer,
    SubagentInstanceStatusEnum,
)


@pytest.fixture
def registry() -> ExternalAgentBundleRegistry:
    return ExternalAgentBundleRegistry()


@pytest.fixture
def multiplexer(registry: ExternalAgentBundleRegistry) -> ExternalSubagentMultiplexer:
    return ExternalSubagentMultiplexer(registry=registry)


def test_bundle_registry_builtins_and_registration(registry: ExternalAgentBundleRegistry) -> None:
    """Ensure built-in DeepSeek RC.8 bundles are initialized with correct metadata."""
    bundles = registry.list_bundles()
    bundle_ids = {b.bundle_id for b in bundles}
    assert "subagent-claude-code" in bundle_ids
    assert "subagent-codex" in bundle_ids
    assert "subagent-gemini-cli" in bundle_ids

    codex = registry.get_bundle("subagent-codex")
    assert codex.agent_type == ExternalAgentTypeEnum.CODEX
    assert codex.binary_name == "codex"
    assert "unit_testing" in codex.capabilities

    # Unknown bundle check
    with pytest.raises(ExternalBundleNotFoundError):
        registry.get_bundle("nonexistent-bundle-id")


def test_sandbox_directory_boundary_validation(registry: ExternalAgentBundleRegistry) -> None:
    """Ensure external subagents cannot escape workspace root via path traversal."""
    workspace = "/tmp/sandbox/myrm-project"

    # Permitted subdirectory
    valid_path = registry.validate_directory_boundary(
        bundle_id="subagent-codex",
        target_path=f"{workspace}/frontend",
        session_workspace_root=workspace,
    )
    assert "frontend" in valid_path

    # Illegal directory traversal
    with pytest.raises(ExternalBundleSecurityViolationError, match="Security Violation"):
        registry.validate_directory_boundary(
            bundle_id="subagent-codex",
            target_path="/etc/passwd",
            session_workspace_root=workspace,
        )


@pytest.mark.asyncio
async def test_unlocked_parallel_multiplexing_concurrent_codex(
    multiplexer: ExternalSubagentMultiplexer,
) -> None:
    """Ensure multiple instances of the same bundle (Codex) run 100% in parallel without mutex blocking."""
    session_id = "test-session-multiplex"
    workspace = "/tmp/sandbox/project"

    # Tasks: 2 Codex instances + 1 Claude Code instance concurrently
    tasks = [
        BatchDispatchTask(
            bundle_id="subagent-codex",
            role_label="frontend-coder",
            task_prompt="Implement Button component in React",
            target_subdir="src/components",
        ),
        BatchDispatchTask(
            bundle_id="subagent-codex",
            role_label="backend-coder",
            task_prompt="Implement API endpoints in FastAPI",
            target_subdir="app/api",
        ),
        BatchDispatchTask(
            bundle_id="subagent-claude-code",
            role_label="code-reviewer",
            task_prompt="Audit AST diffs for memory leaks",
            target_subdir=".",
        ),
    ]

    result = await multiplexer.dispatch_batch(
        session_id=session_id,
        tasks=tasks,
        workspace_root=workspace,
    )

    assert result.total_dispatched == 3
    instance_ids = [inst.instance_id for inst in result.dispatched_instances]
    assert len(instance_ids) == 3

    # Wait briefly for simulated mock execution to complete
    await asyncio.sleep(0.15)

    for i_id in instance_ids:
        inst = multiplexer.get_instance(i_id)
        assert inst is not None
        assert inst.status == SubagentInstanceStatusEnum.COMPLETED
        assert inst.exit_code == 0
        assert len(inst.stdout_chunks) >= 3
        assert len(inst.artifacts) >= 2


def test_stdout_reshaping_and_artifact_extraction(
    multiplexer: ExternalSubagentMultiplexer,
) -> None:
    """Ensure ANSI formatting is removed and diff/result tags are reshaped into structured artifacts."""
    task = BatchDispatchTask(
        bundle_id="subagent-codex",
        role_label="styler",
        task_prompt="Style with Tailwind",
    )
    record = multiplexer.dispatch_instance(
        session_id="test-session-ansi",
        task=task,
        workspace_root="/tmp/sandbox/project",
    )

    # Inject dirty ANSI line with artifact tag
    dirty_line = "\x1b[31;1mError: none\x1b[0m\n[artifact:diff:App.tsx] +className='p-4'"
    multiplexer.reshape_and_append_stdout(record, dirty_line)

    assert "\x1b[" not in record.stdout_chunks[-1]
    assert len(record.artifacts) == 1
    assert record.artifacts[0]["type"] == "diff"
    assert record.artifacts[0]["path"] == "App.tsx"


def test_concurrency_limit_enforcement(multiplexer: ExternalSubagentMultiplexer) -> None:
    """Ensure max_concurrency boundary raises ConcurrencyLimitExceededError."""
    # Register bundle with max_concurrency = 2
    bundle = ExternalBundleProfileSpec(
        bundle_id="micro-bundle",
        agent_type=ExternalAgentTypeEnum.CUSTOM,
        display_name="Micro Bundle",
        description="Limited bundle",
        binary_name="micro",
        max_concurrency=2,
    )
    multiplexer.registry.register_bundle(bundle)

    task = BatchDispatchTask(
        bundle_id="micro-bundle",
        role_label="micro-worker",
        task_prompt="Do micro work",
    )

    # First 2 succeed
    multiplexer.dispatch_instance(session_id="s1", task=task, workspace_root="/tmp/w")
    multiplexer.dispatch_instance(session_id="s1", task=task, workspace_root="/tmp/w")

    # 3rd fails
    with pytest.raises(ConcurrencyLimitExceededError):
        multiplexer.dispatch_instance(session_id="s1", task=task, workspace_root="/tmp/w")


@pytest.mark.asyncio
async def test_instance_termination(multiplexer: ExternalSubagentMultiplexer) -> None:
    """Ensure terminating an active subagent halts execution and records status TERMINATED."""
    async def long_running_executor(rec) -> None:
        await asyncio.sleep(5.0)

    task = BatchDispatchTask(
        bundle_id="subagent-codex",
        role_label="long-worker",
        task_prompt="Run long task",
    )
    record = multiplexer.dispatch_instance(
        session_id="s-term",
        task=task,
        workspace_root="/tmp/w",
        custom_executor=long_running_executor,
    )

    await asyncio.sleep(0.02)
    assert record.status == SubagentInstanceStatusEnum.RUNNING

    terminated = multiplexer.terminate_instance(record.instance_id, reason="user_cancelled_task")
    assert terminated is True
    assert record.status == SubagentInstanceStatusEnum.TERMINATED
    assert "user_cancelled_task" in str(record.error)
