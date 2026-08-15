"""Tests for linux_ax.invoke_ax_element — input validation, node collection, and action dispatch.

Covers:
- Input validation: invalid backend_key (non-numeric, negative, out-of-range)
- pyatspi ImportError graceful handling
- Empty desktop graceful handling
- Stale element index (TOCTOU scenario)
- Action dispatch: fill, click, unsupported
- getState() consistency between walk() and _collect()
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.dref.errors import AXTreeEmptyError


class TestInvokeInputValidation:
    """Input validation guard at invoke_ax_element entry."""

    def test_non_numeric_backend_key(self) -> None:
        """int('d3') would raise ValueError without guard."""
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import invoke_ax_element

        result = invoke_ax_element("d3", "click")
        assert result.success is False
        assert "Invalid backend_key" in (result.error or "")

    def test_empty_string_backend_key(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import invoke_ax_element

        result = invoke_ax_element("", "click")
        assert result.success is False
        assert "Invalid backend_key" in (result.error or "")

    def test_negative_index(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import invoke_ax_element

        result = invoke_ax_element("-1", "click")
        assert result.success is False
        assert "out of range" in (result.error or "")

    def test_index_exceeds_max_elements(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import (
            _MAX_ELEMENTS,
            invoke_ax_element,
        )

        result = invoke_ax_element(str(_MAX_ELEMENTS), "click")
        assert result.success is False
        assert "out of range" in (result.error or "")

    def test_very_large_index(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import invoke_ax_element

        result = invoke_ax_element("99999", "click")
        assert result.success is False
        assert "out of range" in (result.error or "")


class TestInvokeImportError:
    """Graceful handling when pyatspi is not installed."""

    def test_returns_failure_without_pyatspi(self) -> None:
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "pyatspi":
                raise ImportError("No module named 'pyatspi'")
            return original_import(name, *args, **kwargs)

        from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = linux_ax.invoke_ax_element("0", "click")
        assert result.success is False
        assert "pyatspi not available" in (result.error or "")


class TestInvokeEmptyDesktop:
    """Graceful handling when AT-SPI desktop has no applications."""

    def test_returns_failure_for_empty_desktop(self) -> None:
        mock_pyatspi = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.childCount = 0
        mock_pyatspi.Registry.getDesktop.return_value = mock_desktop

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "click")

        assert result.success is False
        assert "no applications" in (result.error or "")


class TestInvokeStaleIndex:
    """TOCTOU scenario: snapshot had element, but it's gone at invoke time."""

    def test_stale_index_returns_failure(self) -> None:
        mock_pyatspi = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.childCount = 1

        mock_child = MagicMock()
        mock_child.getRoleName.return_value = "frame"
        mock_child.getState.return_value = MagicMock()
        mock_child.childCount = 0
        mock_desktop.getChildAtIndex.return_value = mock_child

        mock_pyatspi.Registry.getDesktop.return_value = mock_desktop

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "click")

        assert result.success is False
        assert "Stale element index" in (result.error or "")


