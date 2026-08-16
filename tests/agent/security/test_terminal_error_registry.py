import json

import pytest

from myrm_agent_harness.agent.security.terminal_error_registry import TerminalErrorRegistry


@pytest.fixture
def temp_workspace(tmp_path):
    return tmp_path


def test_runtime_add_is_memory_only(temp_workspace):
    """add() is turn-scoped: it never writes the durable God-Mode file."""
    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("network_blocked")
    assert "network_blocked" in reg.get_all()

    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    assert not storage_file.exists()


def test_god_mode_file_injection_is_merged(temp_workspace):
    """The God-Mode file is a durable injection channel: a fresh instance merges it."""
    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    storage_file.write_text('["network_blocked", "sandbox_ro"]', encoding="utf-8")

    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    assert reg.get_all() == {"network_blocked", "sandbox_ro"}


def test_clear_clears_memory_keeps_god_mode_file(temp_workspace):
    """clear() wipes turn-scoped runtime state but must not unlink the durable file."""
    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    storage_file.write_text('["network_blocked"]', encoding="utf-8")

    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("config_or_auth:search")
    reg.clear()

    assert reg.get_all() == {"network_blocked"}
    assert storage_file.exists()


def test_registry_add_is_idempotent(temp_workspace):
    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("network_blocked")
    reg.add("network_blocked")
    assert reg.get_all() == {"network_blocked"}


def test_registry_corrupt_json_load_is_graceful(temp_workspace):
    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    storage_file.write_text("{not valid json", encoding="utf-8")

    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    assert reg.get_all() == set()


def test_registry_non_list_json_load_is_ignored(temp_workspace):
    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    storage_file.write_text('{"unexpected": true}', encoding="utf-8")

    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    assert reg.get_all() == set()


def test_registry_clear_empty_is_noop(temp_workspace):
    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.clear()
    assert reg.get_all() == set()


def test_merge_preserves_runtime_state_after_reload(temp_workspace):
    """get_all() re-merges the God-Mode file without clobbering turn-scoped state."""
    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    storage_file.write_text('["network_blocked"]', encoding="utf-8")

    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("config_or_auth:search")

    assert reg.get_all() == {"network_blocked", "config_or_auth:search"}
    assert json.loads(storage_file.read_text(encoding="utf-8")) == ["network_blocked"]
