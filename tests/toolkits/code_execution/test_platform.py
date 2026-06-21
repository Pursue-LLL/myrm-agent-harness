"""Tests for toolkits/code_execution/platform.py — platform detection and environment prompt."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.platform import (
    PlatformInfo,
    _detect_wsl,
    detect_platform,
)


class TestDetectPlatform:
    """detect_platform() returns a valid PlatformInfo for the current host."""

    def test_returns_platform_info(self):
        info = detect_platform()
        assert isinstance(info, PlatformInfo)
        assert info.os_type in ("windows", "macos", "linux")
        assert info.arch
        assert info.shell_path

    def test_is_cached(self):
        a = detect_platform()
        b = detect_platform()
        assert a is b


class TestPlatformInfoProperties:
    """PlatformInfo derived properties."""

    @pytest.fixture
    def macos_info(self) -> PlatformInfo:
        return PlatformInfo(
            os_type="macos",
            os_release="24.6.0",
            arch="arm64",
            is_wsl=False,
            shell_path="/bin/bash",
            shell_args=("--norc", "--noprofile"),
            shell_type="bash",
            exit_code_var="$?",
            env_set_template="export {key}={value}",
            path_separator=":",
            process_group_creation_flag=0,
            safe_env_vars=frozenset(),
        )

    @pytest.fixture
    def windows_info(self) -> PlatformInfo:
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
            process_group_creation_flag=0x00000200,
            safe_env_vars=frozenset(),
        )

    @pytest.fixture
    def linux_wsl_info(self) -> PlatformInfo:
        return PlatformInfo(
            os_type="linux",
            os_release="5.15.0",
            arch="x86_64",
            is_wsl=True,
            shell_path="/bin/bash",
            shell_args=("--norc", "--noprofile"),
            shell_type="bash",
            exit_code_var="$?",
            env_set_template="export {key}={value}",
            path_separator=":",
            process_group_creation_flag=0,
            safe_env_vars=frozenset(),
        )

    @pytest.fixture
    def linux_info(self) -> PlatformInfo:
        return PlatformInfo(
            os_type="linux",
            os_release="6.1.0",
            arch="x86_64",
            is_wsl=False,
            shell_path="/bin/bash",
            shell_args=("--norc", "--noprofile"),
            shell_type="bash",
            exit_code_var="$?",
            env_set_template="export {key}={value}",
            path_separator=":",
            process_group_creation_flag=0,
            safe_env_vars=frozenset(),
        )

    def test_is_windows(self, windows_info: PlatformInfo, macos_info: PlatformInfo):
        assert windows_info.is_windows is True
        assert macos_info.is_windows is False

    def test_is_posix(self, macos_info: PlatformInfo, linux_info: PlatformInfo, windows_info: PlatformInfo):
        assert macos_info.is_posix is True
        assert linux_info.is_posix is True
        assert windows_info.is_posix is False

    def test_prompt_label_macos(self, macos_info: PlatformInfo):
        label = macos_info.prompt_label
        assert "macOS" in label
        assert "24.6.0" in label
        assert "arm64" in label

    def test_prompt_label_windows(self, windows_info: PlatformInfo):
        assert "Windows" in windows_info.prompt_label

    def test_prompt_label_wsl(self, linux_wsl_info: PlatformInfo):
        label = linux_wsl_info.prompt_label
        assert "Linux" in label
        assert "WSL" in label

    def test_shell_hint_macos(self, macos_info: PlatformInfo):
        hint = macos_info.shell_hint
        assert "bash" in hint
        assert "BSD" in hint

    def test_shell_hint_windows(self, windows_info: PlatformInfo):
        assert "cmd.exe" in windows_info.shell_hint

    def test_shell_hint_wsl(self, linux_wsl_info: PlatformInfo):
        hint = linux_wsl_info.shell_hint
        assert "WSL" in hint

    def test_shell_hint_linux(self, linux_info: PlatformInfo):
        hint = linux_info.shell_hint
        assert "GNU" in hint


class TestEnvironmentPromptLine:
    """environment_prompt_line property."""

    @pytest.fixture
    def macos_info(self) -> PlatformInfo:
        return PlatformInfo(
            os_type="macos",
            os_release="24.6.0",
            arch="arm64",
            is_wsl=False,
            shell_path="/bin/bash",
            shell_args=("--norc", "--noprofile"),
            shell_type="bash",
            exit_code_var="$?",
            env_set_template="export {key}={value}",
            path_separator=":",
            process_group_creation_flag=0,
            safe_env_vars=frozenset(),
        )

    def test_contains_environment_tag(self, macos_info: PlatformInfo):
        line = macos_info.environment_prompt_line
        assert "<environment>" in line
        assert "</environment>" in line

    def test_contains_os_info(self, macos_info: PlatformInfo):
        line = macos_info.environment_prompt_line
        assert "OS:" in line
        assert "macOS" in line

    def test_contains_shell_info(self, macos_info: PlatformInfo):
        line = macos_info.environment_prompt_line
        assert "Shell:" in line

    def test_idempotent(self, macos_info: PlatformInfo):
        a = macos_info.environment_prompt_line
        b = macos_info.environment_prompt_line
        assert a == b

    def test_env_probe_failure_does_not_crash(self, macos_info: PlatformInfo):
        with patch(
            "myrm_agent_harness.toolkits.code_execution.env_probe.get_environment_probe_line",
            side_effect=RuntimeError("boom"),
        ):
            line = macos_info.environment_prompt_line
            assert "<environment>" in line
            assert "OS:" in line

    def test_env_probe_empty_omits_python(self, macos_info: PlatformInfo):
        with patch(
            "myrm_agent_harness.toolkits.code_execution.env_probe.get_environment_probe_line",
            return_value="",
        ):
            line = macos_info.environment_prompt_line
            assert "Python" not in line
            assert "OS:" in line

    def test_env_probe_nonempty_includes_python(self, macos_info: PlatformInfo):
        probe_line = "Python toolchain: python3=3.12.4, pip=missing."
        with patch(
            "myrm_agent_harness.toolkits.code_execution.env_probe.get_environment_probe_line",
            return_value=probe_line,
        ):
            line = macos_info.environment_prompt_line
            assert probe_line in line

    def test_vnc_probe_failure_does_not_crash(self, macos_info: PlatformInfo):
        with patch(
            "myrm_agent_harness.toolkits.vnc.server.get_environment_hint",
            side_effect=RuntimeError("boom"),
        ):
            line = macos_info.environment_prompt_line
            assert "<environment>" in line
            assert "OS:" in line

    def test_vnc_probe_empty_omits_visual_desktop(self, macos_info: PlatformInfo):
        with patch(
            "myrm_agent_harness.toolkits.vnc.server.get_environment_hint",
            return_value="",
        ):
            line = macos_info.environment_prompt_line
            assert "Visual Desktop" not in line

    def test_vnc_probe_nonempty_includes_visual_desktop(self, macos_info: PlatformInfo):
        vnc_hint = "Visual Desktop: Xvfb virtual display (1280x720) with VNC streaming is available."
        with patch(
            "myrm_agent_harness.toolkits.vnc.server.get_environment_hint",
            return_value=vnc_hint,
        ):
            line = macos_info.environment_prompt_line
            assert vnc_hint in line


class TestDetectWSL:
    """WSL detection edge cases."""

    def test_non_linux_returns_false(self):
        with patch("myrm_agent_harness.toolkits.code_execution.platform.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert _detect_wsl() is False

    def test_wsl_env_var_detected(self):
        with (
            patch("myrm_agent_harness.toolkits.code_execution.platform.sys") as mock_sys,
            patch.dict("os.environ", {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False),
        ):
            mock_sys.platform = "linux"
            assert _detect_wsl() is True
