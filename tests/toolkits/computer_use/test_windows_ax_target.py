"""Tests for windows_ax target-window capture and invoke.

Covers:
- _locate_window: exact title → exact process name → title substring priority, not-found
- capture_ax_snapshot: target path, missing app_name, target not found, foreground path
- invoke_ax_element: target path reuses _locate_window, not-found error
- index consistency between capture (_collect_controls) and invoke (_flatten)
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import myrm_agent_harness.toolkits.computer_use.perception.windows_ax as windows_ax
from myrm_agent_harness.toolkits.computer_use.dref.errors import AXTreeEmptyError
from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _collect_controls


def _make_button(name: str = "Compose") -> MagicMock:
    button = MagicMock()
    button.ControlTypeName = "ButtonControl"
    button.Name = name
    button.ProcessId = 100
    button.GetValuePattern.return_value = None
    rect = MagicMock()
    rect.left = 10
    rect.top = 20
    rect.width.return_value = 80
    rect.height.return_value = 30
    button.BoundingRectangle = rect
    button.GetChildren.return_value = []
    return button


def _make_window(name: str, pid: int) -> MagicMock:
    window = MagicMock()
    window.Name = name
    window.ProcessId = pid
    window.GetChildren.return_value = []
    return window


def _make_auto(process_names: dict[int, str], windows: list[MagicMock]) -> MagicMock:
    auto = MagicMock()
    root = MagicMock()
    root.GetChildren.return_value = windows
    auto.GetRootControl.return_value = root
    auto.GetForegroundControl.return_value = windows[0] if windows else None
    auto.GetProcessNameByPid.side_effect = lambda pid: process_names.get(pid, "")
    return auto


@contextmanager
def _module_with_auto(auto: MagicMock):
    with patch.dict("sys.modules", {"uiautomation": auto}):
        from importlib import reload

        reload(windows_ax)
        yield windows_ax


class TestLocateWindow:
    def test_exact_process_name_match(self) -> None:
        mail_window = _make_window("Mail - Inbox", 100)
        auto = _make_auto({100: "Mail"}, [mail_window])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is mail_window

    def test_title_substring_fallback(self) -> None:
        win = _make_window("Q3 Report - Excel", 200)
        auto = _make_auto({200: "EXCEL.EXE"}, [win])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Excel") is win

    def test_process_name_with_exe_suffix_matches(self) -> None:
        win = _make_window("Excel - Q3", 400)
        auto = _make_auto({400: "EXCEL.EXE"}, [win])
        with _module_with_auto(auto) as module:
            assert module._locate_window("excel") is win

    def test_process_name_match_preferred_over_title(self) -> None:
        exact = _make_window("Mail - Inbox", 100)
        fuzzy = _make_window("Mail Merge", 200)
        auto = _make_auto({100: "Mail", 200: "WORD"}, [fuzzy, exact])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is exact

    def test_exact_title_match_preferred_over_process(self) -> None:
        exact = _make_window("Mail - Inbox", 100)
        other = _make_window("Mail - Inbox", 200)
        auto = _make_auto({100: "MAIL", 200: "MAIL"}, [exact, other])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail - Inbox") is exact

    def test_exact_title_avoids_similar_substring_window(self) -> None:
        foreground = _make_window("Q3 Report - Word", 100)
        similar = _make_window("2023 Q3 Report - Word", 200)
        auto = _make_auto({100: "WINWORD", 200: "WINWORD"}, [similar, foreground])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Q3 Report - Word") is foreground

    def test_not_found_returns_none(self) -> None:
        win = _make_window("Notes", 300)
        auto = _make_auto({300: "Notes"}, [win])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Slack") is None

    def test_empty_app_name_returns_none(self) -> None:
        auto = _make_auto({}, [])
        with _module_with_auto(auto) as module:
            assert module._locate_window("") is None


class TestCaptureTarget:
    def test_target_success(self) -> None:
        button = _make_button()
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            snapshot = module.capture_ax_snapshot("target", "Mail")
        assert snapshot.meta.scope == "target"
        assert snapshot.meta.app_name == "Mail - Inbox"
        assert len(snapshot.refs) == 1
        ref = next(iter(snapshot.refs.values()))
        assert ref.role == "ButtonControl"
        assert ref.name == "Compose"

    def test_target_requires_app_name(self) -> None:
        auto = _make_auto({}, [])
        with _module_with_auto(auto) as module, pytest.raises(
            AXTreeEmptyError, match="target scope requires app_name"
        ):
            module.capture_ax_snapshot("target")

    def test_target_not_found_raises(self) -> None:
        win = _make_window("Notes", 300)
        auto = _make_auto({300: "Notes"}, [win])
        with _module_with_auto(auto) as module, pytest.raises(
            AXTreeEmptyError, match="target window not found"
        ):
            module.capture_ax_snapshot("target", "Slack")

    def test_foreground_path_unchanged(self) -> None:
        button = _make_button()
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            snapshot = module.capture_ax_snapshot("foreground")
        assert snapshot.meta.scope == "foreground"
        assert len(snapshot.refs) == 1


class TestInvokeTarget:
    def test_target_invoke_success(self) -> None:
        button = _make_button()
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click", app_name="Mail")
        assert result.success is True
        button.Click.assert_called_once()

    def test_target_invoke_not_found(self) -> None:
        win = _make_window("Notes", 300)
        auto = _make_auto({300: "Notes"}, [win])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click", app_name="Slack")
        assert result.success is False
        assert "target window not found" in (result.error or "")

    def test_target_invoke_with_exact_title(self) -> None:
        button = _make_button()
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click", app_name="Mail - Inbox")
        assert result.success is True
        button.Click.assert_called_once()

    def test_invoke_without_app_name_uses_foreground(self) -> None:
        button = _make_button()
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert result.success is True
        auto.GetForegroundControl.assert_called()


class TestIndexConsistency:
    """capture (_collect_controls) and invoke (_flatten) must yield identical DFS index order."""

    def test_dfs_order_matches(self) -> None:
        # Tree: root -> [buttonA, buttonB, container -> buttonC]
        button_a = _make_button("A")
        button_b = _make_button("B")
        button_c = _make_button("C")
        container = MagicMock()
        container.GetChildren.return_value = [button_c]
        root = _make_window("Root", 1)
        root.GetChildren.return_value = [button_a, button_b, container]

        refs: dict[str, object] = {}
        _collect_controls(root, refs, [0])  # type: ignore[arg-type]
        capture_order = [refs[f"d{i}"].name for i in range(len(refs))]  # type: ignore[attr-defined]

        # Mirror of the flatten routine inside invoke_ax_element.
        flat: list[object] = []

        def _flatten(node: object) -> None:
            flat.append(node)
            try:
                for child in node.GetChildren():  # type: ignore[attr-defined]
                    _flatten(child)
            except Exception:
                return

        _flatten(root)
        interactive: list[object] = []
        for node in flat:
            if getattr(node, "ControlTypeName", "") not in windows_ax._INTERACTIVE_TYPES:
                continue
            try:
                rect = getattr(node, "BoundingRectangle", None)
            except Exception:
                continue
            if rect is None or rect.width() <= 0 or rect.height() <= 0:
                continue
            interactive.append(node)
        invoke_order = [getattr(node, "Name", "") for node in interactive]

        assert capture_order == invoke_order == ["A", "B", "C"]

    def test_zero_sized_control_skipped_by_both_sides(self) -> None:
        button_a = _make_button("A")
        zero_rect = MagicMock()
        zero_rect.left = 0
        zero_rect.top = 0
        zero_rect.width.return_value = 0
        zero_rect.height.return_value = 30
        zero = _make_button("Zero")
        zero.BoundingRectangle = zero_rect
        root = _make_window("Root", 1)
        root.GetChildren.return_value = [button_a, zero]

        refs: dict[str, object] = {}
        _collect_controls(root, refs, [0])  # type: ignore[arg-type]
        capture_order = [refs[f"d{i}"].name for i in range(len(refs))]  # type: ignore[attr-defined]

        flat: list[object] = []

        def _flatten(node: object) -> None:
            flat.append(node)
            try:
                for child in node.GetChildren():  # type: ignore[attr-defined]
                    _flatten(child)
            except Exception:
                return

        _flatten(root)
        interactive: list[object] = []
        for node in flat:
            if getattr(node, "ControlTypeName", "") not in windows_ax._INTERACTIVE_TYPES:
                continue
            try:
                rect = getattr(node, "BoundingRectangle", None)
            except Exception:
                continue
            if rect is None or rect.width() <= 0 or rect.height() <= 0:
                continue
            interactive.append(node)

        assert capture_order == ["A"]
        assert len(interactive) == 1
        assert getattr(interactive[0], "Name", "") == "A"
