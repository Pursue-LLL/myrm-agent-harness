"""Agent-facing LangChain tool for ground truth priority and code drift stale memory defense.

[INPUT]
- toolkits.memory.drift_defense.detector::GroundTruthDriftDetector (POS: ground truth drift detector)
- toolkits.memory.drift_defense.types::DriftCheckRequest, DriftCheckResult, DriftDefenseConfig, MemoryDriftFinding (POS: drift types)

[OUTPUT]
- CheckMemoryDriftInput: Pydantic input schema for individual drift check
- BatchCheckMemoryDriftInput: Pydantic input schema for batch drift verification
- create_ground_truth_drift_check_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing agents to verify candidate memories against active workspace ground truth before usage.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.drift_defense.detector import (
    GroundTruthDriftDetector,
)
from myrm_agent_harness.toolkits.memory.drift_defense.types import (
    DriftCheckRequest,
    DriftCheckResult,
    DriftDefenseConfig,
)


class CheckMemoryDriftInput(BaseModel):
    """Input representation to evaluate memory candidate against physical workspace state."""

    memory_id: str = Field(..., description="Unique memory record identifier")
    content: str = Field(..., min_length=1, description="Memory text content to inspect for file/symbol references")
    workspace_root: str = Field(..., description="Absolute path to active workspace root directory")
    recorded_path: str | None = Field(
        default=None,
        description="Explicit relative file path bound to memory if any",
    )
    recorded_symbol: str | None = Field(
        default=None,
        description="Explicit symbol name bound to memory if any",
    )


class BatchCheckMemoryDriftInput(BaseModel):
    """Input representation to batch evaluate candidate memories."""

    workspace_root: str = Field(..., description="Global workspace root directory path")
    items: list[CheckMemoryDriftInput] = Field(
        ...,
        min_length=1,
        description="List of candidate memory items to evaluate",
    )


def create_ground_truth_drift_check_tool(
    detector: GroundTruthDriftDetector | None = None,
    config: DriftDefenseConfig | None = None,
) -> BaseTool:
    """Create a LangChain standard tool to verify memory consistency against physical repository ground truth."""
    active_detector = detector or GroundTruthDriftDetector(config=config)

    @tool("check_memory_ground_truth_drift", args_schema=CheckMemoryDriftInput)
    def check_memory_ground_truth_drift(
        memory_id: str,
        content: str,
        workspace_root: str,
        recorded_path: str | None = None,
        recorded_symbol: str | None = None,
    ) -> str:
        """Inspect a memory statement against the active repository state to detect deleted files, moved symbols, and stale code patterns."""
        request = DriftCheckRequest(
            memory_id=memory_id,
            content=content,
            workspace_root=Path(workspace_root),
            recorded_path=recorded_path,
            recorded_symbol=recorded_symbol,
        )
        result: DriftCheckResult = active_detector.check(request)
        findings_payload = [
            {
                "drift_type": f.drift_type.value,
                "reference_target": f.reference_target,
                "detail": f.detail,
                "is_stale": f.is_stale,
            }
            for f in result.findings
        ]
        return json.dumps(
            {
                "memory_id": result.memory_id,
                "is_drifted": result.is_drifted,
                "confidence_penalty": result.confidence_penalty,
                "findings": findings_payload,
                "decorated_content": result.decorated_content,
            },
            ensure_ascii=False,
        )

    return check_memory_ground_truth_drift
