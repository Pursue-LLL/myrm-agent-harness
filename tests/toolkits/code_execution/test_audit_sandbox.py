import os
import tempfile
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.security.audit_sandbox import (
    SecurityError,
    install,
)


@pytest.fixture
def audit_hook(tmp_path):
    """Fixture to extract the audit hook without installing it globally."""
    hook_capture = []

    def mock_addaudithook(hook):
        hook_capture.append(hook)

    with patch("sys.addaudithook", side_effect=mock_addaudithook):
        install(workspace_path=str(tmp_path), allow_network=False)

    assert len(hook_capture) == 1
    return hook_capture[0], str(tmp_path)


def test_subprocess_execution_blocked(audit_hook):
    hook, _ = audit_hook
    blocked_events = [
        "os.system", "os.exec", "os.posix_spawn", "os.spawn", "subprocess.Popen"
    ]
    for event in blocked_events:
        with pytest.raises(SecurityError, match="Subprocess execution is strictly forbidden"):
            hook(event, ("dummy",))


def test_ctypes_dlopen_blocked(audit_hook):
    hook, _ = audit_hook
    with pytest.raises(SecurityError, match="Dynamic library loading"):
        hook("ctypes.dlopen", ("lib",))


def test_network_isolation_af_unix_allowed(audit_hook):
    hook, _ = audit_hook
    # AF_UNIX uses string path
    hook("socket.connect", ("/tmp/socket.sock",))  # Should not raise


def test_network_isolation_af_inet_blocked_when_network_false(audit_hook):
    hook, _ = audit_hook
    with pytest.raises(SecurityError, match="Network access is blocked"):
        hook("socket.connect", (("127.0.0.1", 80),))


def test_network_isolation_allowed_hosts(tmp_path):
    hook_capture = []
    with patch("sys.addaudithook", side_effect=lambda h: hook_capture.append(h)):
        install(str(tmp_path), allow_network=True, allowed_hosts=frozenset(["api.github.com"]))
    hook = hook_capture[0]

    # Allowed host
    hook("socket.connect", (("api.github.com", 443),))

    # Blocked host
    with pytest.raises(SecurityError, match="Network access to 'evil.com' is blocked"):
        hook("socket.connect", (("evil.com", 80),))


def test_file_isolation_writes_allowed_in_workspace(audit_hook):
    hook, workspace = audit_hook
    allowed_path = os.path.join(workspace, "test.txt")

    # Write mode 'w'
    hook("open", (allowed_path, "w", 0))
    # Write flag
    hook("open", (allowed_path, "r", os.O_WRONLY))
    # Destructive
    hook("os.remove", (allowed_path, None))


def test_file_isolation_writes_blocked_outside_workspace(audit_hook):
    hook, _workspace = audit_hook
    outside_path = "/etc/passwd"

    with pytest.raises(SecurityError, match="Write operation outside allowed workspace blocked"):
        hook("open", (outside_path, "w", 0))

    with pytest.raises(SecurityError, match="Destructive file operation \\(os.remove\\) outside allowed workspace blocked"):
        hook("os.remove", (outside_path, None))


def test_file_isolation_writes_allowed_in_tmpdir(audit_hook):
    hook, _ = audit_hook
    tmp_path = os.path.join(tempfile.gettempdir(), "test.txt")

    hook("open", (tmp_path, "w", 0))
    hook("os.mkdir", (tmp_path, 0o777, None))


def test_file_isolation_sensitive_reads_blocked(audit_hook):
    hook, _ = audit_hook
    sensitive_path = "/root/.ssh/id_rsa"

    with pytest.raises(SecurityError, match="Read access to sensitive file blocked"):
        hook("open", (sensitive_path, "r", 0))


def test_file_isolation_rename_blocked_outside_workspace(audit_hook):
    hook, workspace = audit_hook
    allowed_src = os.path.join(workspace, "test.txt")
    outside_dst = "/etc/hosts"

    with pytest.raises(SecurityError, match="Destructive file operation \\(os.rename\\) outside allowed workspace blocked"):
        hook("os.rename", (allowed_src, outside_dst, None, None))
