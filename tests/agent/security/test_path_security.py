"""Tests for path_security module — dangerous paths and sensitive file detection."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.security.path_security import (
    BLOCKED_DEVICE_NAMES,
    DANGEROUS_PATHS,
    MAX_PATH_LENGTH,
    SENSITIVE_FILE_PATTERNS,
    coerce_filesystem_path,
    is_blocked_device_path,
    is_content_not_path,
    is_dangerous_path,
    is_protected_instruction_file,
    is_sensitive_file,
    safe_join_path,
)
from myrm_agent_harness.core.security.path_security import is_within_boundary


class TestCoerceFilesystemPath:
    """Test coerce_filesystem_path() runtime type guard."""

    def test_none_and_empty_string(self) -> None:
        assert coerce_filesystem_path(None) is None
        assert coerce_filesystem_path("") is None
        assert coerce_filesystem_path("   ") is None

    def test_str_and_path(self) -> None:
        assert coerce_filesystem_path("/tmp/ws") == Path("/tmp/ws")
        assert coerce_filesystem_path(Path("/tmp/ws")) == Path("/tmp/ws")

    def test_rejects_magicmock_and_arbitrary_objects(self) -> None:
        assert coerce_filesystem_path(MagicMock()) is None
        assert coerce_filesystem_path(123) is None
        assert coerce_filesystem_path(["/tmp/ws"]) is None


class TestDangerousPaths:
    """Verify DANGEROUS_PATHS contains expected entries."""

    def test_unix_system_roots_present(self) -> None:
        for path in ("/etc", "/sys", "/proc", "/dev", "/root", "/boot", "/var/log"):
            real = os.path.realpath(path)
            assert real in DANGEROUS_PATHS, f"{path} (resolved: {real}) not in DANGEROUS_PATHS"

    def test_user_sensitive_dirs_present(self) -> None:
        for path in ("~/.ssh", "~/.gnupg", "~/.aws", "~/.docker", "~/.kube"):
            real = os.path.realpath(os.path.expanduser(path))
            assert real in DANGEROUS_PATHS, f"{path} (resolved: {real}) not in DANGEROUS_PATHS"

    def test_docker_and_kube_included(self) -> None:
        docker_real = os.path.realpath(os.path.expanduser("~/.docker"))
        kube_real = os.path.realpath(os.path.expanduser("~/.kube"))
        assert docker_real in DANGEROUS_PATHS
        assert kube_real in DANGEROUS_PATHS

    def test_windows_paths_on_windows(self) -> None:
        with patch("myrm_agent_harness.agent.security.path_security.platform.system", return_value="Windows"):
            from myrm_agent_harness.agent.security.path_security import _build_dangerous_paths

            result = _build_dangerous_paths()
            win_paths = {
                "C:\\Windows\\System32",
                "C:\\Windows\\SysWOW64",
                "C:\\Windows",
                "C:\\Program Files",
                "C:\\ProgramData",
            }
            for wp in win_paths:
                real = os.path.realpath(wp)
                assert real in result, f"{wp} should be in dangerous paths on Windows"


class TestIsDangerousPath:
    """Test is_dangerous_path() function."""

    def test_exact_dangerous_path(self) -> None:
        assert is_dangerous_path("/etc") is True

    def test_child_of_dangerous_path(self) -> None:
        assert is_dangerous_path("/etc/passwd") is True
        assert is_dangerous_path("/etc/nginx/nginx.conf") is True

    def test_ssh_dir(self) -> None:
        assert is_dangerous_path("~/.ssh/id_rsa") is True

    def test_docker_dir(self) -> None:
        assert is_dangerous_path("~/.docker/config.json") is True

    def test_kube_dir(self) -> None:
        assert is_dangerous_path("~/.kube/config") is True

    def test_safe_path(self) -> None:
        assert is_dangerous_path("/tmp/safe_file.txt") is False
        assert is_dangerous_path("/home/user/project/main.py") is False

    def test_partial_name_no_false_positive(self) -> None:
        assert is_dangerous_path("/etcetera/something") is False

    def test_tilde_expansion(self) -> None:
        assert is_dangerous_path("~/.aws/credentials") is True


class TestIsSensitiveFile:
    """Test is_sensitive_file() function."""

    def test_ssh_keys(self) -> None:
        assert is_sensitive_file("/home/user/.ssh/id_rsa") is True
        assert is_sensitive_file("id_ed25519") is True

    def test_pem_key_files(self) -> None:
        assert is_sensitive_file("server.pem") is True
        assert is_sensitive_file("/path/to/cert.key") is True
        assert is_sensitive_file("bundle.p12") is True

    def test_env_files(self) -> None:
        assert is_sensitive_file(".env") is True
        assert is_sensitive_file(".env.local") is True
        assert is_sensitive_file("/project/.env.production") is True

    def test_credential_files(self) -> None:
        assert is_sensitive_file("credentials.json") is True
        assert is_sensitive_file("secrets.json") is True

    def test_database_files(self) -> None:
        assert is_sensitive_file("data.db") is True
        assert is_sensitive_file("app.sqlite3") is True

    def test_password_files(self) -> None:
        assert is_sensitive_file("passwd") is True
        assert is_sensitive_file("shadow") is True

    def test_safe_files(self) -> None:
        assert is_sensitive_file("main.py") is False
        assert is_sensitive_file("README.md") is False
        assert is_sensitive_file("package.json") is False

    def test_aws_credentials(self) -> None:
        assert is_sensitive_file("/home/user/.aws/credentials") is True

    def test_git_config(self) -> None:
        assert is_sensitive_file("/project/.git/config") is True


class TestSensitiveFilePatterns:
    """Verify SENSITIVE_FILE_PATTERNS tuple integrity."""

    def test_not_empty(self) -> None:
        assert len(SENSITIVE_FILE_PATTERNS) > 0

    def test_all_strings(self) -> None:
        for p in SENSITIVE_FILE_PATTERNS:
            assert isinstance(p, str)


class TestSafeJoinPathAndBoundary:
    """Test safe_join_path and is_within_boundary functions."""

    def test_is_within_boundary_safe(self) -> None:
        from myrm_agent_harness.agent.security.path_security import is_within_boundary

        assert is_within_boundary("/safe/workspace/file.txt", "/safe/workspace") is True
        assert is_within_boundary("/safe/workspace/subdir/file.txt", "/safe/workspace") is True

    def test_is_within_boundary_traversal(self) -> None:
        from myrm_agent_harness.agent.security.path_security import is_within_boundary

        assert is_within_boundary("/safe/workspace/../file.txt", "/safe/workspace") is False
        assert is_within_boundary("/etc/passwd", "/safe/workspace") is False

    def test_safe_join_path_safe(self) -> None:

        from myrm_agent_harness.agent.security.path_security import safe_join_path

        result = safe_join_path("/safe/workspace", "subdir/file.txt")
        assert str(result).endswith("subdir/file.txt")

    def test_safe_join_path_null_byte(self) -> None:
        import pytest

        from myrm_agent_harness.agent.security.path_security import safe_join_path

        with pytest.raises(ValueError, match="Null byte injection"):
            safe_join_path("/safe/workspace", "file\0.txt")

    def test_safe_join_path_absolute(self) -> None:
        import pytest

        from myrm_agent_harness.agent.security.path_security import safe_join_path

        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            safe_join_path("/safe/workspace", "/etc/passwd")

    def test_safe_join_path_traversal(self) -> None:
        import pytest

        from myrm_agent_harness.agent.security.path_security import safe_join_path

        with pytest.raises(ValueError, match="Path traversal detected"):
            safe_join_path("/safe/workspace", "../../etc/passwd")

    def test_safe_join_path_symlink_escape(self, tmp_path) -> None:
        import os

        import pytest

        from myrm_agent_harness.agent.security.path_security import safe_join_path

        # Setup: base_dir and an outside file
        base_dir = tmp_path / "workspace"
        base_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("secret")

        # Create a symlink inside workspace pointing outside
        symlink_path = base_dir / "link"
        try:
            os.symlink(outside_file, symlink_path)
        except OSError:
            pytest.skip("Symlinks not supported on this OS/filesystem")

        with pytest.raises(ValueError, match="Path traversal detected"):
            safe_join_path(base_dir, "link")


class TestBlockedDevicePath:
    """Test is_blocked_device_path() and BLOCKED_DEVICE_NAMES."""

    def test_blocked_device_names_set(self) -> None:
        assert "CON" in BLOCKED_DEVICE_NAMES
        assert "NUL" in BLOCKED_DEVICE_NAMES
        assert "PRN" in BLOCKED_DEVICE_NAMES
        assert "AUX" in BLOCKED_DEVICE_NAMES
        assert "COM1" in BLOCKED_DEVICE_NAMES
        assert "LPT1" in BLOCKED_DEVICE_NAMES

    def test_posix_device_paths(self) -> None:
        assert is_blocked_device_path("/dev/zero") is True
        assert is_blocked_device_path("/dev/null") is True
        assert is_blocked_device_path("/dev/urandom") is True
        assert is_blocked_device_path("dev/random") is True
        assert is_blocked_device_path("/proc/kcore") is True
        assert is_blocked_device_path("/sys/kernel") is True

    def test_windows_device_names(self) -> None:
        assert is_blocked_device_path("CON") is True
        assert is_blocked_device_path("con.txt") is True
        assert is_blocked_device_path("NUL") is True
        assert is_blocked_device_path("nul.json") is True
        assert is_blocked_device_path("aux.py") is True
        assert is_blocked_device_path("COM1") is True
        assert is_blocked_device_path(r"\\.\COM1") is True
        assert is_blocked_device_path(r"//./NUL") is True
        assert is_blocked_device_path("src/utils/con.txt") is True

    def test_safe_regular_paths_not_blocked(self) -> None:
        assert is_blocked_device_path("src/index.ts") is False
        assert is_blocked_device_path("config.json") is False
        assert is_blocked_device_path("controller.py") is False
        assert is_blocked_device_path("connect.go") is False
        assert is_blocked_device_path("") is False
        assert is_blocked_device_path("   ") is False


class TestCanonicalPathContainmentGuard:
    """Test is_within_boundary and consolidated path containment behaviors."""

    def test_within_boundary_basic_and_nested(self, tmp_path: Path) -> None:
        from myrm_agent_harness.core.security.path_security import is_within_boundary

        root = tmp_path / "workspace"
        root.mkdir()
        sub = root / "src" / "deep"
        sub.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()

        assert is_within_boundary(sub, root) is True
        assert is_within_boundary(root, root) is True
        assert is_within_boundary(outside, root) is False

    def test_within_boundary_traversal_attack(self, tmp_path: Path) -> None:
        from myrm_agent_harness.core.security.path_security import is_within_boundary

        root = tmp_path / "workspace"
        root.mkdir()
        traversal = root / ".." / "outside"

        assert is_within_boundary(traversal, root) is False

    def test_within_boundary_symlink_escape(self, tmp_path: Path) -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        secret_dir = tmp_path / "etc"
        secret_dir.mkdir()
        symlink_target = root / "escaped_link"

        try:
            os.symlink(secret_dir, symlink_target)
        except OSError:
            pytest.skip("Symlinks not supported")

        assert is_within_boundary(symlink_target, root) is False

    def test_within_boundary_prefix_similarity_attack(self, tmp_path: Path) -> None:
        """Verify sibling directory with same prefix is strictly blocked (prevent startswith flaw)."""
        from myrm_agent_harness.core.security.path_security import is_within_boundary

        root = tmp_path / "workspace"
        root.mkdir()
        sibling_evil = tmp_path / "workspace_evil"
        sibling_evil.mkdir()
        evil_file = sibling_evil / "malicious.py"
        evil_file.write_text("evil")

        assert is_within_boundary(evil_file, root) is False
        assert is_within_boundary(sibling_evil, root) is False

    def test_executor_base_workspace_containment_prefix_attack(self, tmp_path: Path) -> None:
        """Verify CodeExecutor.resolve_path blocks prefix-truncation traversal attacks."""
        import asyncio

        from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
            ExecutionResult,
        )

        ws = tmp_path / "ws"
        ws.mkdir()
        ws_evil = tmp_path / "ws_evil"
        ws_evil.mkdir()
        evil_file = ws_evil / "hack.sh"
        evil_file.write_text("malicious")

        class DummyExecutor(CodeExecutor):
            async def execute(self, context: ExecutionContext) -> ExecutionResult:
                raise NotImplementedError

            async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
                raise NotImplementedError

        executor = DummyExecutor()
        executor.bind_workspace(str(ws))

        # Relative path resolving to sibling with common prefix must be blocked
        with pytest.raises(ValueError, match="Path traversal detected"):
            asyncio.run(executor.resolve_path("../ws_evil/hack.sh"))

    def test_policy_engine_symlink_containment(self, tmp_path: Path) -> None:
        """Verify check_path_policy blocks symlink escapes pointing outside workspace."""
        from myrm_agent_harness.agent.security.checks import check_path_policy
        from myrm_agent_harness.agent.security.types import PathPolicy, PermissionAction

        ws = tmp_path / "workspace"
        ws.mkdir()
        secret_dir = tmp_path / "private_etc"
        secret_dir.mkdir()
        secret_file = secret_dir / "secret.txt"
        secret_file.write_text("classified")

        link_in_ws = ws / "symlink_secret.txt"
        try:
            os.symlink(secret_file, link_in_ws)
        except OSError:
            pytest.skip("Symlinks not supported")

        policy = PathPolicy()
        # Reading a symlink pointing outside allowed roots must require user approval (ASK)
        action, reason = check_path_policy(
            str(link_in_ws), policy, workspace_root=str(ws), require_write=False
        )
        assert action == PermissionAction.ASK
        assert "outside allowed zones" in reason

    def test_validator_forbidden_path_containment(self, tmp_path: Path) -> None:
        """Verify validator._is_forbidden_path correctly detects forbidden path boundaries."""
        from myrm_agent_harness.toolkits.code_execution.security.validator import _is_forbidden_path

        assert _is_forbidden_path("/etc/passwd") is True
        assert _is_forbidden_path("/etc/shadow") is True
        # Path with similar prefix but outside forbidden directory
        assert _is_forbidden_path("/etc/passwd_not_real") is False

    def test_acp_callback_safe_path_containment(self, tmp_path: Path) -> None:
        """Verify acp_callback._resolve_safe_path blocks traversal and symlink escapes."""
        from myrm_agent_harness.toolkits.acp.runtime.acp_callback import _resolve_safe_path

        cwd = tmp_path / "app"
        cwd.mkdir()
        inner_file = cwd / "index.js"
        inner_file.write_text("console.log('hi');")

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.key"
        outside_file.write_text("key")

        # In-bounds relative path succeeds
        assert _resolve_safe_path("index.js", str(cwd)) == inner_file.resolve()
        # Directory traversal fails
        assert _resolve_safe_path("../outside/secret.key", str(cwd)) is None

        # Symlink pointing outside cwd fails
        link = cwd / "link_out.key"
        try:
            os.symlink(outside_file, link)
            assert _resolve_safe_path("link_out.key", str(cwd)) is None
        except OSError:
            pass

    def test_skill_path_filter_containment(self, tmp_path: Path) -> None:
        """Verify is_under_disabled_skill_root accurately blocks paths under disabled roots."""
        from myrm_agent_harness.agent.meta_tools.file_search.skill_path_filter import (
            is_under_disabled_skill_root,
        )

        disabled_root = str(tmp_path / "skills" / "unsafe_skill")
        os.makedirs(disabled_root, exist_ok=True)
        inside_path = os.path.join(disabled_root, "actions", "run.py")
        outside_path = str(tmp_path / "skills" / "unsafe_skill_other" / "run.py")

        assert is_under_disabled_skill_root(inside_path, [disabled_root]) is True
        assert is_under_disabled_skill_root(outside_path, [disabled_root]) is False


class TestContentNotPathDisambiguation:
    """Test is_content_not_path() and safe isolation of text/code content from path checks."""

    def test_normal_paths_not_identified_as_content(self) -> None:
        assert is_content_not_path("/etc/passwd") is False
        assert is_content_not_path("src/core/security.py") is False
        assert is_content_not_path("./relative/path/to/file.txt") is False

    def test_multiline_strings_identified_as_content(self) -> None:
        multiline_snippet = "def hello():\n    return 'world'"
        assert is_content_not_path(multiline_snippet) is True
        assert is_content_not_path("line1\r\nline2") is True

    def test_code_fences_identified_as_content(self) -> None:
        markdown_code = "```python\nprint('hello')\n```"
        assert is_content_not_path(markdown_code) is True

    def test_oversized_text_identified_as_content(self) -> None:
        huge_text = "a" * (MAX_PATH_LENGTH + 10)
        assert is_content_not_path(huge_text) is True

    def test_coerce_filesystem_path_rejects_content(self) -> None:
        assert coerce_filesystem_path("def foo():\n    pass") is None
        assert coerce_filesystem_path("```python\nx = 1\n```") is None
        assert coerce_filesystem_path("x" * (MAX_PATH_LENGTH + 1)) is None

    def test_path_guards_safely_ignore_content_without_crashing(self) -> None:
        content_with_dangerous_pattern = "Review /etc/passwd and config\nMore content here"
        # Should cleanly return False instead of raising File name too long or OSError
        assert is_dangerous_path(content_with_dangerous_pattern) is False
        assert is_blocked_device_path(content_with_dangerous_pattern) is False
        assert is_sensitive_file(content_with_dangerous_pattern) is False
        assert is_protected_instruction_file(content_with_dangerous_pattern) is False

    def test_safe_join_path_raises_on_content(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid path: content or multiline string"):
            safe_join_path(tmp_path, "def main():\n    print('fail')")



