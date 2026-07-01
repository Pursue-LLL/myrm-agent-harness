"""Integration smoke: conftest wiring → tests.support.browser_process_cleanup."""

from __future__ import annotations

import ast
from pathlib import Path


def test_harness_and_server_cleanup_modules_share_markers() -> None:
    harness_path = Path(__file__).resolve().parent / "browser_process_cleanup.py"
    server_path = (
        Path(__file__).resolve().parents[3]
        / "myrm-agent"
        / "myrm-agent-server"
        / "tests"
        / "support"
        / "browser_process_cleanup.py"
    )
    assert server_path.is_file(), f"Missing server mirror: {server_path}"

    harness_markers = _automation_markers_from_file(harness_path)
    server_markers = _automation_markers_from_file(server_path)
    assert harness_markers == server_markers


def test_harness_conftest_cleanup_hook_runs() -> None:
    from tests.conftest import _cleanup_browser_child_processes

    _cleanup_browser_child_processes()


def _automation_markers_from_file(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_AUTOMATION_CMD_MARKERS" and node.value is not None:
                value = ast.literal_eval(node.value)
                if isinstance(value, tuple):
                    return tuple(str(item) for item in value)
    raise AssertionError(f"_AUTOMATION_CMD_MARKERS not found in {path}")
