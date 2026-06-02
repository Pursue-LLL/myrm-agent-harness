"""Tests for path_security module — dangerous paths and sensitive file detection."""

from __future__ import annotations

import os
from unittest.mock import patch

from myrm_agent_harness.agent.security.path_security import (
    DANGEROUS_PATHS,
    SENSITIVE_FILE_PATTERNS,
    is_dangerous_path,
    is_sensitive_file,
)


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
