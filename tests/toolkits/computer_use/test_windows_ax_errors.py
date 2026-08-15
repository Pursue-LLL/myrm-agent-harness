"""Error-path tests for windows_ax.py.

Covers:
- _collect_controls: element cap, GetChildren/GetValuePattern/BoundingRectangle failures
- _resolve_windows_app_id: missing pid, unexpected failure
- _locate_window: uiautomation missing, root/children failures, title/pid access failures
- capture_ax_snapshot: uiautomation missing, empty foreground, no interactive refs
- invoke_ax_element: uiautomation missing, flatten failure, invalid rect, stale index,
  SendKeys fill, unsupported action, action failure
- inspect_foreground: empty tree and permission-required paths
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

import myrm_agent_harness.toolkits.computer_use.perception.windows_ax as windows_ax
from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
)


def _make_interactive_control(
    *, bbox_fails: bool = False, zero_size: bool = False
) -> MagicMock:
    control = MagicMock(
        spec=[
            "ControlTypeName",
            "Name",
            "ProcessId",
            "GetValuePattern",
            "GetChildren",
            "BoundingRectangle",
            "Click",
            "SendKeys",
        ]
    )
    control.ControlTypeName = "ButtonControl"
    control.Name = "Go"
    control.ProcessId = 100
    control.GetValuePattern.return_value = None
    control.GetChildren.return_value = []
    if bbox_fails:
        type(control).BoundingRectangle = PropertyMock(side_effect=Exception("rect"))
    else:
        rect = MagicMock()
        rect.left = 1
        rect.top = 2
        rect.width.return_value = 0 if zero_size else 40
        rect.height.return_value = 0 if zero_size else 20
        control.BoundingRectangle = rect
    return control


def _make_auto(**kwargs) -> MagicMock:
    auto = MagicMock()
    auto.GetForegroundControl.return_value = kwargs.get("foreground", None)
    root = kwargs.get("root")
    auto.GetRootControl.return_value = root
    auto.GetProcessNameByPid.return_value = kwargs.get("process_name", "")
    return auto


@contextmanager
def _module_with_auto(auto: MagicMock):
    with patch.dict("sys.modules", {"uiautomation": auto}):
        from importlib import reload

        reload(windows_ax)
        yield windows_ax


@contextmanager
def _module_without_uiautomation():
    with patch.dict("sys.modules", {"uiautomation": None}):
        from importlib import reload

        reload(windows_ax)
        yield windows_ax


class TestCollectControlsErrors:
    def test_element_cap_reached(self) -> None:
        control = _make_interactive_control()
        refs: dict = {}
        windows_ax._collect_controls(control, refs, [windows_ax._MAX_ELEMENTS])
        assert refs == {}

    def test_get_children_failure_aborts(self) -> None:
        control = _make_interactive_control()
        control.GetChildren.side_effect = Exception("children")
        refs: dict = {}
        windows_ax._collect_controls(control, refs, [0])
        assert refs == {}

    def test_loop_hits_element_cap(self) -> None:
        child = _make_interactive_control()
        control = MagicMock()
        control.GetChildren.return_value = [child] * (windows_ax._MAX_ELEMENTS + 1)
        refs: dict = {}
        windows_ax._collect_controls(control, refs, [0])
        assert len(refs) == windows_ax._MAX_ELEMENTS

    def test_value_pattern_failure_tolerated(self) -> None:
        control = _make_interactive_control()
        control.GetValuePattern.side_effect = Exception("value")
        root = MagicMock()
        root.GetChildren.return_value = [control]
        refs: dict = {}
        windows_ax._collect_controls(root, refs, [0])
        assert "d0" in refs
        assert refs["d0"].value == ""

    def test_bbox_failure_tolerated(self) -> None:
        control = _make_interactive_control(bbox_fails=True)
        refs: dict = {}
        windows_ax._collect_controls(control, refs, [0])
        assert refs == {}


class TestResolveWindowsAppId:
    def test_zero_pid_returns_empty(self) -> None:
        control = _make_interactive_control()
        control.ProcessId = 0
        assert windows_ax._resolve_windows_app_id(control) == ""

    def test_failure_returns_empty(self) -> None:
        control = _make_interactive_control()
        control.ProcessId = MagicMock()
        assert windows_ax._resolve_windows_app_id(control) == ""


class TestLocateWindowErrors:
    def test_uiautomation_missing(self) -> None:
        with _module_without_uiautomation() as module:
            assert module._locate_window("Mail") is None

    def test_root_none(self) -> None:
        auto = _make_auto()
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None

    def test_root_children_failure(self) -> None:
        root = MagicMock()
        root.GetChildren.side_effect = Exception("children")
        auto = _make_auto(root=root)
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None

    def test_access_failures_skipped(self) -> None:
        title_boom = MagicMock(spec=["Name", "ProcessId"])
        type(title_boom).Name = PropertyMock(side_effect=Exception("name"))
        title_boom.ProcessId = 100

        pid_boom = MagicMock(spec=["Name", "ProcessId"])
        pid_boom.Name = "Other Window"
        pid_boom.ProcessId = MagicMock()  # int() raises TypeError

        title_boom2 = MagicMock(spec=["Name", "ProcessId"])
        type(title_boom2).Name = PropertyMock(side_effect=Exception("name2"))
        title_boom2.ProcessId = 100

        root = MagicMock()
        root.GetChildren.return_value = [title_boom, pid_boom, title_boom2]
        auto = _make_auto(root=root)
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None


class TestCaptureSnapshotErrors:
    def test_uiautomation_missing(self) -> None:
        with _module_without_uiautomation() as module:
            with pytest.raises(AXTreeEmptyError):
                module.capture_ax_snapshot("foreground")

    def test_no_foreground_window(self) -> None:
        auto = _make_auto(foreground=None)
        with _module_with_auto(auto) as module:
            with pytest.raises(AXTreeEmptyError, match="no foreground"):
                module.capture_ax_snapshot("foreground")

    def test_no_interactive_refs(self) -> None:
        non_interactive = MagicMock()
        non_interactive.ControlTypeName = "GroupControl"
        non_interactive.GetChildren.return_value = []
        foreground = MagicMock()
        foreground.Name = "Main Window"
        foreground.GetChildren.return_value = [non_interactive]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            with pytest.raises(AXTreeEmptyError, match="Main Window"):
                module.capture_ax_snapshot("foreground")


class TestInvokeElementErrors:
    def test_uiautomation_missing(self) -> None:
        with _module_without_uiautomation() as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "not installed" in result.error

    def test_no_foreground_window(self) -> None:
        auto = _make_auto(foreground=None)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "foreground" in result.error.lower()

    def test_flatten_failure_returns_stale(self) -> None:
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.side_effect = Exception("flatten")
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "Stale" in result.error

    def test_bbox_failure_skips_element(self) -> None:
        control = _make_interactive_control(bbox_fails=True)
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.return_value = [control]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "Stale" in result.error

    def test_zero_size_bbox_skips_element(self) -> None:
        control = _make_interactive_control(zero_size=True)
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.return_value = [control]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "Stale" in result.error

    def test_stale_index(self) -> None:
        control = _make_interactive_control()
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.return_value = [control]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("5", "click")
        assert result.success is False
        assert "Stale element index 5" in result.error

    def test_fill_uses_send_keys(self) -> None:
        control = _make_interactive_control()
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.return_value = [control]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "fill", text="hello")
        assert result.success is True
        control.SendKeys.assert_called_once_with("hello")

    def test_unsupported_action(self) -> None:
        control = _make_interactive_control()
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.return_value = [control]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "scroll")
        assert result.success is False
        assert "Unsupported action" in result.error

    def test_action_failure_propagates_error(self) -> None:
        control = _make_interactive_control()
        control.Click.side_effect = Exception("click failed")
        foreground = MagicMock()
        foreground.ControlTypeName = "PaneControl"
        foreground.GetChildren.return_value = [control]
        auto = _make_auto(foreground=foreground)
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "click failed" in result.error


class TestInspectForegroundErrors:
    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.windows_ax.capture_ax_snapshot",
        side_effect=AXTreeEmptyError("UIA empty"),
    )
    def test_empty_tree(self, mock_snapshot) -> None:
        result = windows_ax.inspect_foreground()
        assert result["needs_permission"] is False
        assert "desktop_vision_tool" in result["recommendation"]

    @patch(
        "myrm_agent_harness.toolkits.computer_use.perception.windows_ax.capture_ax_snapshot",
        side_effect=AXPermissionRequiredError("Windows"),
    )
    def test_permission_required(self, mock_snapshot) -> None:
        result = windows_ax.inspect_foreground()
        assert result["needs_permission"] is True
        assert "permission" in result["recommendation"].lower()
