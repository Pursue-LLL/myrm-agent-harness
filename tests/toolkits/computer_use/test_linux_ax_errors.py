"""Error-path tests for linux_ax.py.

Covers:
- _try_pyatspi_snapshot: ImportError, empty desktop, element cap, role/state access
  failures, component query failure, child walk failure, target role failure
- capture_ax_snapshot: xdotool fallback matrix (missing, timeout, no title, available)
- invoke_ax_element: collection cap, component/child/target failures, grabFocus
  fallback, action failure
- inspect_foreground: empty tree and success paths
"""

from __future__ import annotations

import builtins
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.dref.errors import AXTreeEmptyError


def _make_button(*, fail_role: bool = False, fail_component: bool = False) -> MagicMock:
    button = MagicMock()
    button.getState.return_value = MagicMock()
    button.childCount = 0
    if fail_role:
        button.getRoleName.side_effect = Exception("role")
    else:
        button.getRoleName.return_value = "push button"
    if fail_component:
        button.queryComponent.side_effect = Exception("component")
    else:
        extents = MagicMock()
        extents.width = 100
        extents.height = 30
        extents.x = 1
        extents.y = 2
        button.queryComponent.return_value.getExtents.return_value = extents
    return button


def _make_app(name: str, children: list[MagicMock]) -> MagicMock:
    app = MagicMock()
    app.getRoleName.return_value = "application"
    app.name = name
    app.childCount = len(children)
    app.getChildAtIndex.side_effect = lambda i: children[i]
    return app


def _reload_with(pyatspi: MagicMock | None):
    import sys as _sys

    from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

    if pyatspi is not None:
        # pyatspi is imported lazily inside functions, so the mock must stay in
        # sys.modules beyond the reload window for invoke/capture to see it.
        _sys.modules["pyatspi"] = pyatspi
        from importlib import reload

        reload(linux_ax)
    else:
        _sys.modules.pop("pyatspi", None)
        original_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "pyatspi":
                raise ImportError("No module named 'pyatspi'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            from importlib import reload

            reload(linux_ax)
    return linux_ax


class TestPyatspiSnapshotImportError:
    def test_missing_pyatspi_returns_none(self) -> None:
        module = _reload_with(None)
        assert module._try_pyatspi_snapshot() is None


class TestPyatspiSnapshotEmptyDesktop:
    def test_empty_desktop_returns_none(self) -> None:
        desktop = MagicMock()
        desktop.childCount = 0
        pyatspi = MagicMock()
        pyatspi.Registry.getDesktop.return_value = desktop
        module = _reload_with(pyatspi)
        assert module._try_pyatspi_snapshot() is None


class TestPyatspiSnapshotElementCap:
    def test_hits_element_cap_truncates(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import (
            _MAX_ELEMENTS,
        )

        button = _make_button()
        app = _make_app("Slack", [button] * (_MAX_ELEMENTS + 1))

        desktop = MagicMock()
        desktop.childCount = 1
        desktop.getChildAtIndex.return_value = app
        pyatspi = MagicMock()
        pyatspi.Registry.getDesktop.return_value = desktop

        module = _reload_with(pyatspi)
        snapshot = module._try_pyatspi_snapshot()
        assert snapshot is not None
        assert snapshot.meta.truncated is True
        assert len(snapshot.refs) == _MAX_ELEMENTS


class TestPyatspiSnapshotWalkFailures:
    def _desktop_with(self, child: MagicMock) -> MagicMock:
        desktop = MagicMock()
        desktop.childCount = 1
        desktop.getChildAtIndex.return_value = child
        pyatspi = MagicMock()
        pyatspi.Registry.getDesktop.return_value = desktop
        return pyatspi

    def test_role_failure_returns_none(self) -> None:
        bad = MagicMock()
        bad.getRoleName.side_effect = Exception("role")
        bad.childCount = 0
        module = _reload_with(self._desktop_with(bad))
        assert module._try_pyatspi_snapshot() is None

    def test_component_failure_skips_element(self) -> None:
        button = _make_button(fail_component=True)
        app = _make_app("Slack", [button])
        module = _reload_with(self._desktop_with(app))
        snapshot = module._try_pyatspi_snapshot()
        assert snapshot is None  # no valid refs collected

    def test_child_walk_failure_returns(self) -> None:
        app = MagicMock()
        app.getRoleName.return_value = "application"
        app.name = "Slack"
        app.childCount = 1
        app.getChildAtIndex.side_effect = Exception("child")
        module = _reload_with(self._desktop_with(app))
        assert module._try_pyatspi_snapshot() is None

    def test_target_child_role_failure_continues(self) -> None:
        bad = MagicMock()
        bad.getRoleName.side_effect = Exception("role")
        app = _make_app("Slack", [_make_button()])
        desktop = MagicMock()
        desktop.childCount = 2
        desktop.getChildAtIndex.side_effect = lambda i: [bad, app][i]
        pyatspi = MagicMock()
        pyatspi.Registry.getDesktop.return_value = desktop
        module = _reload_with(pyatspi)
        snapshot = module._try_pyatspi_snapshot(target_app="Slack")
        assert snapshot is not None
        assert snapshot.meta.app_name == "Slack"


class TestCaptureXdotoolFallback:
    def _no_pyatspi_module(self) -> None:
        import builtins as _builtins

        original_import = _builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "pyatspi":
                raise ImportError("No module named 'pyatspi'")
            return original_import(name, *args, **kwargs)

        self._import_patch = patch.object(_builtins, "__import__", side_effect=mock_import)
        self._import_patch.start()

    def _reload_no_pyatspi(self):
        from importlib import reload

        from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

        reload(linux_ax)
        return linux_ax

    def test_xdotool_missing_raises(self) -> None:
        self._no_pyatspi_module()
        try:
            module = self._reload_no_pyatspi()
            with (
                patch.object(module.shutil, "which", return_value=None),
                pytest.raises(AXTreeEmptyError, match="xdotool missing"),
            ):
                module.capture_ax_snapshot("foreground")
        finally:
            self._import_patch.stop()

    def test_xdotool_timeout_raises(self) -> None:
        self._no_pyatspi_module()
        try:
            module = self._reload_no_pyatspi()
            with (
                patch.object(module.shutil, "which", return_value="/usr/bin/xdotool"),
                patch.object(
                    module.subprocess,
                    "run",
                    side_effect=subprocess.TimeoutExpired("xdotool", 5),
                ),
                pytest.raises(AXTreeEmptyError, match="snapshot failed"),
            ):
                module.capture_ax_snapshot("foreground")
        finally:
            self._import_patch.stop()

    def test_no_title_raises(self) -> None:
        self._no_pyatspi_module()
        try:
            module = self._reload_no_pyatspi()
            result = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            )
            with (
                patch.object(module.shutil, "which", return_value="/usr/bin/xdotool"),
                patch.object(module.subprocess, "run", return_value=result),
                pytest.raises(AXTreeEmptyError, match="no active window title"),
            ):
                module.capture_ax_snapshot("foreground")
        finally:
            self._import_patch.stop()

    def test_title_available_still_raises_fallback(self) -> None:
        self._no_pyatspi_module()
        try:
            module = self._reload_no_pyatspi()
            result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="My Window\n", stderr=""
            )
            with (
                patch.object(module.shutil, "which", return_value="/usr/bin/xdotool"),
                patch.object(module.subprocess, "run", return_value=result),
                pytest.raises(AXTreeEmptyError, match="desktop_vision_tool"),
            ):
                module.capture_ax_snapshot("foreground")
        finally:
            self._import_patch.stop()


