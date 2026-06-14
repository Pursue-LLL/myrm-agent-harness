"""Tests for workspace coordination policy (Layer 3 supplement).

Verifies: parallel write isolation, readonly bypass, writer counting.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy
from myrm_agent_harness.agent.workspace_coordination.policy import (
    apply_parallel_write_isolation,
    count_parallel_writers,
)


class TestCountParallelWriters:
    def test_counts_non_readonly(self) -> None:
        tasks = [
            {"readonly": False},
            {"readonly": True},
            {"readonly": False},
        ]
        assert count_parallel_writers(tasks) == 2

    def test_all_readonly_returns_zero(self) -> None:
        tasks = [{"readonly": True}, {"readonly": True}]
        assert count_parallel_writers(tasks) == 0

    def test_non_list_returns_zero(self) -> None:
        assert count_parallel_writers("not a list") == 0

    def test_empty_list(self) -> None:
        assert count_parallel_writers([]) == 0


class TestApplyParallelWriteIsolation:
    def test_upgrades_inherit_to_isolated(self) -> None:
        config = SubagentConfig(system_prompt="test")
        ctx: dict[str, object] = {"workspace_path": "/tmp/ws"}
        new_config, new_ctx = apply_parallel_write_isolation(
            config=config,
            child_context=ctx,
            readonly=False,
            parallel_write_batch=True,
        )
        assert new_config.workspace_policy == WorkspacePolicy.ISOLATED_COPY
        assert new_ctx["_defer_workspace_merge"] is True
        assert new_ctx["_parallel_write_batch"] is True

    def test_skips_readonly_tasks(self) -> None:
        config = SubagentConfig(system_prompt="test")
        ctx: dict[str, object] = {}
        new_config, new_ctx = apply_parallel_write_isolation(
            config=config,
            child_context=ctx,
            readonly=True,
            parallel_write_batch=True,
        )
        assert new_config.workspace_policy == WorkspacePolicy.INHERIT

    def test_skips_non_parallel_batch(self) -> None:
        config = SubagentConfig(system_prompt="test")
        ctx: dict[str, object] = {}
        new_config, _ = apply_parallel_write_isolation(
            config=config,
            child_context=ctx,
            readonly=False,
            parallel_write_batch=False,
        )
        assert new_config.workspace_policy == WorkspacePolicy.INHERIT

    def test_preserves_existing_isolated_policy(self) -> None:
        config = SubagentConfig(
            system_prompt="test",
            workspace_policy=WorkspacePolicy.ISOLATED_COPY,
        )
        ctx: dict[str, object] = {}
        new_config, _ = apply_parallel_write_isolation(
            config=config,
            child_context=ctx,
            readonly=False,
            parallel_write_batch=True,
        )
        assert new_config.workspace_policy == WorkspacePolicy.ISOLATED_COPY
