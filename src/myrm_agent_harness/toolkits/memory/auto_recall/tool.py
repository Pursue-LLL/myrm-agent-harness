"""Agent-facing LangChain tool for targeted experience auto-recall evaluation.

[INPUT]
- toolkits.memory.auto_recall.recall_gate::ExperienceRecallGate (POS: auto-recall gate orchestrator)
- toolkits.memory.auto_recall.types::AutoRecallDecision, RecallCandidate, RecallGateConfig, RecallTriggerType, RerankerStatus (POS: auto-recall contracts)

[OUTPUT]
- AutoRecallCandidateInput: Pydantic input schema for memory candidate item
- AutoRecallTriggerInput: Pydantic input schema for auto-recall evaluator tool
- create_auto_recall_evaluator_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing agents and workflow triggers to evaluate memory auto-recall gates.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.auto_recall.recall_gate import (
    ExperienceRecallGate,
)
from myrm_agent_harness.toolkits.memory.auto_recall.types import (
    RecallCandidate,
)


class AutoRecallCandidateInput(BaseModel):
    """Input representation of a candidate memory item."""

    memory_id: str = Field(..., description="Unique memory record identifier")
    content: str = Field(..., description="Memory body text content")
    initial_score: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Initial rough retrieval similarity score",
    )


class AutoRecallTriggerInput(BaseModel):
    """Input schema for targeted experience auto-recall evaluation."""

    session_id: str = Field(..., description="Current conversation or task session identifier")
    current_turn: int = Field(default=1, ge=1, description="Sequential interaction turn index")
    candidates: list[AutoRecallCandidateInput] = Field(
        default_factory=list,
        description="List of candidate memories to evaluate against triggers and sliding dedup window",
    )
    event_name: str | None = Field(
        default=None,
        description="Lifecycle event name (e.g. task_start, skill_load, subagent_start, write_preflight, cron_start)",
    )
    tool_name: str | None = Field(
        default=None,
        description="Tool name about to be invoked (triggers write_preflight for destructive commands)",
    )
    query_text: str | None = Field(
        default=None,
        description="Task prompt or user query text",
    )
    force_recall: bool = Field(
        default=False,
        description="Assert forced recall bypassing trigger classification",
    )


def create_auto_recall_evaluator_tool(
    gate: ExperienceRecallGate | None = None,
) -> BaseTool:
    """Create a LangChain standard tool to evaluate 5-scenario trigger filtering, 5-turn sliding dedup, and fail-open rerank."""
    active_gate = gate or ExperienceRecallGate()

    @tool("evaluate_auto_recall_trigger", args_schema=AutoRecallTriggerInput)
    def evaluate_auto_recall_trigger(
        session_id: str,
        current_turn: int = 1,
        candidates: list[AutoRecallCandidateInput] | None = None,
        event_name: str | None = None,
        tool_name: str | None = None,
        query_text: str | None = None,
        force_recall: bool = False,
    ) -> str:
        """Evaluate whether to trigger experience memories auto_recall based on 5 high-risk scenarios and suppress duplicates within 5 turns."""
        candidate_objs = [

            RecallCandidate(
                memory_id=c.memory_id,
                content=c.content,
                initial_score=c.initial_score,
            )
            for c in (candidates or [])
        ]

        decision = active_gate.evaluate_and_recall(
            session_id=session_id,
            current_turn=current_turn,
            raw_candidates=candidate_objs,
            event_name=event_name,
            tool_name=tool_name,
            query_text=query_text,
            force_recall=force_recall,
        )

        output = {
            "session_id": session_id,
            "turn_index": current_turn,
            "triggered": decision.triggered,
            "trigger_type": decision.trigger_type.value,
            "candidates_pre_dedup": decision.candidates_pre_dedup,
            "candidates_post_dedup": decision.candidates_post_dedup,
            "reranker_status": decision.reranker_status.value,
            "audit_reason": decision.audit_reason,
            "injected_memories": [
                {
                    "memory_id": m.memory_id,
                    "content": m.content,
                    "initial_score": m.initial_score,
                }
                for m in decision.injected_candidates
            ],
        }
        return json.dumps(output, ensure_ascii=False)

    return evaluate_auto_recall_trigger
