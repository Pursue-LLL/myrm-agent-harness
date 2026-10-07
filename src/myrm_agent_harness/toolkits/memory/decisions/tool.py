"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/tool.py
[INPUT]: Invocation arguments from LLM tool calling schema.
[OUTPUT]: Execution of record_architecture_decision staging or direct commit.
"""

from typing import Any

from pydantic import BaseModel, Field

from .models import DecisionRecord, PendingDecisionCandidate
from .store import EngineeringDecisionStore


class RecordArchitectureDecisionInput(BaseModel):
    """Input payload for record_architecture_decision tool."""

    title: str = Field(description="Succinct technical topic or decision headline (e.g. 'Authentication Strategy')")
    text: str = Field(description="Concrete decision statement chosen (e.g. 'Adopt server-side Session instead of JWT')")
    rationale: str = Field(default="", description="Key tradeoff reason and constraints justifying this choice")
    supersedes_id: str | None = Field(default=None, description="Optional ID of prior decision superseded by this one")
    session_id: str = Field(default="default_session", description="Current conversation session ID")
    project_key: str = Field(default="default", description="Project or workspace scope identifier")


class RecordArchitectureDecisionTool:
    """Agent meta-tool exposing architecture decision recording with HITL gate support."""

    name: str = "record_architecture_decision"
    description: str = (
        "Record an immutable architecture or technical specification decision into engineering memory. "
        "Supports explicit lifecycle state machine and lineage (active-to-superseded evolution). "
        "Will trigger human confirmation gate if enabled."
    )

    def __init__(self, store: EngineeringDecisionStore) -> None:
        self.store = store

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute decision staging via EngineeringDecisionStore."""
        payload = RecordArchitectureDecisionInput.model_validate(kwargs)
        res = await self.store.stage_candidate(
            session_id=payload.session_id,
            title=payload.title,
            text=payload.text,
            rationale=payload.rationale,
            supersedes_id=payload.supersedes_id,
            project_key=payload.project_key,
        )

        if isinstance(res, DecisionRecord):
            return {
                "status": "active",
                "decision_id": res.id,
                "title": res.title,
                "text": res.text,
                "supersedes_id": res.supersedes_id,
                "message": f"Architecture decision #{res.id} recorded and currently active.",
            }

        candidate: PendingDecisionCandidate = res
        return {
            "status": "pending_confirmation",
            "candidate_id": candidate.id,
            "title": candidate.title,
            "text": candidate.text,
            "rationale": candidate.rationale,
            "supersedes_id": candidate.supersedes_id,
            "message": (
                f"Architecture decision candidate #{candidate.id} staged in pending buffer. "
                "Awaiting human approval before committing to active lineage."
            ),
        }
