"""
[INPUT]: Agent session graphs, child process descriptors, and resource usage metrics.
[OUTPUT]: Pydantic schemas representing agent causality trees, orphan reaper events, deadlock polling breakers, and post-mortem failure traces.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/runtime_zombie_reaper/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ProcessLifecycleState(str, Enum):
    """Lifecycle execution state of an agent or auxiliary helper process."""

    RUNNING = "running"
    IDLE = "idle"
    WAITING = "waiting"
    TERMINATED = "terminated"
    CRASHED = "crashed"


class ProcessCausalityNode(BaseModel):
    """Single node in the process and agent causality graph."""

    node_id: str = Field(..., description="Unique node identifier (e.g. session_id or helper_id)")
    name: str = Field(..., description="Human-readable node label, e.g. 'CodingAgent' or 'PlaywrightBrowser'")
    role: str = Field(..., description="primary_agent | subagent | helper_process | sandbox_container")
    pid: int = Field(..., ge=0, description="Host or container process ID")
    pgid: int = Field(..., ge=0, description="Process group ID for group signal management")
    parent_id: Optional[str] = Field(default=None, description="Parent session or task node ID")
    profile_id: str = Field(default="default", description="Associated user or agent profile")
    state: ProcessLifecycleState = Field(default=ProcessLifecycleState.RUNNING)
    cpu_percent: float = Field(default=0.0, ge=0.0, description="Instantaneous CPU usage percentage")
    memory_rss_mb: float = Field(default=0.0, ge=0.0, description="Resident Set Size memory in MB")
    tokens_consumed: int = Field(default=0, ge=0, description="Total tokens leveraged by this node")
    last_heartbeat_ms: int = Field(..., ge=0, description="Epoch timestamp of last heartbeat")
    exit_code: Optional[int] = Field(default=None, description="Exit code if terminated or crashed")
    crash_reason: Optional[str] = Field(default=None, description="Diagnostic reason if crashed or aborted")


class ProfileResourceUsage(BaseModel):
    """Aggregated resource consumption metrics for a specific profile or install."""

    profile_id: str = Field(...)
    active_nodes_count: int = Field(default=0, ge=0)
    total_cpu_percent: float = Field(default=0.0, ge=0.0)
    total_memory_mb: float = Field(default=0.0, ge=0.0)
    total_tokens: int = Field(default=0, ge=0)


class PostMortemTaskEntry(BaseModel):
    """Historical post-mortem archive of failed or abnormally terminated runs."""

    task_id: str = Field(...)
    name: str = Field(...)
    parent_task_id: Optional[str] = Field(default=None)
    profile_id: str = Field(default="default")
    exit_code: int = Field(...)
    crash_reason: str = Field(...)
    duration_ms: int = Field(default=0, ge=0)
    terminated_at_ms: int = Field(...)


class RuntimeCausalitySnapshot(BaseModel):
    """Comprehensive snapshot of the multi-agent activity tree, resources, and failed runs."""

    nodes: List[ProcessCausalityNode] = Field(default_factory=list)
    profile_summaries: List[ProfileResourceUsage] = Field(default_factory=list)
    recent_failed_tasks: List[PostMortemTaskEntry] = Field(default_factory=list)
    total_reaped_orphans: int = Field(default=0, ge=0)
    total_deadlocks_broken: int = Field(default=0, ge=0)
    timestamp_ms: int = Field(...)
