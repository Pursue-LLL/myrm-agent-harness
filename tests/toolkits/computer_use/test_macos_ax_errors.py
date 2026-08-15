"""Error-path tests for macos_ax.py.

Covers:
- _read_foreground_meta: normal / timeout / non-zero returncode
- _parse_ax_output: role outside filter, malformed bbox coordinates
- invoke_ax_element: non-zero returncode with plain stderr
- inspect_foreground: permission required, AX tree empty with/without app name
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
)
from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import (
    _parse_ax_output,
    _read_foreground_meta,
    inspect_foreground,
    invoke_ax_element,
)

_META_LINE = "TextEdit|||META|||Untitled|||com.apple.TextEdit|||12345"


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _patch_run(result: subprocess.CompletedProcess[str] | Exception):
    return patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.subprocess.run",
        side_effect=result if isinstance(result, Exception) else lambda *a, **k: result,
    )


class TestReadForegroundMeta:
    def test_normal_path(self) -> None:
        with _patch_run(
            _completed("TextEdit|||Untitled|||com.apple.TextEdit")
        ):
            assert _read_foreground_meta() == (
                "TextEdit",
                "Untitled",
                "com.apple.TextEdit",
            )

    def test_timeout_returns_empty(self) -> None:
        with _patch_run(subprocess.TimeoutExpired(cmd="osascript", timeout=5)):
            assert _read_foreground_meta() == ("", "", "")

    def test_nonzero_returncode_returns_empty(self) -> None:
        with _patch_run(_completed("", returncode=1, stderr="error")):
            assert _read_foreground_meta() == ("", "", "")

    def test_short_output_returns_empty_fields(self) -> None:
        with _patch_run(_completed("TextEdit")):
            app_name, window_title, app_id = _read_foreground_meta()
            assert app_name == "TextEdit"
            assert window_title == ""
            assert app_id == ""


class TestParseAxOutputFiltering:
    def test_role_outside_filter_skipped(self) -> None:
        stdout = f"{_META_LINE}\n1|||AXUnknownRole|||Foo||||||10|||20|||80|||30\n"
        with pytest.raises(AXTreeEmptyError):
            _parse_ax_output(
                _completed(stdout), effective_scope="foreground"
            )

    def test_malformed_bbox_skipped(self) -> None:
        stdout = f"{_META_LINE}\n1|||AXButton|||OK||||||10|||abc|||80|||30\n"
        with pytest.raises(AXTreeEmptyError):
            _parse_ax_output(
                _completed(stdout), effective_scope="foreground"
            )


class TestInvokeAxElementPlainError:
    def test_nonzero_returncode_returns_stderr(self) -> None:
        with _patch_run(_completed("", returncode=1, stderr="boom")):
            result = invoke_ax_element("1", "click")
        assert result.success is False
        assert result.error == "boom"


class TestInspectForeground:
    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.capture_ax_snapshot",
        side_effect=AXPermissionRequiredError("macOS"),
    )
    def test_permission_required(self, mock_snapshot) -> None:
        result = inspect_foreground()
        assert result["needs_permission"] is True
        assert "permission" in result["recommendation"].lower()

    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax._read_foreground_meta",
        return_value=("TextEdit", "Untitled", "com.apple.TextEdit"),
    )
    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.capture_ax_snapshot",
        side_effect=AXTreeEmptyError("TextEdit"),
    )
    def test_ax_tree_empty_with_app_name(
        self, mock_snapshot, mock_meta
    ) -> None:
        result = inspect_foreground()
        assert result["app_name"] == "TextEdit"
        assert result["window_title"] == "Untitled"
        assert result["app_id"] == "com.apple.TextEdit"
        assert result["needs_permission"] is False
        assert "desktop_vision_tool" in result["recommendation"]

    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax._read_foreground_meta",
        return_value=("", "", ""),
    )
    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.capture_ax_snapshot",
        side_effect=AXTreeEmptyError("frontmost app"),
    )
    def test_ax_tree_empty_without_app_name(
        self, mock_snapshot, mock_meta
    ) -> None:
        result = inspect_foreground()
        assert result["app_name"] == ""
        assert "desktop_vision_tool" in result["recommendation"]

    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax._read_foreground_meta",
        return_value=("SomeApp", "Window", ""),
    )
    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.macos_ax.capture_ax_snapshot",
        side_effect=AXTreeEmptyError("SomeApp"),
    )
    def test_ax_tree_empty_falls_back_to_foreground_meta(
        self, mock_snapshot, mock_meta
    ) -> None:
        result = inspect_foreground()
        assert result["app_name"] == "SomeApp"
        assert result["window_title"] == "Window"
