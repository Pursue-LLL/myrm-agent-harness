"""[INPUT] None.
[OUTPUT] Unit test suite for Heterogeneous External Agent Bridge & CLI Process Adapter.
[POS] Subagent CLI process adapter testing.
"""

from __future__ import annotations

import sys

import pytest

from myrm_agent_harness.agent.sub_agents.cli_adapter import (
    ExternalAgentConfig,
    ExternalAgentKind,
    ExternalCliAgentAdapter,
    ProcessExecutionRequest,
    ProcessLaneStatus,
    compute_receipt_hash,
    sanitize_cli_output,
)


@pytest.fixture
def cli_adapter() -> ExternalCliAgentAdapter:
    return ExternalCliAgentAdapter()


def test_sanitize_cli_output_and_ansi_stripping() -> None:
    ansi_input = "\x1b[31;1mError:\x1b[0m Process crashed\x1b[2K\r\nNext line"
    cleaned = sanitize_cli_output(ansi_input)
    assert cleaned == "Error: Process crashed\nNext line"
    assert "\x1b" not in cleaned

    # Empty string edge case
    assert sanitize_cli_output("") == ""


def test_sanitize_cli_output_truncation() -> None:
    large_input = "A" * 1000
    cleaned = sanitize_cli_output(large_input, max_chars=100)
    assert len(cleaned) < 1000
    assert "TRUNCATED" in cleaned
    assert cleaned.startswith("A" * 50)
    assert cleaned.endswith("A" * 50)


def test_compute_receipt_hash_determinism() -> None:
    hash_1 = compute_receipt_hash(
        execution_id="exec-1",
        agent_id="agt-1",
        exit_code=0,
        stdout_summary="Task completed",
    )
    hash_2 = compute_receipt_hash(
        execution_id="exec-1",
        agent_id="agt-1",
        exit_code=0,
        stdout_summary="Task completed",
    )
    assert hash_1 == hash_2
    assert len(hash_1) == 64  # SHA-256 length


def test_adapter_registration_lifecycle(cli_adapter: ExternalCliAgentAdapter) -> None:
    config = ExternalAgentConfig(
        agent_id="agt-claude",
        name="Claude Code Worker",
        kind=ExternalAgentKind.CLAUDE_CODE,
        command="claude",
        args=["--non-interactive"],
        timeout_seconds=30.0,
    )

    cli_adapter.register_agent(config)
    fetched = cli_adapter.get_agent("agt-claude")
    assert fetched is not None
    assert fetched.name == "Claude Code Worker"
    assert len(cli_adapter.list_agents()) == 1

    assert cli_adapter.unregister_agent("agt-claude") is True
    assert cli_adapter.get_agent("agt-claude") is None
    assert len(cli_adapter.list_agents()) == 0


def test_adapter_probe_health(cli_adapter: ExternalCliAgentAdapter) -> None:
    config_valid = ExternalAgentConfig(
        agent_id="agt-python",
        name="Python CLI",
        kind=ExternalAgentKind.GENERIC_STDIO,
        command=sys.executable,
    )
    cli_adapter.register_agent(config_valid)
    assert cli_adapter.probe_health("agt-python") is True

    config_invalid = ExternalAgentConfig(
        agent_id="agt-ghost",
        name="Ghost Executable",
        kind=ExternalAgentKind.OPENCLAW,
        command="non_existent_binary_xyz_123",
    )
    cli_adapter.register_agent(config_invalid)
    assert cli_adapter.probe_health("agt-ghost") is False
    assert cli_adapter.probe_health("unknown-agent") is False


def test_adapter_execute_success(cli_adapter: ExternalCliAgentAdapter) -> None:
    config = ExternalAgentConfig(
        agent_id="agt-echo",
        name="Echo Worker",
        kind=ExternalAgentKind.GENERIC_STDIO,
        command=sys.executable,
        args=["-c", "import sys; print('ECHO:' + sys.stdin.read().strip())"],
        timeout_seconds=5.0,
    )
    cli_adapter.register_agent(config)

    request = ProcessExecutionRequest(
        execution_id="exec-success",
        input_text="Hello CLI Bridge",
    )
    receipt = cli_adapter.execute("agt-echo", request)

    assert receipt.status == ProcessLaneStatus.COMPLETED
    assert receipt.exit_code == 0
    assert "ECHO:Hello CLI Bridge" in receipt.stdout_summary
    assert receipt.execution_id == "exec-success"
    assert len(receipt.receipt_hash) == 64

    # Receipt recorded in history
    history = cli_adapter.get_receipts("agt-echo")
    assert len(history) == 1
    assert history[0].execution_id == "exec-success"


def test_adapter_execute_failure(cli_adapter: ExternalCliAgentAdapter) -> None:
    config = ExternalAgentConfig(
        agent_id="agt-fail",
        name="Failing Worker",
        kind=ExternalAgentKind.CODEX_CLI,
        command=sys.executable,
        args=["-c", "import sys; sys.stderr.write('Fatal syntax failure\\n'); sys.exit(42)"],
        timeout_seconds=5.0,
    )
    cli_adapter.register_agent(config)

    request = ProcessExecutionRequest(
        execution_id="exec-fail",
        input_text="Do something wrong",
    )
    receipt = cli_adapter.execute("agt-fail", request)

    assert receipt.status == ProcessLaneStatus.FAILED
    assert receipt.exit_code == 42
    assert "Fatal syntax failure" in receipt.stderr_summary


def test_adapter_execute_timeout(cli_adapter: ExternalCliAgentAdapter) -> None:
    config = ExternalAgentConfig(
        agent_id="agt-timeout",
        name="Hanging Worker",
        kind=ExternalAgentKind.GENERIC_STDIO,
        command=sys.executable,
        args=["-c", "import time; time.sleep(10)"],
        timeout_seconds=0.2,  # Very short timeout
    )
    cli_adapter.register_agent(config)

    request = ProcessExecutionRequest(
        execution_id="exec-timeout",
        input_text="Wait forever",
    )
    receipt = cli_adapter.execute("agt-timeout", request)

    assert receipt.status == ProcessLaneStatus.TIMED_OUT
    assert receipt.duration_ms >= 200
