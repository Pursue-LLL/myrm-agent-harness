"""myrm_agent_harness/agent/sub_agents/mixed_fleet/types.py

[INPUT]
- enum
- uuid
- dataclasses
- datetime

[OUTPUT]
- FleetRoleEnum
- FleetExecutionStatusEnum
- MixedFleetError
- MixedFleetOfflineError
- MixedFleetHandoffNotFoundError
- FleetNodeSpec
- MixedFleetHandoffManifest
- DispatchHandoffRequest
- FleetStatusSnapshot

[POS]
myrm_agent_harness/agent/sub_agents/mixed_fleet/types.py
"""

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


class FleetRoleEnum(enum.StrEnum):
    LOCAL_BRAIN = "local_brain"
    REMOTE_EXECUTOR = "remote_executor"


class FleetExecutionStatusEnum(enum.StrEnum):
    IDLE = "idle"
    DISPATCHED = "dispatched"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    OFFLINE = "offline"


class MixedFleetError(Exception):
    """Base exception for mixed fleet orchestration."""


class MixedFleetOfflineError(MixedFleetError):
    """Raised when remote executor or local brain is unreachable."""


class MixedFleetHandoffNotFoundError(MixedFleetError):
    """Raised when the specified handoff manifest does not exist."""


@dataclass
class FleetNodeSpec:
    node_id: str
    role: FleetRoleEnum
    display_name: str
    is_online: bool = True
    endpoint_url: str | None = None
    last_heartbeat: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    supported_capabilities: list[str] = field(default_factory=list)


@dataclass
class MixedFleetHandoffManifest:
    manifest_id: str
    chat_id: str
    source_role: FleetRoleEnum
    target_role: FleetRoleEnum
    task_instruction: str
    handoff_markdown: str
    context_files: list[str] = field(default_factory=list)
    execution_status: FleetExecutionStatusEnum = FleetExecutionStatusEnum.DISPATCHED
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    synced_at: str | None = None
    output_summary: str | None = None
    error_detail: str | None = None


@dataclass
class DispatchHandoffRequest:
    chat_id: str
    task_instruction: str
    context_files: list[str] = field(default_factory=list)
    manifest_id: str = field(
        default_factory=lambda: f"mf-handoff-{uuid.uuid4().hex[:10]}"
    )
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass
class FleetStatusSnapshot:
    chat_id: str
    local_brain: FleetNodeSpec
    remote_executor: FleetNodeSpec
    active_manifest: MixedFleetHandoffManifest | None
    total_handoffs: int = 0
