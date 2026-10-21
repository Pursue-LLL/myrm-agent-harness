"""Coordinator for Pi Harness v2 multi-lane parallel thread execution.

[INPUT]
- __future__
- asyncio
- time
- uuid

[OUTPUT]
- MultiLaneSessionCoordinator

[POS]
Coordinator for Pi Harness v2 multi-lane parallel thread execution.

"""

from __future__ import annotations

import asyncio
import time
import uuid

from myrm_agent_harness.agent.sub_agents.multi_lane.types import (
    LaneConcurrencyConflictError,
    LaneInfo,
    LaneNotFoundError,
    LaneOperation,
    LaneState,
    MetadataDict,
    MultiLaneSessionSnapshot,
    NodeNotFoundError,
    OperationNotFoundError,
    OpStatus,
    TreeNode,
)


class MultiLaneSessionCoordinator:
    """Session coordinator managing parallel lanes over a shared append-only tree.

    Implements Pi Harness v2 principles:
    1. Single Writer: coordinator serializes node writes and lane transitions.
    2. Parallel Lanes: multiple lanes can run concurrently in the same session.
    3. Isolated Op Log: each lane owns its operational history and current leaf.
    4. Mutual Exclusion: at most 1 open operation per lane at any moment.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id: str = session_id
        self._lock: asyncio.Lock = asyncio.Lock()
        self._nodes: dict[str, TreeNode] = {}
        self._lanes: dict[str, LaneInfo] = {}
        self._op_logs: dict[str, list[LaneOperation]] = {}

        # Initialize root node in shared append-only tree
        root_node = TreeNode(
            node_id="root",
            parent_id=None,
            lane_id="system",
            node_type="root",
            content="Session root node initialized",
            created_at=time.time(),
            metadata={"description": "Shared tree root"},
        )
        self._nodes[root_node.node_id] = root_node

        # Initialize primary main lane pointing to root
        main_lane = LaneInfo(
            lane_id="main",
            display_name="Main Channel Lane",
            state=LaneState.IDLE,
            current_leaf_id="root",
            active_op_id=None,
            total_ops=0,
            created_at=time.time(),
        )
        self._lanes[main_lane.lane_id] = main_lane
        self._op_logs[main_lane.lane_id] = []

    async def create_lane(
        self,
        lane_id: str,
        display_name: str,
        fork_from_node_id: str | None = None,
    ) -> LaneInfo:
        """Create a new lane branching from an existing node or default leaf."""
        async with self._lock:
            if lane_id in self._lanes:
                return self._lanes[lane_id]

            target_leaf = fork_from_node_id or self._lanes["main"].current_leaf_id
            if target_leaf not in self._nodes:
                raise NodeNotFoundError(
                    f"Fork node '{target_leaf}' not found in shared tree"
                )

            lane = LaneInfo(
                lane_id=lane_id,
                display_name=display_name,
                state=LaneState.IDLE,
                current_leaf_id=target_leaf,
                active_op_id=None,
                total_ops=0,
                created_at=time.time(),
            )
            self._lanes[lane_id] = lane
            self._op_logs[lane_id] = []
            return lane

    async def append_node(
        self,
        lane_id: str,
        content: str,
        node_type: str = "message",
        metadata: MetadataDict | None = None,
    ) -> TreeNode:
        """Append a node to the shared tree on behalf of a specific lane."""
        async with self._lock:
            if lane_id not in self._lanes:
                raise LaneNotFoundError(f"Lane '{lane_id}' not found")

            lane = self._lanes[lane_id]
            parent_id = lane.current_leaf_id
            node_id = f"node-{uuid.uuid4().hex[:10]}"
            node = TreeNode(
                node_id=node_id,
                parent_id=parent_id,
                lane_id=lane_id,
                node_type=node_type,
                content=content,
                created_at=time.time(),
                metadata=metadata or {},
            )
            self._nodes[node_id] = node
            lane.current_leaf_id = node_id
            return node

    async def dispatch_operation(
        self,
        lane_id: str,
        name: str,
        payload: MetadataDict | None = None,
    ) -> LaneOperation:
        """Dispatch an operation on a lane. Enforces max 1 open operation."""
        async with self._lock:
            if lane_id not in self._lanes:
                raise LaneNotFoundError(f"Lane '{lane_id}' not found")

            lane = self._lanes[lane_id]
            if lane.active_op_id is not None:
                raise LaneConcurrencyConflictError(
                    f"Lane '{lane_id}' already has active operation '{lane.active_op_id}'. "
                    "Per-lane concurrency constraint: max 1 open operation."
                )

            op_id = f"op-{uuid.uuid4().hex[:8]}"
            operation = LaneOperation(
                op_id=op_id,
                lane_id=lane_id,
                name=name,
                payload=payload or {},
                status=OpStatus.RUNNING,
                created_at=time.time(),
                started_at=time.time(),
            )
            lane.active_op_id = op_id
            lane.state = LaneState.RUNNING
            lane.total_ops += 1

            self._op_logs[lane_id].append(operation)
            return operation

    async def complete_operation(
        self,
        lane_id: str,
        op_id: str,
        result_content: str | None = None,
        error: str | None = None,
    ) -> LaneOperation:
        """Complete an operation, advancing op log and optionally appending node."""
        async with self._lock:
            if lane_id not in self._lanes:
                raise LaneNotFoundError(f"Lane '{lane_id}' not found")

            lane = self._lanes[lane_id]
            target_op: LaneOperation | None = None
            for op in reversed(self._op_logs[lane_id]):
                if op.op_id == op_id:
                    target_op = op
                    break

            if target_op is None:
                raise OperationNotFoundError(
                    f"Operation '{op_id}' not found on lane '{lane_id}'"
                )

            now = time.time()
            target_op.completed_at = now
            if error:
                target_op.status = OpStatus.FAILED
                target_op.error_message = error
            else:
                target_op.status = OpStatus.COMPLETED
                if result_content is not None:
                    # Append result to shared tree
                    node_id = f"node-{uuid.uuid4().hex[:10]}"
                    node = TreeNode(
                        node_id=node_id,
                        parent_id=lane.current_leaf_id,
                        lane_id=lane_id,
                        node_type="tool_result",
                        content=result_content,
                        created_at=now,
                        metadata={"op_id": op_id, "op_name": target_op.name},
                    )
                    self._nodes[node_id] = node
                    lane.current_leaf_id = node_id
                    target_op.result_node_id = node_id

            if lane.active_op_id == op_id:
                lane.active_op_id = None
                lane.state = LaneState.IDLE

            return target_op

    async def cancel_operation(
        self,
        lane_id: str,
        op_id: str,
        reason: str | None = None,
    ) -> LaneOperation:
        """Cancel an in-flight operation on a lane."""
        async with self._lock:
            if lane_id not in self._lanes:
                raise LaneNotFoundError(f"Lane '{lane_id}' not found")

            lane = self._lanes[lane_id]
            target_op: LaneOperation | None = None
            for op in reversed(self._op_logs[lane_id]):
                if op.op_id == op_id:
                    target_op = op
                    break

            if target_op is None:
                raise OperationNotFoundError(
                    f"Operation '{op_id}' not found on lane '{lane_id}'"
                )

            now = time.time()
            target_op.status = OpStatus.CANCELLED
            target_op.completed_at = now
            target_op.error_message = reason or "Operation cancelled by user"

            if lane.active_op_id == op_id:
                lane.active_op_id = None
                lane.state = LaneState.IDLE

            return target_op

    async def get_lane(self, lane_id: str) -> LaneInfo:
        """Retrieve metadata for a specific lane."""
        async with self._lock:
            if lane_id not in self._lanes:
                raise LaneNotFoundError(f"Lane '{lane_id}' not found")
            return self._lanes[lane_id]

    async def get_op_log(self, lane_id: str) -> list[LaneOperation]:
        """Retrieve operational log entries for a lane."""
        async with self._lock:
            if lane_id not in self._lanes:
                raise LaneNotFoundError(f"Lane '{lane_id}' not found")
            return list(self._op_logs[lane_id])

    async def get_snapshot(
        self, recent_ops_limit: int = 50
    ) -> MultiLaneSessionSnapshot:
        """Generate a global snapshot of all lanes and tree size."""
        async with self._lock:
            all_ops: list[LaneOperation] = []
            active_count = 0
            for lane_id, lane in self._lanes.items():
                if lane.state == LaneState.RUNNING:
                    active_count += 1
                all_ops.extend(self._op_logs[lane_id])

            all_ops.sort(key=lambda op: op.created_at, reverse=True)

            return MultiLaneSessionSnapshot(
                session_id=self.session_id,
                lanes={k: LaneInfo(**v.__dict__) for k, v in self._lanes.items()},
                total_nodes=len(self._nodes),
                active_lanes_count=active_count,
                recent_op_logs=all_ops[:recent_ops_limit],
            )
