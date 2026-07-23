"""Tests for HitlToolPolicy SSOT."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.hitl_tool_policy import (
    HITL_TOOL_POLICY,
    HitlToolPolicy,
)
from myrm_agent_harness.agent.sub_agents.types import DelegationCapabilityManifest


def test_default_policy_registers_ask_question_tool() -> None:
    policy = HitlToolPolicy.default()
    assert policy.registered_tools == frozenset({"ask_question_tool"})
    assert policy.subagent_blocked == policy.registered_tools


def test_module_policy_matches_default_factory() -> None:
    assert HITL_TOOL_POLICY == HitlToolPolicy.default()


def test_delegation_manifest_blocks_hitl_policy_tools() -> None:
    manifest = DelegationCapabilityManifest.default()
    assert HITL_TOOL_POLICY.subagent_blocked <= manifest.leaf_blocked_tools
