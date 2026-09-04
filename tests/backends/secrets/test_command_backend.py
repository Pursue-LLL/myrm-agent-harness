"""Unit tests for CommandSecretBackend."""

import subprocess
import pytest

from myrm_agent_harness.backends.secrets import CommandExecutionError, CommandSecretBackend


def test_command_secret_backend_success_list():
    backend = CommandSecretBackend(command_template=["echo", "secret_for_$MYRM_SECRET_KEY"])
    val = backend.get_secret("agent-1", "OPENAI_API_KEY")
    assert val == "secret_for_OPENAI_API_KEY"


def test_command_secret_backend_string_template():
    backend = CommandSecretBackend(command_template="printf 'key_%s' '$MYRM_SECRET_KEY'")
    val = backend.get_secret("agent-1", "ANTHROPIC_KEY")
    assert val == "key_ANTHROPIC_KEY"


def test_command_secret_backend_timeout():
    backend = CommandSecretBackend(command_template=["sleep", "2", "$MYRM_SECRET_KEY"], timeout_seconds=0.1)
    backend.command_template = ["sleep", "2"]
    # Provide template with placeholder so extra arg is not appended
    backend = CommandSecretBackend(command_template=["sh", "-c", "sleep 2"], timeout_seconds=0.1)
    with pytest.raises(CommandExecutionError) as exc_info:
        backend.get_secret("agent-1", "SLOW_KEY")
    assert "timed out" in str(exc_info.value)


def test_command_secret_backend_nonzero_returns_none():
    backend = CommandSecretBackend(command_template=["false"])
    val = backend.get_secret("agent-1", "MISSING_KEY")
    assert val is None


def test_command_secret_backend_readonly_contract():
    backend = CommandSecretBackend(command_template=["echo"])
    with pytest.raises(NotImplementedError):
        backend.set_secret("agent-1", "K", "V")
    with pytest.raises(NotImplementedError):
        backend.delete_secret("agent-1", "K")
    with pytest.raises(NotImplementedError):
        backend.delete_all_secrets("agent-1")
    assert backend.get_all_secrets("agent-1") == {}
