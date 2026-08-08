"""Trailing ``&`` orphan-guard tests for background spawn.

`spawn_background` runs ``sh -c <command>``. A bare trailing ``&`` makes ``sh``
return immediately while the real process keeps running detached, so the
registered PID points at an exited shell and bash_process_tool cannot manage it.
These tests lock the normalization and the prompt contract.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION
from myrm_agent_harness.agent.meta_tools.bash.bash_executor_background_mixin import (
    strip_trailing_background_ampersand,
)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python server.py &", "python server.py"),
        ("python server.py&", "python server.py"),
        ("  python server.py &  ", "  python server.py"),
        ("uvicorn app:app --port 8000 &", "uvicorn app:app --port 8000"),
        ("python server.py 2>&1 &", "python server.py 2>&1"),
        ("cmd1 && cmd2 &", "cmd1 && cmd2"),
    ],
)
def test_strip_bare_trailing_ampersand(command: str, expected: str) -> None:
    assert strip_trailing_background_ampersand(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "echo hi",
        "make build && pytest",
        "python server.py 2>&1",
        "",
        "cmd & # keep this comment",
        "cmd1 && cmd2 &&",
    ],
)
def test_preserve_non_orphaning_commands(command: str) -> None:
    """``&&`` chains, redirects without ``&``, and plain commands are untouched."""
    assert strip_trailing_background_ampersand(command) == command


def test_background_section_warns_against_trailing_ampersand() -> None:
    """Prompt must tell the model not to append ``&`` when backgrounding."""
    assert "run_in_background=true" in TOOL_DESCRIPTION
    assert "不要" in TOOL_DESCRIPTION
    assert "`&`" in TOOL_DESCRIPTION
    assert "自动后台化" in TOOL_DESCRIPTION
    assert "pid 失效" in TOOL_DESCRIPTION
