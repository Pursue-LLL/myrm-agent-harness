"""Architecture guard for MemoryManager shared import barrel."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SHARED_PATH = (
    _REPO_ROOT
    / "src"
    / "myrm_agent_harness"
    / "toolkits"
    / "memory"
    / "_manager"
    / "shared.py"
)

_REQUIRED_SYMBOLS = (
    "RuleSource",
    "MemoryConfig",
    "MemoryWriter",
    "GovernanceService",
    "MemoryError",
    "logger",
    "_log_background_task_failure",
)


@pytest.mark.architecture
def test_shared_barrel_retains_required_imports() -> None:
    """shared.py must keep symbols mixin modules depend on (guard against ruff --fix accidents)."""
    source = _SHARED_PATH.read_text(encoding="utf-8")
    for symbol in _REQUIRED_SYMBOLS:
        assert symbol in source, f"Missing required shared barrel symbol: {symbol}"

    assert "from myrm_agent_harness.toolkits.memory.types import" in source
    assert "RuleSource" in source
    assert len(source.splitlines()) >= 100
