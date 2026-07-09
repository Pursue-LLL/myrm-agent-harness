"""macOS AX AppleScript generation must compile under osascript."""

from __future__ import annotations

import subprocess

from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import (
    _AX_INVOKE_SCRIPT,
    _AX_SNAPSHOT_SCRIPT,
    _build_ax_snapshot_script,
)


def test_ax_snapshot_script_compiles() -> None:
    result = subprocess.run(
        ["osascript", "-e", _AX_SNAPSHOT_SCRIPT],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "syntax error" not in result.stderr.lower()
    assert result.returncode in {0, 1}


def test_ax_snapshot_script_regenerates_consistently() -> None:
    assert _build_ax_snapshot_script() == _AX_SNAPSHOT_SCRIPT


def test_ax_invoke_escape_script_compiles() -> None:
    result = subprocess.run(
        ["osascript", "-e", _AX_INVOKE_SCRIPT, "click", "1", ""],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "syntax error" not in result.stderr.lower()
