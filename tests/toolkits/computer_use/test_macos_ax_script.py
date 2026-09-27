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


def test_textedit_target_uses_bundle_id_selector() -> None:
    script = _build_ax_snapshot_script(target_app="TextEdit")
    assert 'bundle identifier is "com.apple.TextEdit"' in script
    assert 'application process "TextEdit"' not in script


def test_snapshot_script_resolves_secure_field_before_reading_its_value() -> None:
    """A password field must be identified by subrole and never have its value read.

    macOS reports a password field with role ``AXTextField``; only the subrole distinguishes it.
    The script therefore has to resolve the secure role *before* the ``value`` read, otherwise the
    secret is pulled out of the accessibility tree and can only be masked after the fact.
    """
    script = _AX_SNAPSHOT_SCRIPT
    assert 'subrole of elem' in script
    assert 'set reportRole to "AXSecureTextField"' in script
    # The value read must be guarded, and the reported role must be the resolved one.
    assert 'if reportRole is not "AXSecureTextField" then' in script
    value_guard = script.index('if reportRole is not "AXSecureTextField" then')
    value_read = script.index("set elemValue to value of elem")
    assert value_guard < value_read, "the guard must precede the value read"
    assert '& reportRole &' in script


def test_secure_field_role_parses_without_exposing_its_value() -> None:
    """The secure role must survive parsing (so the step is recorded) with an empty value."""
    import subprocess
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.computer_use.dref.types import is_secure_role
    from myrm_agent_harness.toolkits.computer_use.perception import macos_ax

    stdout = "\n".join(
        [
            "Finder|||META|||Docs|||com.apple.finder|||123",
            "1|||AXTextField|||Search|||quarterly|||10|||20|||100|||20",
            "2|||AXSecureTextField|||Password||||||10|||60|||100|||20",
        ]
    )
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
    with patch.object(macos_ax, "_run_ax_snapshot", return_value=completed):
        snapshot = macos_ax.capture_ax_snapshot("foreground")

    by_role = {ref.role: ref for ref in snapshot.refs.values()}
    assert "AXSecureTextField" in by_role, "the secure field must not be dropped from the tree"
    secure = by_role["AXSecureTextField"]
    assert secure.value == ""
    assert is_secure_role(secure.role) is True
    # ``ElementRef.name`` falls back to ``value`` when the element has no AXName, which would leak
    # the password through the name that the renderer sends to the model.
    assert "s3cr3t" not in f"{secure.name}{secure.value}"
    # A normal field keeps its value: redaction must stay scoped to secure roles.
    assert by_role["AXTextField"].value == "quarterly"
