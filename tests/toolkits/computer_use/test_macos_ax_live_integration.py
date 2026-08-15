"""Live macOS AX integration tests (real osascript, no mock).

Exercises the REAL capture chain on the current machine:
  capture_ax_snapshot("foreground") → osascript → parsed AX tree → @dref refs
  capture_ax_snapshot("target", app) → app selector → same parse path
  inspect_foreground() → real frontmost app metadata

These tests are skipped when the host lacks macOS Accessibility permission
or the AX tree is unavailable, so they are safe to run on any CI host.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
)
from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import (
    capture_ax_snapshot,
    inspect_foreground,
)


def _skip_without_accessibility(exc: BaseException) -> None:
    reason = str(exc)
    if "permission" in reason.lower() or "辅助" in reason:
        pytest.skip(f"macOS Accessibility permission not granted: {reason}")
    if "empty" in reason.lower() or "no AX" in reason:
        pytest.skip(f"AX tree unavailable on this host: {reason}")


def test_live_foreground_snapshot_builds_refs() -> None:
    """Real foreground AX capture must return parsed refs with a valid meta."""
    try:
        snapshot = capture_ax_snapshot("foreground")
    except (AXPermissionRequiredError, AXTreeEmptyError) as exc:
        _skip_without_accessibility(exc)
        return

    assert snapshot.meta.scope == "foreground"
    assert snapshot.meta.app_name, "foreground app_name must be populated"
    assert snapshot.meta.app_id, "foreground bundle id must be populated"
    for ref in snapshot.refs.values():
        assert ref.bbox.width > 0 and ref.bbox.height > 0
        assert ref.ref_id.startswith("d")


def test_live_foreground_refs_are_indices() -> None:
    """@dref backend keys must be sequential indices into the AX tree."""
    try:
        snapshot = capture_ax_snapshot("foreground")
    except (AXPermissionRequiredError, AXTreeEmptyError) as exc:
        _skip_without_accessibility(exc)
        return

    backend_keys = [int(ref.backend_key) for ref in snapshot.refs.values()]
    assert backend_keys == sorted(backend_keys)
    assert len(set(backend_keys)) == len(backend_keys)


def test_live_inspect_foreground_reports_app() -> None:
    """inspect_foreground must report the real frontmost app name."""
    result = inspect_foreground()
    if result["needs_permission"]:
        pytest.skip("macOS Accessibility permission not granted")
    assert result["app_name"], "frontmost app_name must be non-empty"
    assert result["interactive_estimate"] >= 0
    assert "desktop_vision_tool" in result["recommendation"]


def test_live_target_scope_matches_current_app() -> None:
    """scope='target' with the frontmost app must capture the same app window."""
    try:
        foreground = capture_ax_snapshot("foreground")
    except (AXPermissionRequiredError, AXTreeEmptyError) as exc:
        _skip_without_accessibility(exc)
        return

    try:
        targeted = capture_ax_snapshot("target", foreground.meta.app_name)
    except (AXPermissionRequiredError, AXTreeEmptyError) as exc:
        _skip_without_accessibility(exc)
        return

    assert targeted.meta.scope == "target"
    assert (
        targeted.meta.app_name == foreground.meta.app_name
    ), "target capture must resolve to the same app as foreground"
