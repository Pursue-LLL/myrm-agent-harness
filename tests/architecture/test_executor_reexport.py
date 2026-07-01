"""Architecture gate: sub_agents.executor aggregate re-export integrity."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.architecture
def test_subagent_executor_all_exports_are_importable() -> None:
    """Every name in executor.__all__ must resolve on the public aggregate module."""
    executor_mod = importlib.import_module("myrm_agent_harness.agent.sub_agents.executor")
    for name in executor_mod.__all__:
        assert hasattr(executor_mod, name), f"Missing subagent executor export: {name}"


@pytest.mark.architecture
def test_subagent_executor_all_matches_public_surface() -> None:
    """__all__ must list exactly the supported public subagent executor symbols."""
    executor_mod = importlib.import_module("myrm_agent_harness.agent.sub_agents.executor")
    expected = {
        "SubagentExecutor",
        "_auto_vault_or_truncate",
        "_cascade_cancel_descendants",
        "_compact_error_message",
        "_estimate_msg_tokens",
        "_filter_fork_messages",
        "_parse_handover_state",
    }
    assert set(executor_mod.__all__) == expected
