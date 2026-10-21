"""
[INPUT]: Process causality registrations, heartbeat pings, resource metrics, and task failure events.
[OUTPUT]: High-performance tracker constructing causality process trees, executing orphan process reaping, and breaking deadlock polling.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/runtime_zombie_reaper/tracker.py
"""

import time
from typing import Dict, List, Optional, Set, Tuple
from myrm_agent_harness.observability.runtime_zombie_reaper.models import (
    PostMortemTaskEntry,
    ProcessCausalityNode,
    ProcessLifecycleState,
    ProfileResourceUsage,
    RuntimeCausalitySnapshot,
)


class AgentRuntimeCausalityTracker:
    """Manages the process hierarchy, cascades orphan process termination, and aborts polling deadlocks."""

    def __init__(self) -> None:
        self._nodes: Dict[str, ProcessCausalityNode] = {}
        self._failed_tasks: List[PostMortemTaskEntry] = []
        self._total_reaped_orphans: int = 0
        self._total_deadlocks_broken: int = 0

    def reset(self) -> None:
        """Clear all in-memory process nodes and historical telemetry."""
        self._nodes.clear()
        self._failed_tasks.clear()
        self._total_reaped_orphans = 0
        self._total_deadlocks_broken = 0

    def upsert_node(self, node: ProcessCausalityNode) -> None:
        """Register or update an agent, subagent, or auxiliary process node."""
        self._nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Optional[ProcessCausalityNode]:
        """Fetch a specific process node by ID."""
        return self._nodes.get(node_id)

    def reap_orphans(self, parent_id: str, reason: str = "Parent agent offline") -> List[str]:
        """Cascadingly reap all child/helper processes whose parent or ancestor was terminated.

        Returns:
            List[str]: List of reaped node IDs.
        """
        reaped_ids: List[str] = []
        children_ids = self._get_all_descendants(parent_id)

        for cid in children_ids:
            node = self._nodes.get(cid)
            if node and node.state in (
                ProcessLifecycleState.RUNNING,
                ProcessLifecycleState.IDLE,
                ProcessLifecycleState.WAITING,
            ):
                node.state = ProcessLifecycleState.TERMINATED
                node.exit_code = -15  # SIGTERM
                node.crash_reason = f"Reaped by orphan watchdog: {reason}"
                reaped_ids.append(cid)
                self._total_reaped_orphans += 1

        return reaped_ids

    def _get_all_descendants(self, root_id: str) -> Set[str]:
        """Recursively collect all child and helper node IDs under root_id."""
        descendants: Set[str] = set()
        stack = [root_id]
        while stack:
            curr = stack.pop()
            for nid, node in self._nodes.items():
                if node.parent_id == curr and nid not in descendants:
                    descendants.add(nid)
                    stack.append(nid)
        return descendants

    def check_deadlock_polling(self, parent_id: str, child_id: str) -> Tuple[bool, Optional[str]]:
        """Detect whether parent is blocked polling a child that has crashed or abnormally vanished.

        Returns:
            Tuple[is_deadlocked, fault_message]: Whether breaker tripped and diagnostic description.
        """
        child_node = self._nodes.get(child_id)
        if not child_node:
            self._total_deadlocks_broken += 1
            msg = f"Deadlock polling tripped: Subagent '{child_id}' disappeared completely."
            return True, msg

        if child_node.state in (ProcessLifecycleState.CRASHED, ProcessLifecycleState.TERMINATED):
            self._total_deadlocks_broken += 1
            reason = child_node.crash_reason or f"Exit code {child_node.exit_code}"
            msg = f"Deadlock polling tripped: Subagent '{child_id}' has already exited ({reason})."
            return True, msg

        return False, None

    def record_failed_task(self, entry: PostMortemTaskEntry) -> None:
        """Archive a failed run for post-mortem root cause analysis."""
        self._failed_tasks.append(entry)
        if len(self._failed_tasks) > 50:
            self._failed_tasks.pop(0)

    def get_snapshot(self) -> RuntimeCausalitySnapshot:
        """Produce full hierarchy snapshot, cross-profile summaries, and post-mortem list."""
        all_nodes = list(self._nodes.values())

        # Aggregate per profile
        profile_map: Dict[str, Dict[str, float]] = {}
        profile_nodes: Dict[str, int] = {}
        for n in all_nodes:
            prof = n.profile_id
            profile_nodes[prof] = profile_nodes.get(prof, 0) + (
                1 if n.state in (ProcessLifecycleState.RUNNING, ProcessLifecycleState.IDLE) else 0
            )
            m = profile_map.setdefault(
                prof, {"cpu": 0.0, "ram": 0.0, "tokens": 0.0}
            )
            m["cpu"] += n.cpu_percent
            m["ram"] += n.memory_rss_mb
            m["tokens"] += float(n.tokens_consumed)

        profile_summaries: List[ProfileResourceUsage] = []
        for prof, metrics in profile_map.items():
            profile_summaries.append(
                ProfileResourceUsage(
                    profile_id=prof,
                    active_nodes_count=profile_nodes.get(prof, 0),
                    total_cpu_percent=round(metrics["cpu"], 1),
                    total_memory_mb=round(metrics["ram"], 1),
                    total_tokens=int(metrics["tokens"]),
                )
            )

        return RuntimeCausalitySnapshot(
            nodes=all_nodes,
            profile_summaries=profile_summaries,
            recent_failed_tasks=list(self._failed_tasks),
            total_reaped_orphans=self._total_reaped_orphans,
            total_deadlocks_broken=self._total_deadlocks_broken,
            timestamp_ms=int(time.time() * 1000),
        )
