"""Unit tests for scripts.tool_registry_config."""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.tool_registry_config import (
    PTC_RUNTIME_TOOL_NAMES,
    is_test_path,
)


def test_ptc_runtime_tool_names_contains_dw_bridge_tools() -> None:
    assert PTC_RUNTIME_TOOL_NAMES == frozenset({"spawn_subagent", "notify"})


def test_is_test_path_detects_tests_directory() -> None:
    assert is_test_path(Path("/repo/myrm-agent-harness/tests/foo/test_bar.py")) is True


def test_is_test_path_rejects_production_source() -> None:
    assert is_test_path(Path("/repo/myrm-agent-harness/src/myrm_agent_harness/agent/foo.py")) is False
