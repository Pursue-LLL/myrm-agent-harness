"""Architecture gate: bash_executor aggregate re-export integrity."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.architecture
def test_bash_executor_all_exports_are_importable() -> None:
    """Every name in bash_executor.__all__ must resolve on the public aggregate module."""
    mod = importlib.import_module("myrm_agent_harness.agent.meta_tools.bash.bash_executor")
    for name in mod.__all__:
        assert hasattr(mod, name), f"Missing bash executor export: {name}"


@pytest.mark.architecture
def test_bash_executor_all_matches_public_surface() -> None:
    """__all__ must list exactly the supported public bash executor symbols."""
    mod = importlib.import_module("myrm_agent_harness.agent.meta_tools.bash.bash_executor")
    expected = {"BashExecutionError", "BashExecutor", "_MCP_MIN_TIMEOUT"}
    assert set(mod.__all__) == expected
