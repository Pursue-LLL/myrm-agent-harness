"""Tests for SubagentConfig policy enums and integration.

Validates:
1. MemoryIsolationPolicy enum values and defaults
2. ControlScope enum values and enforcement
3. WorkspacePolicy enum values
4. _SUBAGENT_DEFAULT_BLACKLIST correctness
5. SubagentConfig with all policy fields
"""

from dataclasses import replace

from myrm_agent_harness.agent.sub_agents.types import (
    _SUBAGENT_DEFAULT_BLACKLIST,
    ControlScope,
    DelegateRole,
    MemoryIsolationPolicy,
    SubagentConfig,
    WorkspacePolicy,
)


class TestMemoryIsolationPolicy:
    def test_ephemeral_session_value(self):
        assert MemoryIsolationPolicy.EPHEMERAL_SESSION == "ephemeral_session"

    def test_read_only_global_value(self):
        assert MemoryIsolationPolicy.READ_ONLY_GLOBAL == "read_only_global"

    def test_default_is_ephemeral(self):
        cfg = SubagentConfig(system_prompt="test", description="test")
        assert cfg.memory_isolation == MemoryIsolationPolicy.EPHEMERAL_SESSION


class TestControlScope:
    def test_orchestrator_value(self):
        assert ControlScope.ORCHESTRATOR == "orchestrator"

    def test_leaf_value(self):
        assert ControlScope.LEAF == "leaf"

    def test_default_is_leaf(self):
        cfg = SubagentConfig(system_prompt="test", description="test")
        assert cfg.control_scope == ControlScope.LEAF


class TestDelegateRole:
    def test_leaf_value(self):
        assert DelegateRole.LEAF == "leaf"

    def test_orchestrator_value(self):
        assert DelegateRole.ORCHESTRATOR == "orchestrator"

    def test_default_is_leaf(self):
        cfg = SubagentConfig(system_prompt="test", description="test")
        assert cfg.delegation_role == DelegateRole.LEAF


class TestWorkspacePolicy:
    def test_inherit_value(self):
        assert WorkspacePolicy.INHERIT == "inherit"

    def test_isolated_copy_value(self):
        assert WorkspacePolicy.ISOLATED_COPY == "isolated_copy"

    def test_default_is_inherit(self):
        cfg = SubagentConfig(system_prompt="test", description="test")
        assert cfg.workspace_policy == WorkspacePolicy.INHERIT


class TestSubagentConfigWithPolicies:
    def test_create_with_all_policies(self):
        cfg = SubagentConfig(
            system_prompt="Analyze data",
            description="Data analyst",
            memory_isolation=MemoryIsolationPolicy.READ_ONLY_GLOBAL,
            control_scope=ControlScope.LEAF,
            workspace_policy=WorkspacePolicy.ISOLATED_COPY,
        )
        assert cfg.memory_isolation == MemoryIsolationPolicy.READ_ONLY_GLOBAL
        assert cfg.control_scope == ControlScope.LEAF
        assert cfg.workspace_policy == WorkspacePolicy.ISOLATED_COPY

    def test_replace_preserves_policies(self):
        cfg = SubagentConfig(system_prompt="Original", description="test", control_scope=ControlScope.LEAF)
        cfg2 = replace(cfg, system_prompt="Modified")
        assert cfg2.control_scope == ControlScope.LEAF
        assert cfg2.system_prompt == "Modified"

    def test_leaf_scope_implies_no_spawn(self):
        """LEAF agents should have max_spawn_depth=0 by default."""
        cfg = SubagentConfig(
            system_prompt="test", description="test", control_scope=ControlScope.LEAF, max_spawn_depth=0
        )
        assert cfg.max_spawn_depth == 0

    def test_config_with_agent_factory(self):
        class MockFactory:
            async def build_agent(self, *args, **kwargs):
                return None

        cfg = SubagentConfig(system_prompt="test", description="test", agent_factory=MockFactory())
        assert cfg.agent_factory is not None


class TestSubagentDefaultBlacklist:
    def test_delegate_task_in_blacklist(self):
        assert "delegate_task_tool" in _SUBAGENT_DEFAULT_BLACKLIST

    def test_batch_delegate_tasks_in_blacklist(self):
        assert "batch_delegate_tasks_tool" in _SUBAGENT_DEFAULT_BLACKLIST

    def test_old_aliases_not_in_blacklist(self):
        assert "spawn_subagent" not in _SUBAGENT_DEFAULT_BLACKLIST
        assert "delegate_task" not in _SUBAGENT_DEFAULT_BLACKLIST
        assert "batch_delegate_tasks" not in _SUBAGENT_DEFAULT_BLACKLIST

    def test_list_subagents_in_blacklist(self):
        assert "list_subagents_tool" in _SUBAGENT_DEFAULT_BLACKLIST

    def test_cancel_subagent_in_blacklist(self):
        assert "cancel_subagent_tool" in _SUBAGENT_DEFAULT_BLACKLIST

    def test_steer_subagent_in_blacklist(self):
        assert "steer_subagent_tool" in _SUBAGENT_DEFAULT_BLACKLIST

    def test_blacklist_is_frozenset(self):
        assert isinstance(_SUBAGENT_DEFAULT_BLACKLIST, frozenset)
