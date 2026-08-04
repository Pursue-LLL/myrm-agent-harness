"""Tests for shared spawn preparation SSOT."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.spawn_prep import (
    apply_readonly_to_config,
    apply_spawn_workspace_isolation,
    enforce_spawn_policy_on_config,
    merge_candidate_from_spawn_dict,
)
from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    MemoryIsolationPolicy,
    SubagentConfig,
    WorkspacePolicy,
)


def test_apply_readonly_promotes_read_only_sandbox() -> None:
    config = SubagentConfig(system_prompt="base")
    updated = apply_readonly_to_config(config, True)
    assert updated.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX
    assert "write_file" in updated.disallowed_tools


def test_enforce_spawn_policy_leaf_and_memory_blocks() -> None:
    config = SubagentConfig(
        system_prompt="leaf",
        control_scope=ControlScope.LEAF,
        memory_isolation=MemoryIsolationPolicy.READ_ONLY_GLOBAL,
        max_spawn_depth=3,
    )
    updated = enforce_spawn_policy_on_config(config)
    assert updated.max_spawn_depth == 0
    assert "memory_save_tool" in updated.disallowed_tools


def test_parallel_write_isolation_via_spawn_prep() -> None:
    config = SubagentConfig(system_prompt="writer")
    prep = apply_spawn_workspace_isolation(
        config=config,
        child_context={"workspace_path": "/tmp/ws"},
        readonly=False,
        parallel_write_batch=True,
    )
    assert prep.config.workspace_policy == WorkspacePolicy.ISOLATED_COPY
    assert prep.child_context["_defer_workspace_merge"] is True


def test_merge_candidate_detects_isolated_paths() -> None:
    assert merge_candidate_from_spawn_dict(
        {
            "success": True,
            "result": {
                "_isolated_child_workspace": "/tmp/child",
                "_isolated_parent_workspace": "/tmp/parent",
            },
        }
    )
    assert not merge_candidate_from_spawn_dict({"success": True, "result": "plain text"})


def test_sanitize_spawn_result_for_store() -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import sanitize_spawn_result_for_store

    import json

    def sync_back() -> None:
        return None

    payload = sanitize_spawn_result_for_store(
        {
            "success": True,
            "result": {
                "text": "x",
                "_workspace_sync_back": sync_back,
                "_isolated_child_workspace": "/tmp/c",
                "_isolated_parent_workspace": "/tmp/p",
            },
        }
    )
    json.dumps(payload)
    assert payload.get("workspace_merge_status") == "pending"
