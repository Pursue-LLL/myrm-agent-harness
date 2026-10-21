"""Types and contracts for DAG Visual Orchestrator with Cold Resume and Bidirectional Feedback.

[INPUT]
- dataclasses
- enum
- typing

[OUTPUT]
- DagNodeStatus
- DagRole
- DagNode
- DagCheckpointSnapshot
- DagPlanResult

[POS]
Types and contracts for DAG Visual Orchestrator with Cold Resume and Bidirectional Feedback.

"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class DagNodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED_LOOPBACK = "rejected_loopback"


class DagRole(str, Enum):
    ANALYST = "analyst"
    ARCHITECT = "architect"
    CODER = "coder"
    TESTER = "tester"
    RELEASE_MANAGER = "release_manager"


@dataclass
class DagNode:
    node_id: str
    role: DagRole
    title: str
    instruction: str
    depends_on: List[str] = field(default_factory=list)
    status: DagNodeStatus = DagNodeStatus.PENDING
    output_artifact: Optional[str] = None
    rejection_feedback: Optional[str] = None
    execution_time_ms: int = 0


@dataclass
class DagCheckpointSnapshot:
    snapshot_id: str
    dag_id: str
    nodes: Dict[str, DagNode] = field(default_factory=dict)
    completed_node_ids: List[str] = field(default_factory=list)
    created_at_utc: str = ""


@dataclass
class DagPlanResult:
    dag_id: str
    goal: str
    nodes: Dict[str, DagNode]
    topological_order: List[str]
    ready_node_ids: List[str]
