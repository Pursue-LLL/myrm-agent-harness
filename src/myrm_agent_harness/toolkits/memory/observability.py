"""Memory observability DTOs.

[INPUT]
pydantic::BaseModel (POS: structured data model foundation)

[OUTPUT]
MemoryOperationKind, MemoryOperationStatus, MemorySpaceKind, MemoryInfluenceRef,
MemoryOperationEvent, MemorySpaceBinding, MemoryOperationSink: business-neutral memory observability contracts.

[POS]
Memory observability contract layer. Defines framework-level DTOs that applications
can project into dashboards or logs without coupling the harness to product concepts.

Framework-owned, business-neutral contracts for memory operation visibility.
Applications may project these models into dashboards, logs, or API responses
without coupling the harness to product concepts.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, Field

ScalarValue = str | int | float | bool | None


class MemoryOperationKind(StrEnum):
    """Generic memory operation categories."""

    OBSERVE = "observe"
    EXTRACT = "extract"
    PROPOSE = "propose"
    APPROVE = "approve"
    REJECT = "reject"
    WRITE = "write"
    INDEX = "index"
    RECALL = "recall"
    INJECT = "inject"
    CITE = "cite"
    FORGET = "forget"
    CORRECT = "correct"
    MAINTENANCE = "maintenance"
    IMPORT_MEMORY = "import_memory"
    EXPORT_MEMORY = "export_memory"
    HEALTH_CHECK = "health_check"


class MemoryOperationStatus(StrEnum):
    """Execution state for an observed memory operation."""

    PENDING = "pending"
    SUCCESS = "success"
    SKIPPED = "skipped"
    WARNING = "warning"
    ERROR = "error"


class MemorySpaceKind(StrEnum):
    """Business-neutral namespace categories understood by the harness."""

    GLOBAL = "global"
    AGENT = "agent"
    CHANNEL = "channel"
    CONVERSATION = "conversation"
    TASK = "task"
    SHARED = "shared"
    UNKNOWN = "unknown"


class MemoryInfluenceRef(BaseModel):
    """Reference to a memory that influenced recall, prompt context, or a reply."""

    memory_id: str
    memory_type: str
    score: float | None = None
    content_preview: str = ""
    primary_namespace: str | None = None
    namespaces: list[str] = Field(default_factory=list)
    source_chat_id: str | None = None
    source_message_id: str | None = None
    reason: str | None = None


class MemoryOperationEvent(BaseModel):
    """Framework-level memory operation event payload."""

    id: str
    kind: MemoryOperationKind
    status: MemoryOperationStatus
    occurred_at: datetime
    memory_id: str | None = None
    memory_type: str | None = None
    namespace: str | None = None
    source: str | None = None
    summary: str = ""
    target_kind: str | None = None
    target_id: str | None = None
    correlation_id: str | None = None
    influence_refs: list[MemoryInfluenceRef] = Field(default_factory=list)
    metadata: dict[str, ScalarValue] = Field(default_factory=dict)


class MemoryTraceStep(BaseModel):
    """One business-neutral step in a memory retrieval trace."""

    phase: Literal["sanitize", "route", "embed", "collect", "rank", "graph", "budget", "cite"]
    status: Literal["success", "skipped", "warning", "error"] = "success"
    title: str
    summary: str = ""
    duration_ms: float | None = None
    input_count: int = 0
    output_count: int = 0
    metadata: dict[str, ScalarValue] = Field(default_factory=dict)


class MemoryRetrievalTrace(BaseModel):
    """Business-neutral trace for one memory retrieval call."""

    id: str
    query_preview: str
    occurred_at: datetime
    result_count: int = 0
    correlation_id: str | None = None
    steps: list[MemoryTraceStep] = Field(default_factory=list)


class MemorySpaceBinding(BaseModel):
    """A memory namespace exposed as an observable memory space."""

    namespace: str
    kind: MemorySpaceKind = MemorySpaceKind.UNKNOWN
    label: str = ""
    target_id: str | None = None
    context_id: str | None = None
    active: bool = True


class MemoryOperationSink(Protocol):
    """Application-provided sink for durable memory operation visibility."""

    async def record_memory_operation(self, event: MemoryOperationEvent) -> None:
        """Persist or forward one memory operation event."""


__all__ = [
    "MemoryInfluenceRef",
    "MemoryOperationEvent",
    "MemoryOperationKind",
    "MemoryOperationSink",
    "MemoryOperationStatus",
    "MemoryRetrievalTrace",
    "MemorySpaceBinding",
    "MemorySpaceKind",
    "MemoryTraceStep",
    "ScalarValue",
]
