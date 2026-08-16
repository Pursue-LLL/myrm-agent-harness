import pytest

from myrm_agent_harness.agent.security.terminal_error_registry import TerminalErrorRegistry


@pytest.fixture
def temp_workspace(tmp_path):
    return tmp_path


def test_registry_persistence(temp_workspace):
    # 1. First instance: add an error
    reg1 = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg1.add("network_blocked")
    assert "network_blocked" in reg1.get_all()

    # Check if file exists
    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    assert storage_file.exists()

    # 2. Second instance: should load from file
    reg2 = TerminalErrorRegistry(workspace_path=temp_workspace)
    assert "network_blocked" in reg2.get_all()


def test_registry_clear(temp_workspace):
    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("any")
    reg.clear()
    assert len(reg.get_all()) == 0

    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    assert not storage_file.exists()


def test_registry_multiple_errors(temp_workspace):
    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("network_blocked")
    reg.add("sandbox_ro")
    assert reg.get_all() == {"network_blocked", "sandbox_ro"}

    # Reload
    reg2 = TerminalErrorRegistry(workspace_path=temp_workspace)
    assert reg2.get_all() == {"network_blocked", "sandbox_ro"}


def test_registry_add_is_idempotent(temp_workspace):
    import json

    reg = TerminalErrorRegistry(workspace_path=temp_workspace)
    reg.add("network_blocked")
    reg.add("network_blocked")
    assert reg.get_all() == {"network_blocked"}

    storage_file = temp_workspace / ".myrm_terminal_errors.json"
    assert json.loads(storage_file.read_text(encoding="utf-8")) == ["network_blocked"]


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
