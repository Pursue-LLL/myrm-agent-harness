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
from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import (
    _collect_controls,
)


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

    def test_uiautomation_import_error_returns_none(self) -> None:
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "uiautomation":
                raise ImportError("No module named 'uiautomation'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            assert windows_ax._locate_window("Mail") is None

    def test_root_none_returns_none(self) -> None:
        auto = _make_auto({}, [])
        auto.GetRootControl.return_value = None
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None

    def test_get_children_exception_returns_none(self) -> None:
        auto = _make_auto({}, [])
        auto.GetRootControl.return_value.GetChildren.side_effect = Exception("boom")
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None

    def test_window_with_zero_pid_skipped(self) -> None:
        win = _make_window("Notes - Overview", 0)
        auto = _make_auto({}, [win])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None

    def test_process_name_exception_falls_through(self) -> None:
        win = _make_window("Notes - Overview", 100)
        auto = _make_auto({100: "Mail"}, [win])
        auto.GetProcessNameByPid.side_effect = Exception("boom")
        with _module_with_auto(auto) as module:
            assert module._locate_window("Mail") is None

    def test_title_access_exception_skips_window(self) -> None:
        """A window whose Name access raises must not abort the search loops."""
        good = _make_window("Q3 Report - Excel", 200)
        bad = _make_window("Anything", 100)
        bad.Name = None

        class _BrokenNameWindow:
            ProcessId = 100

            @property
            def Name(self) -> str:  # noqa: N802
                raise Exception("access denied")

            def GetChildren(self) -> list[object]:  # noqa: N802
                return []

        auto = _make_auto({100: "Mail", 200: "EXCEL.EXE"}, [_BrokenNameWindow(), good])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Q3 Report - Excel") is good

    def test_title_substring_matches_when_process_differs(self) -> None:
        """Third pass matches on title substring when title and process name differ."""
        win = _make_window("Archive 2023 Q3 Report - Excel", 500)
        auto = _make_auto({500: "WINWORD"}, [win])
        with _module_with_auto(auto) as module:
            assert module._locate_window("Q3 Report - Excel") is win


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
        with (
            _module_with_auto(auto) as module,
            pytest.raises(AXTreeEmptyError, match="target scope requires app_name"),
        ):
            module.capture_ax_snapshot("target")

    def test_target_not_found_raises(self) -> None:
        win = _make_window("Notes", 300)
        auto = _make_auto({300: "Notes"}, [win])
        with (
            _module_with_auto(auto) as module,
            pytest.raises(AXTreeEmptyError, match="target window not found"),
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
            if (
                getattr(node, "ControlTypeName", "")
                not in windows_ax._INTERACTIVE_TYPES
            ):
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
            if (
                getattr(node, "ControlTypeName", "")
                not in windows_ax._INTERACTIVE_TYPES
            ):
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


class TestCollectControlsEdges:
    """_collect_controls defensive branches: exceptions, empty rect, MAX cap."""

    def test_max_elements_cap_returns(self) -> None:
        button = _make_button()
        root = _make_window("Root", 1)
        root.GetChildren.return_value = [button]
        refs: dict[str, object] = {}
        _collect_controls(root, refs, [500])  # type: ignore[arg-type]
        assert refs == {}

    def test_get_children_exception_returns(self) -> None:
        root = _make_window("Root", 1)
        root.GetChildren.side_effect = Exception("COM error")
        refs: dict[str, object] = {}
        _collect_controls(root, refs, [0])  # type: ignore[arg-type]
        assert refs == {}

    def test_get_value_pattern_exception_keeps_name(self) -> None:
        button = _make_button("Compose")
        button.GetValuePattern.side_effect = Exception("no pattern")
        root = _make_window("Root", 1)
        root.GetChildren.return_value = [button]
        refs: dict[str, object] = {}
        _collect_controls(root, refs, [0])  # type: ignore[arg-type]
        assert refs["d0"].name == "Compose"  # type: ignore[index]

    def test_bounding_rect_exception_skips(self) -> None:
        class _NoRectButton:
            ControlTypeName = "ButtonControl"
            Name = "Compose"
            ProcessId = 100

            def GetValuePattern(self) -> None:  # noqa: N802
                return None

            @property
            def BoundingRectangle(self) -> object:  # noqa: N802
                raise Exception("no rect")

            def GetChildren(self) -> list[object]:  # noqa: N802
                return []

        root = _make_window("Root", 1)
        root.GetChildren.return_value = [_NoRectButton()]
        refs: dict[str, object] = {}
        _collect_controls(root, refs, [0])  # type: ignore[arg-type]
        assert refs == {}

    def test_zero_size_rect_skipped(self) -> None:
        button = _make_button("Compose")
        rect = MagicMock()
        rect.left = 0
        rect.top = 0
        rect.width.return_value = 0
        rect.height.return_value = 30
        button.BoundingRectangle = rect
        root = _make_window("Root", 1)
        root.GetChildren.return_value = [button]
        refs: dict[str, object] = {}
        _collect_controls(root, refs, [0])  # type: ignore[arg-type]
        assert refs == {}


class TestResolveWindowsAppId:
    """_resolve_windows_app_id defensive branches."""

    def test_zero_pid_returns_empty(self) -> None:
        control = _make_window("Mail - Inbox", 0)
        auto = _make_auto({0: "Mail"}, [control])
        with _module_with_auto(auto) as module:
            assert module._resolve_windows_app_id(control) == ""

    def test_exception_returns_empty(self) -> None:
        control = _make_window("Mail - Inbox", 100)
        auto = _make_auto({100: "Mail"}, [control])
        auto.GetProcessNameByPid.side_effect = Exception("boom")
        with _module_with_auto(auto) as module:
            assert module._resolve_windows_app_id(control) == ""

    def test_process_name_prefixed(self) -> None:
        control = _make_window("Mail - Inbox", 100)
        auto = _make_auto({100: "Mail"}, [control])
        with _module_with_auto(auto) as module:
            assert module._resolve_windows_app_id(control) == "win:mail"


class TestCaptureEdges:
    """capture_ax_snapshot defensive branches."""

    def test_uiautomation_missing_raises(self) -> None:
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "uiautomation":
                raise ImportError("No module named 'uiautomation'")
            return original_import(name, *args, **kwargs)

        import myrm_agent_harness.toolkits.computer_use.perception.windows_ax as module

        with (
            patch.object(builtins, "__import__", side_effect=mock_import),
            pytest.raises(AXTreeEmptyError, match="uiautomation not installed"),
        ):
            module.capture_ax_snapshot("foreground")

    def test_foreground_none_raises(self) -> None:
        auto = _make_auto({}, [])
        auto.GetForegroundControl.return_value = None
        with _module_with_auto(auto) as module, pytest.raises(
            AXTreeEmptyError, match="no foreground window"
        ):
            module.capture_ax_snapshot("foreground")

    def test_no_refs_raises(self) -> None:
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = []
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module, pytest.raises(
            AXTreeEmptyError, match="Mail - Inbox"
        ):
            module.capture_ax_snapshot("foreground")


class TestInvokeEdges:
    """invoke_ax_element defensive branches."""

    def test_uiautomation_missing_returns_error(self) -> None:
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "uiautomation":
                raise ImportError("No module named 'uiautomation'")
            return original_import(name, *args, **kwargs)

        import myrm_agent_harness.toolkits.computer_use.perception.windows_ax as module

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = module.invoke_ax_element("0", "click")
        assert not result.success
        assert "uiautomation not installed" in (result.error or "")

    def test_foreground_none_returns_error(self) -> None:
        auto = _make_auto({}, [])
        auto.GetForegroundControl.return_value = None
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click")
        assert not result.success
        assert "No foreground window" in (result.error or "")

    def test_flatten_exception_skips_branch(self) -> None:
        """A node whose GetChildren raises inside _flatten must not abort the walk."""
        button = _make_button()
        broken = _make_window("Broken", 1)
        broken.GetChildren.side_effect = Exception("boom")
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [broken, button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click", app_name="Mail")
        assert result.success is True
        button.Click.assert_called_once()

    def test_stale_index_returns_error(self) -> None:
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = []
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("5", "click")
        assert not result.success
        assert "Stale element index" in (result.error or "")

    def test_fill_sends_keys(self) -> None:
        edit = _make_button("Search")
        edit.ControlTypeName = "EditControl"
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [edit]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "fill", "hello", app_name="Mail")
        assert result.success is True
        edit.SendKeys.assert_called_once_with("hello")

    def test_unsupported_action_returns_error(self) -> None:
        button = _make_button()
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "swipe", app_name="Mail")
        assert not result.success
        assert "Unsupported action" in (result.error or "")

    def test_action_exception_returns_error(self) -> None:
        button = _make_button()
        button.Click.side_effect = Exception("COM failure")
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.invoke_ax_element("0", "click", app_name="Mail")
        assert not result.success
        assert "COM failure" in (result.error or "")


class TestWindowsInspectForeground:
    """windows_ax.inspect_foreground branches."""

    def test_empty_tree_branch(self) -> None:
        window = _make_window("Mail - Inbox", 100)
        window.GetChildren.return_value = []
        auto = _make_auto({100: "Mail"}, [window])
        with _module_with_auto(auto) as module:
            result = module.inspect_foreground()
        assert result["app_name"] == ""
        assert "desktop_vision_tool" in result["recommendation"]

    def test_success_branch_with_hint(self) -> None:
        button = _make_button()
        window = _make_window("Microsoft Excel - Book1", 100)
        window.GetChildren.return_value = [button]
        auto = _make_auto({100: "EXCEL.EXE"}, [window])
        with _module_with_auto(auto) as module:
            result = module.inspect_foreground()
        assert result["app_name"] == "Microsoft Excel - Book1"
        assert result["interactive_estimate"] == 1
        assert "COM/PowerShell" in result["recommendation"]
