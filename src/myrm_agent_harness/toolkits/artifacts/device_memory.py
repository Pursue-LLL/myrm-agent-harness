"""Multi-protocol hardware device state snapshot and command sequence memory.

[INPUT]
- toolkits.artifacts.models::DeviceCommandEntry, DeviceStateSnapshot (POS: Typed CAD vector-geometry
  contracts (2D points, bounding boxes, vector primitives, LOD levels, layers, progressive render chunks)
  for the artifacts toolkit.)

[OUTPUT]
- DeviceStateCommandMemory: Multi-protocol hardware device state snapshot and command sequence memory.

[POS]
Multi-protocol hardware device state snapshot and command sequence memory.
"""

from __future__ import annotations

from typing import Final

from myrm_agent_harness.toolkits.artifacts.models import (
    DeviceCommandEntry,
    DeviceStateSnapshot,
)

MAX_COMMAND_TRACE_LIMIT: Final[int] = 1000


class DeviceStateCommandMemory:
    """Multi-protocol hardware device state snapshot and command sequence memory.

    Adapted from CadenzaOS scheduling and hardware command sequence trace replay
    architecture to provide authoritative hardware state snapshots and idempotent
    command execution verification.
    """

    def __init__(self, trace_limit: int = MAX_COMMAND_TRACE_LIMIT) -> None:
        self._trace_limit = trace_limit
        self._device_snapshots: dict[str, DeviceStateSnapshot] = {}
        self._snapshot_history: dict[str, list[DeviceStateSnapshot]] = {}
        self._command_traces: dict[str, list[DeviceCommandEntry]] = {}

    def record_snapshot(self, snapshot: DeviceStateSnapshot) -> None:
        """Record or update authoritative hardware state snapshot for a device."""
        self._device_snapshots[snapshot.device_id] = snapshot
        if snapshot.device_id not in self._snapshot_history:
            self._snapshot_history[snapshot.device_id] = []
        self._snapshot_history[snapshot.device_id].append(snapshot)
        if len(self._snapshot_history[snapshot.device_id]) > self._trace_limit:
            self._snapshot_history[snapshot.device_id].pop(0)

    def get_latest_snapshot(self, device_id: str) -> DeviceStateSnapshot | None:
        """Retrieve the latest registered state snapshot for a given device."""
        return self._device_snapshots.get(device_id)

    def get_snapshot_history(self, device_id: str) -> list[DeviceStateSnapshot]:
        """Retrieve historical state snapshots for audit and rollback."""
        return list(self._snapshot_history.get(device_id, []))

    def append_command(self, command: DeviceCommandEntry) -> bool:
        """Append a hardware command with monotonic timestamp and idempotency check.

        Returns False if the command is a duplicate committed command or out of order.
        """
        device_id = command.device_id
        if device_id not in self._command_traces:
            self._command_traces[device_id] = []

        trace = self._command_traces[device_id]

        for existing in trace:
            if existing.command_id == command.command_id and existing.is_committed:
                return False

        if trace and command.timestamp_ns < trace[-1].timestamp_ns:
            return False

        trace.append(command)
        if len(trace) > self._trace_limit:
            trace.pop(0)

        return True

    def commit_command(
        self,
        device_id: str,
        command_id: str,
        actual_response_hex: str | None = None,
    ) -> bool:
        """Mark an in-flight command as committed after physical/virtual bus acknowledgment."""
        trace = self._command_traces.get(device_id, [])
        for cmd in trace:
            if cmd.command_id == command_id:
                cmd.is_committed = True
                cmd.actual_response_hex = actual_response_hex
                return True
        return False

    def get_uncommitted_commands(self, device_id: str) -> list[DeviceCommandEntry]:
        """Retrieve pending uncommitted commands for in-flight error recovery."""
        trace = self._command_traces.get(device_id, [])
        return [cmd for cmd in trace if not cmd.is_committed]

    def rollback_to_snapshot(
        self, device_id: str, target_snapshot_id: str
    ) -> bool:
        """Rollback current device state to an earlier authoritative snapshot."""
        history = self._snapshot_history.get(device_id, [])
        for snap in history:
            if snap.snapshot_id == target_snapshot_id:
                self._device_snapshots[device_id] = snap
                return True
        return False