class TestInvokeActionDispatch:
    """Action dispatch for click and fill."""

    def _make_interactive_desktop(self) -> tuple[MagicMock, MagicMock]:
        """Create a mock desktop with one interactive button."""
        mock_pyatspi = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.childCount = 1

        mock_button = MagicMock()
        mock_button.getRoleName.return_value = "push button"
        mock_button.getState.return_value = MagicMock()
        mock_button.childCount = 0

        mock_extents = MagicMock()
        mock_extents.width = 100
        mock_extents.height = 30
        mock_extents.x = 10
        mock_extents.y = 20
        mock_button.queryComponent.return_value.getExtents.return_value = mock_extents

        mock_action = MagicMock()
        mock_action.getNActions.return_value = 1
        mock_button.queryAction.return_value = mock_action

        mock_desktop.getChildAtIndex.return_value = mock_button
        mock_pyatspi.Registry.getDesktop.return_value = mock_desktop

        return mock_pyatspi, mock_button

    def test_click_calls_do_action(self) -> None:
        mock_pyatspi, mock_button = self._make_interactive_desktop()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "click")

        assert result.success is True
        assert "click succeeded" in (result.output or "")
        mock_button.queryAction.return_value.doAction.assert_called_with(0)

    def test_unsupported_action(self) -> None:
        mock_pyatspi, _ = self._make_interactive_desktop()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "invalid_action")

        assert result.success is False
        assert "Unsupported action" in (result.error or "")

    def test_fill_calls_editable_text(self) -> None:
        mock_pyatspi, mock_button = self._make_interactive_desktop()
        mock_button.getRoleName.return_value = "entry"
        mock_editable = MagicMock()
        mock_button.queryEditableText.return_value = mock_editable

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "fill", "hello")

        assert result.success is True
        mock_editable.setTextContents.assert_called_with("hello")

    def test_click_fallback_to_grab_focus(self) -> None:
        """When queryAction has 0 actions, should fallback to grabFocus."""
        mock_pyatspi, mock_button = self._make_interactive_desktop()

        # queryAction returns 0 actions to trigger grabFocus fallback
        mock_action = MagicMock()
        mock_action.getNActions.return_value = 0
        mock_button.queryAction.return_value = mock_action

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "click")

        assert result.success is True
        mock_button.queryComponent.return_value.grabFocus.assert_called()

    def test_fill_fallback_to_xdotool(self) -> None:
        """When EditableText fails, should fallback to xdotool type."""
        mock_pyatspi, mock_button = self._make_interactive_desktop()
        mock_button.getRoleName.return_value = "entry"
        mock_button.queryEditableText.side_effect = Exception("no editable")

        mock_action = MagicMock()
        mock_action.getNActions.return_value = 1
        mock_button.queryAction.return_value = mock_action

        with (
            patch.dict("sys.modules", {"pyatspi": mock_pyatspi}),
            patch("subprocess.run") as mock_run,
        ):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "type", "world")

        assert result.success is True
        mock_action.doAction.assert_called_with(0)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "xdotool" in call_args
        assert "world" in call_args

    def test_getstate_exception_skips_node(self) -> None:
        """Node whose getState() raises should be skipped in _collect (mirrors walk)."""
        mock_pyatspi = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.childCount = 2

        # First child: getState raises → should be skipped
        bad_node = MagicMock()
        bad_node.getRoleName.return_value = "push button"
        bad_node.getState.side_effect = Exception("broken node")
        bad_node.childCount = 0

        # Second child: valid interactive element
        good_node = MagicMock()
        good_node.getRoleName.return_value = "push button"
        good_node.getState.return_value = MagicMock()
        good_node.childCount = 0
        mock_extents = MagicMock()
        mock_extents.width = 50
        mock_extents.height = 20
        good_node.queryComponent.return_value.getExtents.return_value = mock_extents
        mock_good_action = MagicMock()
        mock_good_action.getNActions.return_value = 1
        good_node.queryAction.return_value = mock_good_action

        def get_child(idx: int) -> MagicMock:
            return [bad_node, good_node][idx]

        mock_desktop.getChildAtIndex.side_effect = get_child
        mock_pyatspi.Registry.getDesktop.return_value = mock_desktop

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            # index 0 should be good_node (bad_node was skipped)
            result = linux_ax.invoke_ax_element("0", "click")

        assert result.success is True
        mock_good_action.doAction.assert_called_with(0)


