"""Platform dispatch for desktop AX snapshot capture.

[INPUT]
- backends.protocols::ComputerBackend (POS: platform I/O protocol)
- perception.{macos_ax,windows_ax,linux_ax} (POS: platform AX capture/invoke)
- dref.types::ElementRef, SnapshotMeta, SnapshotScope (POS: @dref types)
- types::ActionResult (POS: action result container)

[OUTPUT]
- capture_snapshot: platform-routed AX snapshot capture
- inspect_backend: frontmost app metadata inspection
- invoke_element: platform-routed AX element invocation

[POS]
Platform routing dispatch for AX snapshot/invoke. Routes to macOS/Windows/Linux backend.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta, SnapshotScope
from myrm_agent_harness.toolkits.computer_use.perception import linux_ax, macos_ax, windows_ax
from myrm_agent_harness.toolkits.computer_use.types import ActionResult

logger = logging.getLogger(__name__)


def capture_snapshot(
    backend: ComputerBackend,
    scope: SnapshotScope,
    window_title: str | None = None,
) -> tuple[SnapshotMeta, dict[str, ElementRef]]:
    platform = type(backend).__name__
    if platform == "MacOSBackend":
        snapshot = macos_ax.capture_ax_snapshot(scope, window_title)
        return snapshot.meta, snapshot.refs
    if platform == "WindowsBackend":
        snapshot = windows_ax.capture_ax_snapshot(scope, window_title)
        return snapshot.meta, snapshot.refs
    if platform == "LinuxBackend":
        snapshot = linux_ax.capture_ax_snapshot(scope, window_title)
        return snapshot.meta, snapshot.refs
    raise RuntimeError(f"Unsupported backend for AX snapshot: {platform}")


def inspect_backend(backend: ComputerBackend) -> dict[str, str | int | bool]:
    platform = type(backend).__name__
    if platform == "MacOSBackend":
        return macos_ax.inspect_foreground()
    if platform == "WindowsBackend":
        return windows_ax.inspect_foreground()
    if platform == "LinuxBackend":
        return linux_ax.inspect_foreground()
    return {
        "app_name": "",
        "window_title": "",
        "interactive_estimate": 0,
        "needs_permission": False,
        "recommendation": "Use desktop_snapshot_tool, then desktop_vision_tool fallback if needed.",
    }


def invoke_element(
    backend: ComputerBackend,
    element: ElementRef,
    action: str,
    text: str = "",
    app_name: str | None = None,
) -> ActionResult:
    platform = type(backend).__name__
    if platform == "MacOSBackend":
        return macos_ax.invoke_ax_element(element.backend_key, action, text, app_name=app_name)
    if platform == "WindowsBackend":
        return windows_ax.invoke_ax_element(element.backend_key, action, text)
    if platform == "LinuxBackend":
        return linux_ax.invoke_ax_element(element.backend_key, action, text)
    return ActionResult(success=False, error=f"Unsupported backend for AX invoke: {platform}")
