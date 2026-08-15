"""Tests for targeted AX capture/invoke in macos_ax.py.

Covers:
- _resolve_target_app: scope → target_app routing
- _run_ax_snapshot: execution + timeout handling
- _parse_ax_output: meta parsing, element extraction, error handling
- capture_ax_snapshot: targeted + fallback + foreground paths
- invoke_ax_element: targeted invoke, unsupported actions, timeout
- _build_ax_snapshot_script / _build_ax_invoke_script: target_app parameter
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
)
from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import (
    _build_ax_invoke_script,
    _build_ax_snapshot_script,
    _parse_ax_output,
    _resolve_target_app,
    _run_ax_snapshot,
    capture_ax_snapshot,
    invoke_ax_element,
)


class TestResolveTargetApp:
    def test_foreground_scope_returns_none(self) -> None:
        assert _resolve_target_app("foreground", None) is None

    def test_foreground_scope_ignores_app_name(self) -> None:
        assert _resolve_target_app("foreground", "TextEdit") is None

    def test_target_scope_with_app_name(self) -> None:
        assert _resolve_target_app("target", "TextEdit") == "TextEdit"

    def test_target_scope_without_app_name(self) -> None:
        assert _resolve_target_app("target", None) is None

    def test_target_scope_empty_string(self) -> None:
        assert _resolve_target_app("target", "") is None


class TestBuildAxSnapshotScript:
    def test_default_uses_frontmost(self) -> None:
        script = _build_ax_snapshot_script()
        assert "first application process whose frontmost is true" in script

    def test_target_app_uses_bundle_id_when_known(self) -> None:
        script = _build_ax_snapshot_script(target_app="TextEdit")
        assert 'whose bundle identifier is "com.apple.TextEdit"' in script
        assert "frontmost" not in script

    def test_target_app_uses_explicit_name_when_unknown(self) -> None:
        script = _build_ax_snapshot_script(target_app="SomeUnknownApp")
        assert 'application process "SomeUnknownApp"' in script
        assert "frontmost" not in script

    def test_target_app_escapes_quotes(self) -> None:
        script = _build_ax_snapshot_script(target_app='App "Pro"')
        assert 'application process "App \\"Pro\\""' in script

    def test_script_contains_pid_capture(self) -> None:
        script = _build_ax_snapshot_script()
        assert "appPid" in script
        assert "unix id of targetApp" in script


class TestBuildAxInvokeScript:
    def test_default_uses_frontmost(self) -> None:
        script = _build_ax_invoke_script()
        assert "first application process whose frontmost is true" in script

    def test_target_app_uses_explicit_name(self) -> None:
        script = _build_ax_invoke_script(target_app="Finder")
        assert 'application process "Finder"' in script
        assert "frontmost" not in script


class TestRunAxSnapshot:
    def test_success(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="output", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            result = _run_ax_snapshot("fake script")
            assert result.returncode == 0

    def test_timeout_raises_ax_tree_empty(self) -> None:
        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=15),
            ),
            pytest.raises(AXTreeEmptyError, match="timed out"),
        ):
            _run_ax_snapshot("fake script")


class TestParseAxOutput:
    def _make_result(self, stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    def test_basic_parse(self) -> None:
        stdout = "TextEdit|||META|||Untitled|||com.apple.TextEdit|||12345\n1|||AXButton|||Save||||||10|||20|||80|||30\n"
        snapshot = _parse_ax_output(self._make_result(stdout), effective_scope="foreground")
        assert snapshot.meta.app_name == "TextEdit"
        assert snapshot.meta.window_title == "Untitled"
        assert snapshot.meta.app_id == "com.apple.TextEdit"
        assert snapshot.meta.pid == 12345
        assert snapshot.meta.scope == "foreground"
        assert len(snapshot.refs) == 1
        ref = next(iter(snapshot.refs.values()))
        assert ref.role == "AXButton"
        assert ref.name == "Save"

    def test_empty_output_raises(self) -> None:
        with pytest.raises(AXTreeEmptyError, match="no AX output"):
            _parse_ax_output(self._make_result(""), effective_scope="foreground")

    def test_nonzero_returncode_raises(self) -> None:
        with pytest.raises(AXTreeEmptyError, match="script error"):
            _parse_ax_output(self._make_result("", returncode=1, stderr="script error"), effective_scope="foreground")

    def test_permission_error_raises(self) -> None:
        with pytest.raises(AXPermissionRequiredError):
            _parse_ax_output(
                self._make_result("", returncode=1, stderr="not allowed assistive access"),
                effective_scope="foreground",
            )

    def test_permission_error_chinese(self) -> None:
        with pytest.raises(AXPermissionRequiredError):
            _parse_ax_output(
                self._make_result("", returncode=1, stderr="不允许辅助访问"),
                effective_scope="foreground",
            )

    def test_no_interactive_elements_raises(self) -> None:
        stdout = "App|||META|||Win|||com.test|||99\n"
        with pytest.raises(AXTreeEmptyError, match="App"):
            _parse_ax_output(self._make_result(stdout), effective_scope="foreground")

    def test_malformed_element_skipped(self) -> None:
        stdout = "App|||META|||Win|||com.test|||99\nbad_line\n1|||AXTextField|||Email||||||10|||20|||80|||30\n"
        snapshot = _parse_ax_output(self._make_result(stdout), effective_scope="foreground")
        assert len(snapshot.refs) == 1

    def test_zero_size_element_skipped(self) -> None:
        stdout = (
            "App|||META|||Win|||com.test|||99\n"
            "1|||AXButton|||OK||||||10|||20|||0|||30\n"
            "2|||AXButton|||Cancel||||||10|||20|||80|||30\n"
        )
        snapshot = _parse_ax_output(self._make_result(stdout), effective_scope="foreground")
        assert len(snapshot.refs) == 1

    def test_pid_missing_defaults_zero(self) -> None:
        stdout = "App|||META|||Win|||com.test\n1|||AXButton|||OK||||||10|||20|||80|||30\n"
        snapshot = _parse_ax_output(self._make_result(stdout), effective_scope="foreground")
        assert snapshot.meta.pid == 0

    def test_text_field_has_fill_action(self) -> None:
        stdout = "App|||META|||Win|||com.test|||99\n1|||AXTextField|||Email||||||10|||20|||80|||30\n"
        snapshot = _parse_ax_output(self._make_result(stdout), effective_scope="foreground")
        ref = next(iter(snapshot.refs.values()))
        assert "fill" in ref.actions
        assert "click" in ref.actions


class TestCaptureAxSnapshot:
    def _mock_snapshot_stdout(self, app_name: str = "App") -> str:
        return f"{app_name}|||META|||Win|||com.test|||99\n1|||AXButton|||OK||||||10|||20|||80|||30\n"

    def test_foreground_scope(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=self._mock_snapshot_stdout(), stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            snapshot = capture_ax_snapshot("foreground")
            assert snapshot.meta.scope == "foreground"

    def test_targeted_success(self) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=self._mock_snapshot_stdout("TextEdit"), stderr=""
        )
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            snapshot = capture_ax_snapshot("target", "TextEdit")
            assert snapshot.meta.app_name == "TextEdit"
            assert snapshot.meta.scope == "target"

    def test_targeted_fails_falls_back_to_foreground(self) -> None:
        call_count = 0
        targeted_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no such app")
        foreground_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=self._mock_snapshot_stdout("Finder"), stderr=""
        )

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return targeted_result
            return foreground_result

        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", side_effect=side_effect
        ):
            snapshot = capture_ax_snapshot("target", "NonExistentApp")
            assert snapshot.meta.scope == "foreground"
            assert snapshot.meta.app_name == "Finder"
            assert call_count == 2


class TestInvokeAxElement:
    def test_unsupported_action(self) -> None:
        result = invoke_ax_element("1", "delete")
        assert not result.success
        assert "Unsupported" in result.error

    def test_click_success(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            result = invoke_ax_element("1", "click")
            assert result.success

    def test_fill_success(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            result = invoke_ax_element("1", "fill", text="hello")
            assert result.success

    def test_targeted_invoke_with_app_name(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = invoke_ax_element("1", "click", app_name="TextEdit")
            assert result.success
            script_arg = mock_run.call_args[0][0][2]
            assert "TextEdit" in script_arg
            assert "frontmost" not in script_arg

    def test_invoke_without_app_name_uses_frontmost(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = invoke_ax_element("1", "click")
            assert result.success
            script_arg = mock_run.call_args[0][0][2]
            assert "frontmost" in script_arg

    def test_timeout(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=10),
        ):
            result = invoke_ax_element("1", "click")
            assert not result.success
            assert "timed out" in result.error

    def test_permission_error(self) -> None:
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not allowed assistive access"
        )
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            result = invoke_ax_element("1", "click")
            assert not result.success
            assert "permission" in result.error.lower()

    def test_double_click_normalized(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = invoke_ax_element("1", "double_click")
            assert result.success
            call_args = mock_run.call_args[0][0]
            assert call_args[3] == "click"

    def test_invoke_failed_returns_error(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="UNSUPPORTED", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            result = invoke_ax_element("1", "focus")
            assert not result.success


class TestAxDispatchCaptureSnapshot:
    def test_macos_routes_correctly(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import capture_snapshot

        mock_backend = MagicMock()
        type(mock_backend).__name__ = "MacOSBackend"
        stdout = "App|||META|||Win|||com.test|||99\n1|||AXButton|||OK||||||10|||20|||80|||30\n"
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ):
            meta, refs = capture_snapshot(mock_backend, "foreground")
            assert meta.app_name == "App"
            assert len(refs) == 1

    def test_unsupported_backend_raises(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import capture_snapshot

        mock_backend = MagicMock()
        type(mock_backend).__name__ = "UnknownBackend"
        with pytest.raises(RuntimeError, match="Unsupported"):
            capture_snapshot(mock_backend, "foreground")


class TestAxDispatchInspectBackend:
    def test_unknown_backend_returns_defaults(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import inspect_backend

        mock_backend = MagicMock()
        type(mock_backend).__name__ = "UnknownBackend"
        result = inspect_backend(mock_backend)
        assert result["app_name"] == ""
        assert result["needs_permission"] is False

    def test_unsupported_invoke_returns_error(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import invoke_element

        mock_backend = MagicMock()
        type(mock_backend).__name__ = "UnknownBackend"
        mock_element = MagicMock()
        mock_element.backend_key = "1"
        result = invoke_element(mock_backend, mock_element, "click")
        assert not result.success
        assert "Unsupported" in result.error


class TestAxDispatchInvokeElement:
    def test_macos_passes_app_name(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import invoke_element

        mock_backend = MagicMock()
        type(mock_backend).__name__ = "MacOSBackend"
        mock_element = MagicMock()
        mock_element.backend_key = "1"

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = invoke_element(mock_backend, mock_element, "click", app_name="TextEdit")
            assert result.success
            script_arg = mock_run.call_args[0][0][2]
            assert "TextEdit" in script_arg

    def test_macos_no_app_name(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import invoke_element

        mock_backend = MagicMock()
        type(mock_backend).__name__ = "MacOSBackend"
        mock_element = MagicMock()
        mock_element.backend_key = "1"

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK", stderr="")
        with patch(
            "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = invoke_element(mock_backend, mock_element, "click")
            assert result.success
            script_arg = mock_run.call_args[0][0][2]
            assert "frontmost" in script_arg
