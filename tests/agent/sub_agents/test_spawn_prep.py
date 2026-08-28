"""Tests for shared spawn preparation SSOT."""

from __future__ import annotations

from types import SimpleNamespace

from myrm_agent_harness.agent.security.types import PermissionAction, PermissionRule, SecurityConfig
from myrm_agent_harness.agent.sub_agents.spawn_prep import (
    apply_readonly_to_config,
    apply_spawn_workspace_isolation,
    coerce_spawn_readonly,
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


def test_coerce_spawn_readonly_respects_explicit_true() -> None:
    parent = SimpleNamespace(config=SimpleNamespace(security_config=SecurityConfig.readonly()))
    assert coerce_spawn_readonly(parent, True) is True


def test_coerce_spawn_readonly_floor_when_file_write_denied() -> None:
    parent = SimpleNamespace(config=SimpleNamespace(security_config=SecurityConfig.readonly()))
    assert coerce_spawn_readonly(parent, False) is True


def test_coerce_spawn_readonly_false_when_file_write_allowed() -> None:
    config = SecurityConfig(
        ruleset=(PermissionRule("file_write", "*", PermissionAction.ALLOW),),
    )
    parent = SimpleNamespace(config=SimpleNamespace(security_config=config))
    assert coerce_spawn_readonly(parent, False) is False


def test_coerce_spawn_readonly_without_security_config() -> None:
    parent = SimpleNamespace(config=None)
    assert coerce_spawn_readonly(parent, False) is False


def test_apply_readonly_false_passthrough() -> None:
    config = SubagentConfig(system_prompt="base")
    assert apply_readonly_to_config(config, False) is config


def test_build_child_context_from_parent_agent_non_dict() -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import (
        build_child_context_from_parent_agent,
    )

    assert build_child_context_from_parent_agent(object()) == {}


def test_build_spawn_child_context_merges_payload_hashes() -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import build_spawn_child_context

    child = build_spawn_child_context(
        parent_ctx={"workspace_path": "/tmp/ws"},
        base_context={"session_id": "s1"},
        payload_hashes={"h1": "abc"},
    )
    assert child["workspace_path"] == "/tmp/ws"
    assert child["session_id"] == "s1"
    assert child["subagent_payload_hashes"] == {"h1": "abc"}


def test_resolve_delegate_parallel_write_batch() -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import (
        resolve_delegate_parallel_write_batch,
    )

    assert resolve_delegate_parallel_write_batch(SimpleNamespace()) is False
    assert (
        resolve_delegate_parallel_write_batch(
            SimpleNamespace(_parallel_write_batch_active=True)
        )
        is True
    )


def test_build_child_context_from_parent_agent_copies_keys() -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import (
        build_child_context_from_parent_agent,
    )

    parent = SimpleNamespace(context={"workspace_path": "/tmp/ws", "session_id": "s1"})
    child = build_child_context_from_parent_agent(parent)
    assert child["workspace_path"] == "/tmp/ws"
    assert child["session_id"] == "s1"


def test_merge_candidate_false_on_failed_spawn() -> None:
    assert not merge_candidate_from_spawn_dict({"success": False, "result": {}})


def _fake_memory_manager() -> SimpleNamespace:
    return SimpleNamespace(
        _user_id="u1",
        _namespaces=[],
        _scope="session",
        _config=SimpleNamespace(),
        has_relational=False,
        has_vector=False,
    )


def test_memory_isolation_scope_variants(monkeypatch) -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import memory_isolation_scope

    monkeypatch.setattr(
        "myrm_agent_harness.agent.skill_agent.context.get_memory_manager",
        lambda: _fake_memory_manager(),
    )
    parent = SimpleNamespace()

    with memory_isolation_scope(
        parent_agent=parent,
        config=SubagentConfig(
            system_prompt="e",
            memory_isolation=MemoryIsolationPolicy.EPHEMERAL_SESSION,
        ),
    ):
        pass

    with memory_isolation_scope(
        parent_agent=parent,
        config=SubagentConfig(
            system_prompt="c",
            memory_isolation=MemoryIsolationPolicy.COLLABORATIVE_SESSION,
        ),
    ):
        assert hasattr(parent, "_collaborative_memory")

    with memory_isolation_scope(
        parent_agent=parent,
        config=SubagentConfig(
            system_prompt="r",
            memory_isolation=MemoryIsolationPolicy.READ_ONLY_GLOBAL,
        ),
    ):
        pass


def test_spawn_result_for_store_after_merge() -> None:
    from myrm_agent_harness.agent.sub_agents.spawn_prep import (
        spawn_result_for_store_after_merge,
    )

    payload = spawn_result_for_store_after_merge(
        {
            "success": True,
            "workspace_merge_status": "merged",
            "result": {"text": "ok", "_isolated_child_workspace": "/tmp/c"},
        }
    )
    assert payload["workspace_merge_status"] == "merged"
    assert "_isolated_child_workspace" not in payload["result"]


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
    import json

    from myrm_agent_harness.agent.sub_agents.spawn_prep import sanitize_spawn_result_for_store

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
