"""
[POS] src/myrm_agent_harness/core/security/hardened_sandbox_perimeter/resource_process_guard.py
[INPUT] threading, typing, .types (ProcessUsageSnapshot)
[OUTPUT] ResourceProcessGuard

Enforces cgroups v2 resource ceilings and detects anomalous process tree escalation (Fork-Bombs).
Trips safety circuit-breaker when active process counts or memory usage exceed strict sandbox boundaries.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .types import ProcessUsageSnapshot


class ResourceProcessGuard:
    """Monitors sandbox process hierarchy and memory allocation to mitigate resource exhaustion."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tripped_agents: set[str] = set()
        self._previous_snapshots: dict[str, ProcessUsageSnapshot] = {}

    def evaluate_snapshot(
        self,
        agent_id: str,
        snapshot: ProcessUsageSnapshot,
        pids_max: int = 128,
        memory_limit_mb: float = 512.0,
    ) -> tuple[bool, str]:
        """Assess process tree and resource metrics for fork bombs or memory overflows."""
        with self._lock:
            # 1. Check if already tripped
            if agent_id in self._tripped_agents:
                return (
                    False,
                    f"Agent '{agent_id}' sandbox is currently circuit-broken due to a prior resource violation.",
                )

            # 2. Check hard PID ceiling
            if snapshot.active_pids_count > pids_max:
                self._tripped_agents.add(agent_id)
                self._previous_snapshots[agent_id] = snapshot
                return (
                    False,
                    f"Fork bomb detected! Active processes ({snapshot.active_pids_count}) exceeded ceiling ({pids_max}).",
                )

            # 3. Check rapid exponential PID expansion (Fork-bomb surge)
            prev = self._previous_snapshots.get(agent_id)
            if prev is not None and prev.active_pids_count >= 5:
                growth_factor = snapshot.active_pids_count / float(prev.active_pids_count)
                if growth_factor >= 5.0 and snapshot.active_pids_count >= (pids_max // 2):
                    self._tripped_agents.add(agent_id)
                    self._previous_snapshots[agent_id] = snapshot
                    return (
                        False,
                        f"Anomalous process surge detected: PIDs expanded {growth_factor:.1f}x ({prev.active_pids_count} -> {snapshot.active_pids_count}).",
                    )

            # 4. Check memory ceiling
            if snapshot.memory_used_mb > memory_limit_mb:
                self._tripped_agents.add(agent_id)
                self._previous_snapshots[agent_id] = snapshot
                return (
                    False,
                    f"Memory ceiling breached: {snapshot.memory_used_mb:.1f}MB used vs limit of {memory_limit_mb:.1f}MB.",
                )

            self._previous_snapshots[agent_id] = snapshot
            return True, "Process tree and memory consumption are within safe cgroups v2 limits."

    def is_agent_tripped(self, agent_id: str) -> bool:
        """Query whether agent sandbox has tripped the resource circuit-breaker."""
        with self._lock:
            return agent_id in self._tripped_agents

    def reset_agent(self, agent_id: str) -> bool:
        """Reset circuit-breaker state for an agent following remediation."""
        with self._lock:
            if agent_id in self._tripped_agents:
                self._tripped_agents.remove(agent_id)
                self._previous_snapshots.pop(agent_id, None)
                return True
            self._previous_snapshots.pop(agent_id, None)
            return False
