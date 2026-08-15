"""Integration tests for perception.ax_dispatch platform routing.

Exercises the REAL dispatch logic (no mocks of dispatch itself): scope/app_name
are routed verbatim to the matching platform perception module, and unsupported
backends fail with a clear RuntimeError. Only the leaf perception calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import (
    capture_snapshot,
    inspect_backend,
    invoke_element,
)
from myrm_agent_harness.toolkits.computer_use.types import ActionResult


def _backend_named(name: str) -> MagicMock:
    backend = MagicMock()
    backend.__class__.__name__ = name
    return backend


@pytest.mark.parametrize(
    "platform,module",
    [
        ("MacOSBackend", "macos_ax"),
        ("WindowsBackend", "windows_ax"),
        ("LinuxBackend", "linux_ax"),
    ],
)
def test_capture_snapshot_routes_scope_and_app_name(platform: str, module: str) -> None:
    meta = SnapshotMeta(ref_count=1, app_name="Mail", scope="target")
    snapshot = MagicMock(meta=meta, refs={"d0": MagicMock()})
    backend = _backend_named(platform)

    with patch(
        f"myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.{module}.capture_ax_snapshot",
        return_value=snapshot,
    ) as mock_capture:
        out_meta, out_refs = capture_snapshot(backend, "target", "Mail")

    mock_capture.assert_called_once_with("target", "Mail")
    assert out_meta is meta
    assert out_refs is snapshot.refs


@pytest.mark.parametrize(
    "platform,module",
    [
        ("MacOSBackend", "macos_ax"),
        ("WindowsBackend", "windows_ax"),
        ("LinuxBackend", "linux_ax"),
    ],
)
def test_capture_snapshot_routes_foreground_without_app(
    platform: str, module: str
) -> None:
    meta = SnapshotMeta(ref_count=0, app_name="Finder", scope="foreground")
    snapshot = MagicMock(meta=meta, refs={})
    backend = _backend_named(platform)

    with patch(
        f"myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.{module}.capture_ax_snapshot",
        return_value=snapshot,
    ) as mock_capture:
        out_meta, out_refs = capture_snapshot(backend, "foreground", None)

    mock_capture.assert_called_once_with("foreground", None)
    assert out_meta is meta
    assert out_refs is snapshot.refs


def test_capture_snapshot_unsupported_backend_raises() -> None:
    with pytest.raises(RuntimeError, match="Unsupported backend"):
        capture_snapshot(_backend_named("UnsupportedBackend"), "foreground", None)


@pytest.mark.parametrize(
    "platform,module",
    [
        ("MacOSBackend", "macos_ax"),
        ("WindowsBackend", "windows_ax"),
        ("LinuxBackend", "linux_ax"),
    ],
)
def test_inspect_backend_routes(platform: str, module: str) -> None:
    expected = {"app_name": "Mail", "needs_permission": False}
    with patch(
        f"myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.{module}.inspect_foreground",
        return_value=expected,
    ) as mock_inspect:
        result = inspect_backend(_backend_named(platform))

    mock_inspect.assert_called_once_with()
    assert result == expected


def test_inspect_backend_unsupported_returns_fallback() -> None:
    result = inspect_backend(_backend_named("UnsupportedBackend"))
    assert result["needs_permission"] is False
    assert "desktop_snapshot_tool" in result["recommendation"]


@pytest.mark.parametrize(
    "platform,module",
    [
        ("MacOSBackend", "macos_ax"),
        ("WindowsBackend", "windows_ax"),
        ("LinuxBackend", "linux_ax"),
    ],
)
def test_invoke_element_routes(platform: str, module: str) -> None:
    element = MagicMock()
    element.backend_key = "0"
    expected = ActionResult(success=True)
    with patch(
        f"myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch.{module}.invoke_ax_element",
        return_value=expected,
    ) as mock_invoke:
        result = invoke_element(_backend_named(platform), element, "click")

    mock_invoke.assert_called_once_with("0", "click", "", app_name=None)
    assert result.success is True


def test_invoke_element_unsupported_returns_error() -> None:
    element = MagicMock()
    result = invoke_element(_backend_named("UnsupportedBackend"), element, "click")
    assert result.success is False
    assert "Unsupported backend" in (result.error or "")
