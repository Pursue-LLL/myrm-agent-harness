"""Tests for whitelisted background bash auto-WAIT helpers."""

from myrm_agent_harness.agent.goals.wait_background_bash import (
    find_latest_background_spawn_in_window,
    is_wait_eligible_command,
    parse_background_spawn_from_record,
)
from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord


def test_is_wait_eligible_command_whitelist() -> None:
    assert is_wait_eligible_command("npm run build")
    assert is_wait_eligible_command("pytest -q tests/")
    assert is_wait_eligible_command("make build")
    assert not is_wait_eligible_command("make install")
    assert not is_wait_eligible_command("npm install")


def test_parse_background_spawn_from_record() -> None:
    info = parse_background_spawn_from_record(
        "bash_code_execute_tool",
        {"command": "npm run build", "run_in_background": True},
        "Background process started.\n  pid: 4242\n  command: npm run build",
    )
    assert info is not None
    assert info.pid == 4242
    assert "npm run build" in info.command


def test_find_latest_background_spawn_in_window() -> None:
    records = [
        CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="a",
            args={"command": "echo hi", "run_in_background": True},
            result_content="pid: 1",
        ),
        CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="b",
            args={"command": "pytest -q", "run_in_background": True},
            result_content="Background process started.\n  pid: 99\n",
        ),
    ]
    info = find_latest_background_spawn_in_window(records)
    assert info is not None
    assert info.pid == 99
