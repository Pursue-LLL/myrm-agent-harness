"""Unit tests for OS-level sandbox module.

Tests cover:
- SandboxPolicy defaults and construction
- NullProvider passthrough behavior
- BwrapProvider command wrapping
- SeatbeltProvider SBPL profile generation
- Auto-detection logic (container heuristic, platform selection)
- PathPolicy → SandboxPolicy bridge
- LocalPersistentSession sandbox integration
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.platform import PlatformInfo
from myrm_agent_harness.toolkits.code_execution.sandbox.detector import (
    _is_inside_container,
    detect_sandbox_provider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.policy_bridge import (
    build_sandbox_policy_from_path_policy,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap import (
    BwrapProvider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import (
    NullProvider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.seatbelt import (
    SeatbeltProvider,
    _generate_sbpl_profile,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxMode,
    SandboxPolicy,
)

# ---------------------------------------------------------------------------
# SandboxPolicy
# ---------------------------------------------------------------------------


class TestSandboxPolicy:
    def test_defaults(self) -> None:
        p = SandboxPolicy()
        assert p.writable_paths == ()
        assert p.readable_paths == ()
        assert p.allow_network is True
        assert "PATH" in p.env_passthrough

    def test_custom_writable(self) -> None:
        p = SandboxPolicy(writable_paths=("/workspace", "/tmp/out"))
        assert p.writable_paths == ("/workspace", "/tmp/out")

    def test_frozen(self) -> None:
        p = SandboxPolicy()
        with pytest.raises(AttributeError):
            p.allow_network = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NullProvider
# ---------------------------------------------------------------------------


class TestNullProvider:
    def test_name(self) -> None:
        assert NullProvider().name == "null"

    def test_is_available(self) -> None:
        assert NullProvider().is_available() is True

    def test_passthrough(self) -> None:
        provider = NullProvider()
        exe, args = provider.wrap_command(
            "/bin/bash",
            ("--norc",),
            "/workspace",
            SandboxPolicy(),
        )
        assert exe == "/bin/bash"
        assert args == ("--norc",)


# ---------------------------------------------------------------------------
# BwrapProvider
# ---------------------------------------------------------------------------


class TestBwrapProvider:
    def test_name(self) -> None:
        assert BwrapProvider().name == "bwrap"

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_available_when_installed(self, _mock: object) -> None:
        assert BwrapProvider().is_available() is True

    @patch("shutil.which", return_value=None)
    def test_unavailable_when_missing(self, _mock: object) -> None:
        assert BwrapProvider().is_available() is False

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_wrap_command_basic(self, _mock: object) -> None:
        provider = BwrapProvider()
        policy = SandboxPolicy(writable_paths=("/home/user/project",))
        exe, args = provider.wrap_command(
            "/bin/bash",
            ("--norc", "--noprofile"),
            "/workspace",
            policy,
        )
        assert exe == "bwrap"
        assert "--ro-bind" in args
        assert "/workspace" in args
        assert "/home/user/project" in args
        assert "--" in args
        idx = args.index("--")
        assert args[idx + 1] == "/bin/bash"

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_network_unshare(self, _mock: object) -> None:
        provider = BwrapProvider()
        policy = SandboxPolicy(allow_network=False)
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", policy)
        assert "--unshare-net" in args

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_no_network_unshare_by_default(self, _mock: object) -> None:
        provider = BwrapProvider()
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", SandboxPolicy())
        assert "--unshare-net" not in args

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_writable_paths_dedup(self, _mock: object) -> None:
        provider = BwrapProvider()
        policy = SandboxPolicy(writable_paths=("/workspace", "/extra"))
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", policy)
        bind_indices = [i for i, a in enumerate(args) if a == "--bind"]
        bound_paths = [args[i + 1] for i in bind_indices]
        assert bound_paths.count("/workspace") == 1
        assert "/extra" in bound_paths

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_pid_namespace_isolation(self, _mock: object) -> None:
        provider = BwrapProvider()
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", SandboxPolicy())
        assert "--unshare-pid" in args

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_new_session_tty_isolation(self, _mock: object) -> None:
        provider = BwrapProvider()
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", SandboxPolicy())
        assert "--new-session" in args

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_tmp_size_limit(self, _mock: object) -> None:
        from myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap import (
            _TMP_SIZE_MB,
        )

        provider = BwrapProvider()
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", SandboxPolicy())
        size_idx = args.index("--size")
        assert args[size_idx + 1] == str(_TMP_SIZE_MB * 1024 * 1024)
        assert args[size_idx + 2] == "--tmpfs"
        assert args[size_idx + 3] == "/tmp"


# ---------------------------------------------------------------------------
# SeatbeltProvider
# ---------------------------------------------------------------------------


class TestSeatbeltProvider:
    def test_name(self) -> None:
        assert SeatbeltProvider().name == "seatbelt"

    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=True)
    def test_available(self, _a: object, _b: object) -> None:
        assert SeatbeltProvider().is_available() is True

    @patch("os.path.isfile", return_value=False)
    def test_unavailable(self, _mock: object) -> None:
        assert SeatbeltProvider().is_available() is False

    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=True)
    def test_wrap_command_uses_inline_profile(self, _a: object, _b: object) -> None:
        provider = SeatbeltProvider()
        exe, args = provider.wrap_command(
            "/bin/bash",
            ("--norc",),
            "/workspace",
            SandboxPolicy(),
        )
        assert exe == "/usr/bin/sandbox-exec"
        assert args[0] == "-p"
        assert "(deny default)" in args[1]
        assert args[2] == "/bin/bash"
        assert args[3] == "--norc"


class TestSBPLProfile:
    def test_workspace_writable(self) -> None:
        profile = _generate_sbpl_profile(SandboxPolicy(), "/workspace")
        assert "(deny default)" in profile
        assert "(allow file-read-data)" in profile
        import os

        resolved = os.path.realpath("/workspace")
        assert f'(allow file-read-data (subpath "{resolved}"))' in profile
        assert f'(allow file-write* (subpath "{resolved}"))' in profile

    def test_custom_writable_paths(self) -> None:
        policy = SandboxPolicy(writable_paths=("/home/user/data",))
        profile = _generate_sbpl_profile(policy, "/workspace")
        import os

        resolved = os.path.realpath("/home/user/data")
        assert f'(subpath "{resolved}")' in profile

    def test_network_allowed(self) -> None:
        profile = _generate_sbpl_profile(
            SandboxPolicy(allow_network=True), "/workspace"
        )
        assert "(allow network*)" in profile

    def test_network_blocked(self) -> None:
        profile = _generate_sbpl_profile(
            SandboxPolicy(allow_network=False), "/workspace"
        )
        assert "block outbound network" in profile
        assert "(allow network* (local udp) (local tcp))" in profile

    def test_symlink_resolved(self) -> None:
        """Verify /tmp is resolved to /private/tmp on macOS."""
        profile = _generate_sbpl_profile(SandboxPolicy(), "/workspace")
        import os

        real_tmp = os.path.realpath("/tmp")
        assert f'(subpath "{real_tmp}")' in profile


# ---------------------------------------------------------------------------
# Container detection
# ---------------------------------------------------------------------------


class TestContainerDetection:
    @patch("os.path.exists", return_value=False)
    @patch("builtins.open", side_effect=OSError)
    def test_not_in_container(self, _a: object, _b: object) -> None:
        assert _is_inside_container() is False

    @patch("os.path.exists", side_effect=lambda p: p == "/.dockerenv")
    def test_docker_detected(self, _mock: object) -> None:
        assert _is_inside_container() is True

    @patch("os.path.exists", side_effect=lambda p: p == "/run/.containerenv")
    def test_podman_detected(self, _mock: object) -> None:
        assert _is_inside_container() is True

    @patch("os.path.exists", return_value=False)
    def test_cgroup_docker_detected(self, _exists: object) -> None:
        from unittest.mock import mock_open

        m = mock_open(read_data="12:memory:/docker/abc123\n")
        with patch("builtins.open", m):
            assert _is_inside_container() is True

    @patch("os.path.exists", return_value=False)
    def test_cgroup_kubepods_detected(self, _exists: object) -> None:
        from unittest.mock import mock_open

        m = mock_open(read_data="11:cpu:/kubepods/burstable/pod-xyz\n")
        with patch("builtins.open", m):
            assert _is_inside_container() is True


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------


def _linux_platform() -> PlatformInfo:
    return PlatformInfo(
        os_type="linux",
        os_release="6.1",
        arch="x86_64",
        is_wsl=False,
        shell_path="/bin/bash",
        shell_args=("--norc", "--noprofile"),
        shell_type="bash",
        exit_code_var="$?",
        env_set_template="export {key}={value}",
        path_separator=":",
        process_group_creation_flag=0,
        safe_env_vars=frozenset({"PATH"}),
    )


def _macos_platform() -> PlatformInfo:
    return PlatformInfo(
        os_type="macos",
        os_release="24.0",
        arch="arm64",
        is_wsl=False,
        shell_path="/bin/bash",
        shell_args=("--norc", "--noprofile"),
        shell_type="bash",
        exit_code_var="$?",
        env_set_template="export {key}={value}",
        path_separator=":",
        process_group_creation_flag=0,
        safe_env_vars=frozenset({"PATH"}),
    )


def _windows_platform() -> PlatformInfo:
    return PlatformInfo(
        os_type="windows",
        os_release="10.0",
        arch="AMD64",
        is_wsl=False,
        shell_path="cmd.exe",
        shell_args=("/Q",),
        shell_type="cmd",
        exit_code_var="%ERRORLEVEL%",
        env_set_template="set {key}={value}",
        path_separator=";",
        process_group_creation_flag=0x200,
        safe_env_vars=frozenset({"PATH"}),
    )


class TestDetector:
    def test_disable_mode(self) -> None:
        provider, status = detect_sandbox_provider(SandboxMode.DISABLE)
        assert isinstance(provider, NullProvider)
        assert status.enabled is False

    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=True,
    )
    def test_auto_in_container(self, _mock: object) -> None:
        provider, status = detect_sandbox_provider(SandboxMode.AUTO, _linux_platform())
        assert isinstance(provider, NullProvider)
        assert status.enabled is False
        assert "container" in status.reason

    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=False,
    )
    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_auto_linux_with_bwrap(self, _a: object, _b: object) -> None:
        provider, status = detect_sandbox_provider(SandboxMode.AUTO, _linux_platform())
        assert isinstance(provider, BwrapProvider)
        assert status.enabled is True
        assert status.provider_name == "bwrap"

    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=False,
    )
    @patch("os.path.isfile", return_value=True)
    @patch("os.access", return_value=True)
    def test_auto_macos_with_seatbelt(self, _a: object, _b: object, _c: object) -> None:
        provider, status = detect_sandbox_provider(SandboxMode.AUTO, _macos_platform())
        assert isinstance(provider, SeatbeltProvider)
        assert status.enabled is True
        assert status.provider_name == "seatbelt"

    def test_windows_null(self) -> None:
        provider, status = detect_sandbox_provider(
            SandboxMode.AUTO, _windows_platform()
        )
        assert isinstance(provider, NullProvider)
        assert status.enabled is False

    def test_enable_windows_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not supported on Windows"):
            detect_sandbox_provider(SandboxMode.ENABLE, _windows_platform())

    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=False,
    )
    @patch("shutil.which", return_value=None)
    def test_enable_linux_no_bwrap_raises(self, _a: object, _b: object) -> None:
        with pytest.raises(RuntimeError, match="bwrap"):
            detect_sandbox_provider(SandboxMode.ENABLE, _linux_platform())

    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=False,
    )
    @patch("shutil.which", return_value=None)
    def test_auto_linux_no_bwrap_fallback(self, _a: object, _b: object) -> None:
        provider, status = detect_sandbox_provider(SandboxMode.AUTO, _linux_platform())
        assert isinstance(provider, NullProvider)
        assert status.enabled is False
        assert "no sandbox tool" in status.reason


# ---------------------------------------------------------------------------
# BwrapProvider readable_paths
# ---------------------------------------------------------------------------


class TestBwrapReadablePaths:
    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_readable_paths_added(self, _mock: object) -> None:
        provider = BwrapProvider()
        policy = SandboxPolicy(readable_paths=("/opt/data", "/srv/cache"))
        _, args = provider.wrap_command("/bin/bash", (), "/workspace", policy)
        ro_bind_indices = [i for i, a in enumerate(args) if a == "--ro-bind"]
        ro_bound = [args[i + 1] for i in ro_bind_indices]
        assert "/opt/data" in ro_bound
        assert "/srv/cache" in ro_bound


# ---------------------------------------------------------------------------
# Policy bridge
# ---------------------------------------------------------------------------


class TestPolicyBridge:
    def test_basic(self) -> None:
        policy = build_sandbox_policy_from_path_policy("/workspace")
        assert "/workspace" in policy.writable_paths

    def test_allowed_roots_propagated(self) -> None:
        policy = build_sandbox_policy_from_path_policy(
            "/workspace",
            allowed_roots=("/home/user/data", "/opt/tools"),
        )
        assert "/home/user/data" in policy.writable_paths
        assert "/opt/tools" in policy.writable_paths
        assert "/workspace" in policy.writable_paths

    def test_dedup(self) -> None:
        policy = build_sandbox_policy_from_path_policy(
            "/workspace",
            allowed_roots=("/workspace",),
            extra_writable=("/workspace",),
        )
        assert policy.writable_paths.count("/workspace") == 1

    def test_network_control(self) -> None:
        policy = build_sandbox_policy_from_path_policy("/ws", allow_network=False)
        assert policy.allow_network is False


# ---------------------------------------------------------------------------
# LocalPersistentSession sandbox integration
# ---------------------------------------------------------------------------


class TestSessionSandboxIntegration:
    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=True,
    )
    def test_session_auto_null_in_container(self, _mock: object) -> None:
        from myrm_agent_harness.toolkits.code_execution.session import (
            LocalPersistentSession,
            SessionConfig,
        )

        config = SessionConfig(session_id="test", work_dir="/tmp/test")
        session = LocalPersistentSession(config)
        assert session.is_sandboxed is False
        assert session.sandbox_status.provider_name == "null"

    def test_session_disabled_sandbox(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.session import (
            LocalPersistentSession,
            SessionConfig,
        )

        config = SessionConfig(
            session_id="test", work_dir="/tmp/test", sandbox_mode="disable"
        )
        session = LocalPersistentSession(config)
        assert session.is_sandboxed is False

    @patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector._is_inside_container",
        return_value=False,
    )
    @patch("shutil.which", return_value="/usr/bin/bwrap")
    def test_session_sandbox_enabled_linux(self, _a: object, _b: object) -> None:
        from myrm_agent_harness.toolkits.code_execution.session import (
            LocalPersistentSession,
            SessionConfig,
        )

        platform = _linux_platform()
        config = SessionConfig(session_id="test", work_dir="/workspace")
        session = LocalPersistentSession(config, platform_info=platform)
        assert session.is_sandboxed is True
        assert session.sandbox_status.provider_name == "bwrap"
