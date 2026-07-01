"""Architecture guard: stale EventBus imports under pubsub/broadcast paths."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_HARNESS_SRC = _REPO_ROOT / "src" / "myrm_agent_harness"
_SERVER_ROOT = _REPO_ROOT.parent / "myrm-agent" / "myrm-agent-server"

_BROADCAST_EVENT_BUS_IMPORT = re.compile(
    r"from\s+myrm_agent_harness\.agent\.streaming\.broadcast\.event_bus\s+import\s+EventBus\b"
)
_APP_EVENT_BUS_IMPORT = re.compile(
    r"from\s+app\.services\.event\.app_event_bus\s+import\s+[^#\n]*\bEventBus\b"
)


def _scan_py_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.py"))


def _read_py_lines(py_file: Path) -> list[str] | None:
    try:
        return py_file.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return None


@pytest.mark.architecture
def test_no_stale_tool_broadcast_event_bus_imports() -> None:
    """Import ToolBroadcastBus from agent.streaming.broadcast.event_bus, not EventBus."""
    violations: list[str] = []
    for py_file in _scan_py_files(_HARNESS_SRC):
        rel = py_file.relative_to(_REPO_ROOT).as_posix()
        lines = _read_py_lines(py_file)
        if lines is None:
            continue
        for line_no, line in enumerate(lines, start=1):
            if _BROADCAST_EVENT_BUS_IMPORT.search(line):
                violations.append(f"{rel}:{line_no}: {line.strip()}")
    assert not violations, "Stale EventBus import from broadcast.event_bus:\n" + "\n".join(violations)


@pytest.mark.architecture
def test_no_stale_server_app_event_bus_imports() -> None:
    """Import ServerEventBus from app.services.event.app_event_bus, not EventBus."""
    if not _SERVER_ROOT.is_dir():
        pytest.skip("myrm-agent-server not present in workspace")

    violations: list[str] = []
    for py_file in _scan_py_files(_SERVER_ROOT):
        rel = py_file.relative_to(_SERVER_ROOT).as_posix()
        lines = _read_py_lines(py_file)
        if lines is None:
            continue
        for line_no, line in enumerate(lines, start=1):
            if _APP_EVENT_BUS_IMPORT.search(line):
                violations.append(f"{rel}:{line_no}: {line.strip()}")
    assert not violations, "Stale EventBus import from app_event_bus:\n" + "\n".join(violations)