def _desktop_with_children(children: list[MagicMock]) -> MagicMock:
    desktop = MagicMock()
    desktop.childCount = len(children)
    desktop.getChildAtIndex.side_effect = lambda i: children[i]
    pyatspi = MagicMock()
    pyatspi.Registry.getDesktop.return_value = desktop
    return pyatspi


class TestInvokeCollectionFailures:
    def test_collection_stops_after_index(self) -> None:
        button = _make_button()
        module = _reload_with(_desktop_with_children([button, button]))
        result = module.invoke_ax_element("0", "click")
        assert result.success is True

    def test_component_failure_yields_stale(self) -> None:
        button = _make_button(fail_component=True)
        module = _reload_with(_desktop_with_children([button]))
        result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "Stale" in result.error

    def test_child_walk_failure_yields_stale(self) -> None:
        app = MagicMock()
        app.getRoleName.return_value = "application"
        app.getState.return_value = MagicMock()
        app.childCount = 1
        app.getChildAtIndex.side_effect = Exception("child")
        module = _reload_with(_desktop_with_children([app]))
        result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "Stale" in result.error

    def test_target_role_failure_continues(self) -> None:
        bad = MagicMock()
        bad.getRoleName.side_effect = Exception("role")
        button = _make_button()
        app = _make_app("Slack", [button])
        module = _reload_with(_desktop_with_children([bad, app]))
        result = module.invoke_ax_element("0", "click", app_name="Slack")
        assert result.success is True


class TestInvokeActionFailures:
    def test_click_grabfocus_fallback_on_action_error(self) -> None:
        button = _make_button()
        button.queryAction.side_effect = Exception("action")
        module = _reload_with(_desktop_with_children([button]))
        result = module.invoke_ax_element("0", "click")
        assert result.success is True
        button.queryComponent.return_value.grabFocus.assert_called()

    def test_action_failure_propagates_error(self) -> None:
        button = _make_button()
        action_if = MagicMock()
        action_if.getNActions.side_effect = Exception("broken action")
        button.queryAction.return_value = action_if
        button.queryComponent.return_value.grabFocus.side_effect = Exception(
            "broken action"
        )
        module = _reload_with(_desktop_with_children([button]))
        result = module.invoke_ax_element("0", "click")
        assert result.success is False
        assert "broken action" in result.error


class TestInspectForegroundLinux:
    def test_empty_tree_returns_recommendation(self) -> None:
        module = _reload_with(None)
        with patch.object(
            module,
            "capture_ax_snapshot",
            side_effect=AXTreeEmptyError("AT-SPI empty"),
        ):
            result = module.inspect_foreground()
        assert result["needs_permission"] is False
        assert "AT-SPI empty" in result["recommendation"]

    def test_success_path_appends_hint(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        meta = SnapshotMeta(
            ref_count=4, app_name="nautilus", window_title="Files", scope="foreground"
        )
        module = _reload_with(None)
        with patch.object(
            module, "capture_ax_snapshot", return_value=MagicMock(meta=meta, refs={})
        ):
            result = module.inspect_foreground()
        assert result["app_name"] == "nautilus"
        assert "D-Bus" in result["recommendation"]
