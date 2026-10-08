# [POS]: tests.unit.toolkits.memory.test_memory_cube_scoped_isolation_and_dynamic_mounting_suite
# [INPUT]: myrm_agent_harness.toolkits.memory.mem_cube
# [OUTPUT]: TestMemoryCubeScopedIsolationAndDynamicMountingSuite

"""Unit tests for Memory Cube Scoped Isolation & Dynamic Mounting Suite (Item 124 P0).

Verifies:
1. Cube registration and scoped namespace isolation.
2. Read/write separation mounting policies.
3. Strict isolation enforcement intercepting unauthorized writes.
4. Federated multi-cube query aggregation across authorized compartments.
5. High-level orchestrator lifecycle and routing workflows.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.mem_cube.cube_store import MemoryCubeStore
from myrm_agent_harness.toolkits.memory.mem_cube.models import (
    CubeQueryRequest,
    CubeScopeType,
    CubeWriteRequest,
    MountPolicy,
)
from myrm_agent_harness.toolkits.memory.mem_cube.mount_router import DynamicMountRouter
from myrm_agent_harness.toolkits.memory.mem_cube.orchestrator import MemoryCubeOrchestrator


class TestMemoryCubeScopedIsolationAndDynamicMountingSuite:
    """Test suite for Item 124 Memory Cube isolation and dynamic mounting."""

    def test_cube_creation_and_namespace_isolation(self) -> None:
        """Verify distinct cubes keep records strictly partitioned."""
        store = MemoryCubeStore()

        proj_cube = store.create_cube(
            name="OpenPerplexity Project Knowledge",
            scope_type=CubeScopeType.PROJECT_WORKSPACE,
            owner_id="/workspace/open-perplexity",
        )
        agent_cube = store.create_cube(
            name="Architect Agent Private Journal",
            scope_type=CubeScopeType.AGENT_PRIVATE,
            owner_id="agent-architect",
        )

        # Store in project cube
        store.store_record(
            cube_id=proj_cube.cube_id,
            content="Project uses Clean Architecture and modular sub-packages.",
        )
        # Store in agent cube
        store.store_record(
            cube_id=agent_cube.cube_id,
            content="Agent prefers writing comprehensive type annotations without Any.",
        )

        assert proj_cube.item_count == 1
        assert agent_cube.item_count == 1

        # Query project cube should not leak agent private data
        proj_records = store.list_records(proj_cube.cube_id)
        assert len(proj_records) == 1
        assert "Clean Architecture" in proj_records[0].content
        assert "type annotations" not in proj_records[0].content

        agent_records = store.list_records(agent_cube.cube_id)
        assert len(agent_records) == 1
        assert "type annotations" in agent_records[0].content

    def test_mount_policy_read_write_separation(self) -> None:
        """Verify an agent can read from shared/project cubes while only writing to private cube."""
        store = MemoryCubeStore()
        router = DynamicMountRouter()

        proj_cube = store.create_cube(
            name="Project Norms (Read Only)",
            scope_type=CubeScopeType.PROJECT_WORKSPACE,
            is_read_only=True,
        )
        private_cube = store.create_cube(
            name="Coder Agent Workspace",
            scope_type=CubeScopeType.AGENT_PRIVATE,
            owner_id="agent-coder",
        )

        policy = MountPolicy(
            agent_id="agent-coder",
            readable_cube_ids=["cube-global-shared", proj_cube.cube_id, private_cube.cube_id],
            writable_cube_ids=[private_cube.cube_id],
            default_write_cube_id=private_cube.cube_id,
            strict_isolation=True,
        )
        router.register_policy(policy)

        # Attempt writing to read-only project cube -> must be rejected
        write_illegal = router.write_routed(
            store=store,
            request=CubeWriteRequest(
                agent_id="agent-coder",
                target_cube_id=proj_cube.cube_id,
                content="Attempting unauthorized modification of project norms.",
            ),
        )
        assert not write_illegal.success
        assert "not authorized" in (write_illegal.rejection_reason or "")

        # Write to authorized private cube -> succeeds
        write_legal = router.write_routed(
            store=store,
            request=CubeWriteRequest(
                agent_id="agent-coder",
                content="Implemented unit test for data models.",
            ),
        )
        assert write_legal.success
        assert write_legal.target_cube_id == private_cube.cube_id

    def test_federated_multi_cube_query(self) -> None:
        """Verify federated query combines memories from all authorized readable cubes."""
        store = MemoryCubeStore()
        router = DynamicMountRouter()

        cube_a = store.create_cube(name="Standards A", scope_type=CubeScopeType.GLOBAL_SHARED)
        cube_b = store.create_cube(name="Domain B", scope_type=CubeScopeType.PROJECT_WORKSPACE)

        store.store_record(cube_id=cube_a.cube_id, content="Global rule: maximum 400 lines per file.")
        store.store_record(cube_id=cube_b.cube_id, content="Project rule: all files must have IOP headers.")

        router.register_policy(
            MountPolicy(
                agent_id="agent-auditor",
                readable_cube_ids=[cube_a.cube_id, cube_b.cube_id],
                writable_cube_ids=[],
            )
        )

        query_res = router.read_federated(
            store=store,
            request=CubeQueryRequest(
                agent_id="agent-auditor",
                query="rule",
                limit_per_cube=5,
            ),
        )

        assert query_res.total_found == 2
        assert cube_a.cube_id in query_res.records_by_cube
        assert cube_b.cube_id in query_res.records_by_cube

    def test_orchestrator_full_workflow(self) -> None:
        """Verify high-level facade operations and agent topology binding."""
        orchestrator = MemoryCubeOrchestrator()

        task_cube = orchestrator.create_cube(
            name="Session Sandbox Task",
            scope_type=CubeScopeType.EPHEMERAL_TASK,
            owner_id="sess-temp-88",
        )

        policy = orchestrator.mount_agent_cubes(
            agent_id="agent-worker-1",
            readable_cube_ids=["cube-global-shared", task_cube.cube_id],
            writable_cube_ids=[task_cube.cube_id],
            default_write_cube_id=task_cube.cube_id,
        )
        assert policy.agent_id == "agent-worker-1"

        write_res = orchestrator.write_to_cube(
            CubeWriteRequest(
                agent_id="agent-worker-1",
                content="Finished subtask: database migration verified.",
            )
        )
        assert write_res.success
        assert write_res.target_cube_id == task_cube.cube_id

        # Query back
        query_res = orchestrator.query_cubes(
            CubeQueryRequest(
                agent_id="agent-worker-1",
                query="subtask migration",
            )
        )
        assert query_res.total_found == 1
        assert task_cube.cube_id in query_res.records_by_cube
