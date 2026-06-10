"""Terminate headless browser child processes owned by a pytest process tree."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from collections.abc import Sequence

logger = logging.getLogger(__name__)

_BROWSER_CMD_MARKERS: tuple[str, ...] = (
    "chrome-headless-shell",
    "Google Chrome for Testing",
    "puppeteer/chrome",
)


def _list_process_rows() -> list[tuple[int, int, str]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="],
        capture_output=True,
        text=True,
        check=True,
    )
    rows: list[tuple[int, int, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        command = parts[2] if len(parts) > 2 else ""
        rows.append((pid, ppid, command))
    return rows


def _descendant_pids(root_pid: int, rows: Sequence[tuple[int, int, str]]) -> set[int]:
    children: dict[int, list[int]] = {}
    for pid, ppid, _command in rows:
        children.setdefault(ppid, []).append(pid)

    descendants: set[int] = set()
    stack = list(children.get(root_pid, []))
    while stack:
        current = stack.pop()
        if current in descendants:
            continue
        descendants.add(current)
        stack.extend(children.get(current, []))
    return descendants


def _is_browser_command(command: str) -> bool:
    return any(marker in command for marker in _BROWSER_CMD_MARKERS)


def terminate_browser_processes_in_tree(root_pid: int | None = None) -> int:
    """Send SIGTERM to browser processes in the tree rooted at ``root_pid``.

    Returns the number of processes signaled.
    """
    root = os.getpid() if root_pid is None else root_pid
    rows = _list_process_rows()
    targets = _descendant_pids(root, rows)
    targets.add(root)

    signaled = 0
    for pid, _ppid, command in rows:
        if pid not in targets or not _is_browser_command(command):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            signaled += 1
        except ProcessLookupError:
            continue
        except PermissionError:
            logger.warning("Permission denied terminating browser pid=%s", pid)
    return signaled