class TestInvokeTargetApp:
    """Scope invoke to a single AT-SPI application by name."""

    def _make_desktop_with_two_apps(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        mock_pyatspi = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.childCount = 2

        slack_button = MagicMock()
        slack_button.getRoleName.return_value = "push button"
        slack_button.getState.return_value = MagicMock()
        slack_button.childCount = 0
        slack_extents = MagicMock()
        slack_extents.width = 100
        slack_extents.height = 30
        slack_button.queryComponent.return_value.getExtents.return_value = slack_extents
        slack_action = MagicMock()
        slack_action.getNActions.return_value = 1
        slack_button.queryAction.return_value = slack_action

        slack_app = MagicMock()
        slack_app.getRoleName.return_value = "application"
        slack_app.name = "Slack"
        slack_app.childCount = 1
        slack_app.getChildAtIndex.side_effect = lambda i: slack_button if i == 0 else None

        notes_app = MagicMock()
        notes_app.getRoleName.return_value = "application"
        notes_app.name = "Notes"
        notes_app.childCount = 0

        mock_desktop.getChildAtIndex.side_effect = lambda i: [slack_app, notes_app][i]
        mock_pyatspi.Registry.getDesktop.return_value = mock_desktop
        return mock_pyatspi, slack_button, notes_app

    def test_target_app_scopes_collection(self) -> None:
        mock_pyatspi, slack_button, _ = self._make_desktop_with_two_apps()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "click", app_name="Slack")

        assert result.success is True
        slack_button.queryAction.return_value.doAction.assert_called_with(0)

    def test_target_app_not_found_stale_index(self) -> None:
        mock_pyatspi, _, _ = self._make_desktop_with_two_apps()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            result = linux_ax.invoke_ax_element("0", "click", app_name="NonExistent")

        assert result.success is False
        assert "Stale element index" in (result.error or "")


class TestCaptureTargetApp:
    """capture_ax_snapshot(scope='target', app_name=...) on Linux."""

    def _make_desktop(self) -> MagicMock:
        mock_pyatspi = MagicMock()
        mock_desktop = MagicMock()
        mock_desktop.childCount = 2

        slack_button = MagicMock()
        slack_button.getRoleName.return_value = "push button"
        slack_button.name = "Send"
        slack_button.getState.return_value = MagicMock()
        slack_button.childCount = 0
        slack_extents = MagicMock()
        slack_extents.width = 100
        slack_extents.height = 30
        slack_extents.x = 5
        slack_extents.y = 10
        slack_button.queryComponent.return_value.getExtents.return_value = slack_extents

        slack_window = MagicMock()
        slack_window.getRoleName.return_value = "frame"
        slack_window.name = "Slack #general"
        slack_window.childCount = 1
        slack_window.getChildAtIndex.side_effect = lambda i: slack_button if i == 0 else None

        slack_app = MagicMock()
        slack_app.getRoleName.return_value = "application"
        slack_app.name = "Slack"
        slack_app.childCount = 1
        slack_app.getChildAtIndex.side_effect = lambda i: slack_window if i == 0 else None

        notes_app = MagicMock()
        notes_app.getRoleName.return_value = "application"
        notes_app.name = "Notes"
        notes_app.childCount = 0

        mock_desktop.getChildAtIndex.side_effect = lambda i: [slack_app, notes_app][i]
        mock_pyatspi.Registry.getDesktop.return_value = mock_desktop
        return mock_pyatspi

    def test_target_success(self) -> None:
        mock_pyatspi = self._make_desktop()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            snapshot = linux_ax.capture_ax_snapshot("target", "Slack")

        assert snapshot.meta.scope == "target"
        assert snapshot.meta.app_name == "Slack"
        assert snapshot.meta.window_title == "Slack #general"
        assert len(snapshot.refs) == 1
        ref = next(iter(snapshot.refs.values()))
        assert ref.name == "Send"

    def test_target_requires_app_name(self) -> None:
        mock_pyatspi = self._make_desktop()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            with pytest.raises(AXTreeEmptyError, match="target scope requires app_name"):
                linux_ax.capture_ax_snapshot("target")

    def test_target_not_found_raises(self) -> None:
        mock_pyatspi = self._make_desktop()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            with pytest.raises(AXTreeEmptyError, match="target window not found"):
                linux_ax.capture_ax_snapshot("target", "NonExistent")

    def test_foreground_collects_all_apps(self) -> None:
        mock_pyatspi = self._make_desktop()

        with patch.dict("sys.modules", {"pyatspi": mock_pyatspi}):
            from importlib import reload

            from myrm_agent_harness.toolkits.computer_use.perception import linux_ax

            reload(linux_ax)
            snapshot = linux_ax.capture_ax_snapshot("foreground")

        assert snapshot.meta.scope == "foreground"
        assert len(snapshot.refs) == 1
