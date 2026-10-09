# [INPUT]: None (Pure domain types and contracts)
# [OUTPUT]: RollForwardStrategy, CacheBreakpointInfo, DynamicRollForwardResult, AnomalyGuardStatus, CacheMissAnomalyReport, Headless3DEngineType, Headless3DScriptRequest, Headless3DExecutionResult, LongTaskIterationSnapshot
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types
"""Strongly-typed contracts for Prompt Cache Dynamic Roll-Forward and Headless 3D Sandbox Suite (Item 330).

Defines structures for cross-tool-round cache roll-forward, cache miss anomaly fuses,
headless 3D/CAD script executions, and long-horizon task telemetry.
"""

from __future__ import annotations

from enum import Enum
from typing import Final
from pydantic import BaseModel, Field


class RollForwardStrategy(str, Enum):
    """Strategy for advancing prompt cache breakpoints across tool rounds."""

    MOVE_LAST_EPHEMERAL = "move_last_ephemeral"
    STRIP_INTERMEDIATE = "strip_intermediate"
    PRESERVE_SYSTEM_ONLY = "preserve_system_only"


class CacheBreakpointInfo(BaseModel):
    """Information regarding a single prompt cache control breakpoint."""

    message_index: int = Field(..., description="Index of the message in the conversation sequence")
    message_type: str = Field(..., description="Role or type of the message (e.g. system, human, ai, tool)")
    is_permanent: bool = Field(False, description="True if this breakpoint is persistent (e.g. system prompt)")
    ttl_type: str = Field("ephemeral", description="Type of cache control (e.g. ephemeral)")
    has_1h_ttl: bool = Field(False, description="Whether the breakpoint carries explicit 1h TTL")


class DynamicRollForwardResult(BaseModel):
    """Result of performing a dynamic cache roll-forward operation on message sequence."""

    total_messages: int = Field(..., description="Total messages evaluated in sequence")
    stripped_breakpoints_count: int = Field(0, description="Number of obsolete intermediate breakpoints stripped")
    preserved_permanent_indices: list[int] = Field(default_factory=list, description="Indices of preserved permanent breakpoints")
    new_active_breakpoint_indices: list[int] = Field(default_factory=list, description="All active breakpoint indices after roll-forward")
    rolled_forward_index: int = Field(..., description="Index of the newest message where cache_control was rolled forward")
    max_allowed_breakpoints: int = Field(4, description="Maximum permitted breakpoints (Anthropic ceiling is 4)")


class AnomalyGuardStatus(str, Enum):
    """Health status of the prompt cache hit telemetry."""

    NORMAL = "normal"
    WARNING = "warning"
    FUSED_CIRCUIT_BROKEN = "fused_circuit_broken"


class CacheMissAnomalyReport(BaseModel):
    """Diagnostic report from the cache miss anomaly fuse."""

    status: AnomalyGuardStatus = Field(..., description="Current anomaly guard health status")
    consecutive_cold_misses: int = Field(0, description="Current tally of consecutive cold cache misses")
    last_input_tokens: int = Field(0, description="Input tokens observed on the most recent round")
    last_cache_read_tokens: int = Field(0, description="Cache read tokens observed on the most recent round")
    is_circuit_broken: bool = Field(False, description="True if automatic execution loop must be halted immediately")
    reason: str = Field(..., description="Human-readable assessment explanation")
    suggested_action: str = Field("continue", description="Recommended mitigation action")


class Headless3DEngineType(str, Enum):
    """Supported headless 3D and CAD script execution engines in sandbox."""

    BLENDER = "blender"
    OPENSCAD = "openscad"
    FREECAD = "freecad"


class Headless3DScriptRequest(BaseModel):
    """Parameters for running a headless 3D modeling script in pure CPU sandbox."""

    engine: Headless3DEngineType = Field(Headless3DEngineType.BLENDER, description="Headless 3D execution engine")
    script_content: str = Field(..., description="Python or geometry modeling script content")
    output_format: str = Field("gltf", description="Target 3D output format ('gltf', 'obj', 'stl', 'png')")
    target_artifact_name: str = Field("model_v1", description="Base filename for generated 3D artifact")
    timeout_seconds: int = Field(120, description="Hard timeout ceiling for CPU rendering/meshing")
    render_preview: bool = Field(True, description="Whether to capture a viewport thumbnail PNG preview")


class Headless3DExecutionResult(BaseModel):
    """Outcome of headless 3D script execution and geometry compilation."""

    success: bool = Field(..., description="True if geometry was successfully compiled and rendered")
    return_code: int = Field(0, description="Subprocess return code")
    generated_3d_file: str = Field("", description="Path or identifier to generated 3D model asset")
    rendered_preview_png: str = Field("", description="Path or identifier to rendered viewport preview PNG")
    stdout_summary: str = Field("", description="Sanitized stdout summary from engine")
    stderr_summary: str = Field("", description="Sanitized stderr summary if warnings/errors occurred")
    execution_time_seconds: float = Field(0.0, description="Wall clock execution time in seconds")


class LongTaskIterationSnapshot(BaseModel):
    """Telemetry snapshot of long-horizon task evolution (e.g. V1 -> V10 -> V13)."""

    iteration_label: str = Field(..., description="Version label for this iteration (e.g. 'V13')")
    tool_round_index: int = Field(..., description="Cumulative tool round sequence index")
    cache_hit_rate: float = Field(..., description="Observed prompt cache hit rate for this round (0.0 to 1.0)")
    input_tokens: int = Field(..., description="Total input tokens on this round")
    cache_read_tokens: int = Field(..., description="Cache read input tokens on this round")
    cost_saved_usd: float = Field(..., description="Estimated USD saved on this round via prompt caching")
    preview_artifact_path: str = Field("", description="Path to latest rendered thumbnail or deliverable")
    timestamp_iso: str = Field(..., description="ISO 8601 UTC timestamp of iteration completion")


MAX_CACHE_BREAKPOINTS: Final[int] = 4
COLD_MISS_TOKEN_THRESHOLD: Final[int] = 20_000
MAX_CONSECUTIVE_COLD_MISSES: Final[int] = 2
