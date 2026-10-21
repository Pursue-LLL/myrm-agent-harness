"""DAG Dependency Planner and Natural Language Team Spawning Engine.

[INPUT]
- collections
- hashlib
- typing

[OUTPUT]
- CyclicDependencyError
- DagDependencyPlanner

[POS]
DAG Dependency Planner and Natural Language Team Spawning Engine.

"""

from collections import deque
import hashlib
from typing import Dict, List
from myrm_agent_harness.agent.sub_agents.dag_orchestrator.types import (
    DagNode,
    DagNodeStatus,
    DagPlanResult,
    DagRole,
)


class CyclicDependencyError(ValueError):
    """Raised when an invalid cyclic dependency is detected in the DAG."""


class DagDependencyPlanner:
    """Decomposes goals into multi-role DAG nodes and validates acyclic dependency graphs."""

    def plan_team_dag(self, goal: str, dag_id: str = "") -> DagPlanResult:
        """Decompose a high-level natural language goal into a structured DAG."""
        if not dag_id:
            dag_id = f"dag-{hashlib.sha256(goal.encode('utf-8')).hexdigest()[:10]}"

        # Standard multi-agent team decomposition for software engineering & research
        nodes: Dict[str, DagNode] = {
            "node-analyst": DagNode(
                node_id="node-analyst",
                role=DagRole.ANALYST,
                title="Requirements & Scope Analysis",
                instruction=f"Extract functional requirements, constraints, and success criteria for: '{goal}'",
                depends_on=[],
                status=DagNodeStatus.PENDING,
            ),
            "node-architect": DagNode(
                node_id="node-architect",
                role=DagRole.ARCHITECT,
                title="System Architecture & Contract Design",
                instruction="Design component boundaries, interface contracts, and state schema based on analyst specs.",
                depends_on=["node-analyst"],
                status=DagNodeStatus.PENDING,
            ),
            "node-coder-core": DagNode(
                node_id="node-coder-core",
                role=DagRole.CODER,
                title="Core Kernel Implementation",
                instruction="Implement core algorithms, business logic, and database operations.",
                depends_on=["node-architect"],
                status=DagNodeStatus.PENDING,
            ),
            "node-coder-aux": DagNode(
                node_id="node-coder-aux",
                role=DagRole.CODER,
                title="Peripheral Adapters & Utilities",
                instruction="Implement API adapters, serialization helpers, and telemetry pipelines.",
                depends_on=["node-architect"],
                status=DagNodeStatus.PENDING,
            ),
            "node-tester": DagNode(
                node_id="node-tester",
                role=DagRole.TESTER,
                title="Integration & Verification Testing",
                instruction="Execute automated unit tests, concurrency verification, and boundary fuzzing.",
                depends_on=["node-coder-core", "node-coder-aux"],
                status=DagNodeStatus.PENDING,
            ),
            "node-release": DagNode(
                node_id="node-release",
                role=DagRole.RELEASE_MANAGER,
                title="Release Artifact & Deployment Prep",
                instruction="Verify CI/CD artifacts, package bundle, and generate signed deployment manifest.",
                depends_on=["node-tester"],
                status=DagNodeStatus.PENDING,
            ),
        }

        topo_order = self.validate_cycle_free(nodes)
        ready_ids = self.get_ready_nodes(nodes)

        return DagPlanResult(
            dag_id=dag_id,
            goal=goal,
            nodes=nodes,
            topological_order=topo_order,
            ready_node_ids=ready_ids,
        )

    def validate_cycle_free(self, nodes: Dict[str, DagNode]) -> List[str]:
        """Perform Kahn's topological sort to verify DAG has zero circular dependencies."""
        in_degree: Dict[str, int] = {nid: 0 for nid in nodes}
        adjacency: Dict[str, List[str]] = {nid: [] for nid in nodes}

        for nid, node in nodes.items():
            for dep in node.depends_on:
                if dep not in nodes:
                    raise KeyError(f"Node '{nid}' references nonexistent dependency '{dep}'.")
                adjacency[dep].append(nid)
                in_degree[nid] += 1

        queue: deque[str] = deque([nid for nid, deg in in_degree.items() if deg == 0])
        topo_order: List[str] = []

        while queue:
            curr = queue.popleft()
            topo_order.append(curr)

            for neighbor in adjacency[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(topo_order) != len(nodes):
            unresolved = [nid for nid, deg in in_degree.items() if deg > 0]
            raise CyclicDependencyError(
                f"Cyclic dependency detected among nodes: {unresolved}"
            )

        return topo_order

    def get_ready_nodes(self, nodes: Dict[str, DagNode]) -> List[str]:
        """Find node IDs that are ready for immediate concurrent execution."""
        ready: List[str] = []
        for nid, node in nodes.items():
            if node.status in (DagNodeStatus.PENDING, DagNodeStatus.REJECTED_LOOPBACK):
                # All dependencies must be COMPLETED
                all_deps_completed = all(
                    dep in nodes and nodes[dep].status == DagNodeStatus.COMPLETED
                    for dep in node.depends_on
                )
                if all_deps_completed:
                    ready.append(nid)
        return ready
