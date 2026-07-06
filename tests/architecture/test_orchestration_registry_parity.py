"""Tests that tool_registry_config stays aligned with orchestration SSOT."""

from __future__ import annotations

from scripts.tool_registry_config import INTERNAL_TOOL_NAMES, SCHEMA_ONLY_TOOL_NAMES
from myrm_agent_harness.agent.orchestration.hooks import RUNTIME_HOOK_NAMES
from myrm_agent_harness.agent.orchestration.signals.catalog import (
    DEEP_RESEARCH_SIGNAL_NAMES,
    VERIFIER_SIGNAL_NAMES,
)


def test_internal_tool_names_match_session_scoped_tools() -> None:
    expected = VERIFIER_SIGNAL_NAMES | RUNTIME_HOOK_NAMES
    assert INTERNAL_TOOL_NAMES == expected


def test_schema_only_names_match_dr_signals() -> None:
    assert SCHEMA_ONLY_TOOL_NAMES == DEEP_RESEARCH_SIGNAL_NAMES
