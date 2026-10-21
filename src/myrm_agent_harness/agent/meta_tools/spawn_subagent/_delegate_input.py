"""LLM-facing argument schema of delegate_task.

[INPUT]
- _delegate_batch::TaskRequest (POS: Batch/parallel task item schema)
- agent.sub_agents.types::DelegateRole (POS: Delegation hierarchy role)
- pydantic::BaseModel, Field

[OUTPUT]
- DelegateTaskInput: Args schema for mode=single|batch|parallel|council|alternatives

[POS]
The field set and wording the model sees for delegate_task, kept apart from the execution paths so a
schema change is reviewed on its own.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import TaskRequest
from myrm_agent_harness.agent.sub_agents.types import DelegateRole


class DelegateTaskInput(BaseModel):
    mode: Literal["single", "batch", "parallel", "council", "alternatives"] = Field(
        default="single",
        description=(
            "Delegation mode: "
            "'single' (one specialized subagent; requires agent_type + objective), "
            "'batch' (concurrent tasks via tasks[]; supports optional race/tournament), "
            "'parallel' (Swarm Fission map-reduce via tasks[]), "
            "'council' (multi-expert cross-review + chair synthesis; requires expert_agent_types >= 2 + objective), "
            "'alternatives' (N independent candidate solutions; requires expert_agent_types + objective)."
        ),
    )
    agent_type: str | None = Field(
        default=None,
        description="(single mode) Target subagent type identifier from the Available agent types roster",
    )
    objective: str | None = Field(
        default=None,
        description="(single/council/alternatives mode) Clear, unambiguous description of the task objective",
    )
    context_files: list[str] = Field(
        default_factory=list,
        description="(single/batch mode) Optional workspace file paths relevant to the subagent task",
    )
    context: dict[str, object] | None = Field(
        default=None,
        description="Optional structured context data passed to the subagent",
    )
    wait: bool | None = Field(
        default=None,
        description="Whether to block for results. Defaults: single=false (async background), batch/parallel/council/alternatives=true (blocking).",
    )
    readonly: bool = Field(
        default=False,
        description=(
            "If true, enforces read-only execution: no file writes, no shell commands, "
            "no MCP tools unless marked read-only"
        ),
    )
    complexity_tier: str | None = Field(
        default=None,
        description="Optional model tier hint ('simple', 'standard', 'reasoning')",
    )
    role: DelegateRole = Field(
        default=DelegateRole.LEAF,
        description="Delegation hierarchy role ('leaf' cannot spawn further children)",
    )
    verifier_prompt: str | None = Field(
        default=None,
        description="Optional adversarial verification prompt (single mode, requires wait=true)",
    )
    verifier_agent_type: str | None = Field(
        default=None,
        description="Optional verifier agent type identifier (single mode)",
    )
    max_verification_rounds: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum verification retry rounds (1-5, default: 2)",
    )
    tasks: list[TaskRequest] | None = Field(
        default=None,
        description="(batch/parallel mode) List of task definitions to run concurrently",
    )
    race: bool = Field(
        default=False,
        description="(batch mode) Speculative execution: first successful result wins and cancels remaining workers",
    )
    tournament: bool = Field(
        default=False,
        description="(batch mode) Tournament execution: LLM judge evaluates and picks the best result",
    )
    judge_criteria: str | None = Field(
        default=None,
        description="(batch mode tournament) Custom evaluation criteria for the judge agent",
    )
    max_concurrent: int | None = Field(
        default=None,
        description="(batch mode) Max parallel workers (default: 3 for race, 1 otherwise)",
    )
    expert_agent_types: list[str] | None = Field(
        default=None,
        description="(council/alternatives mode) Expert agent type identifiers from catalog (min 2 for council)",
    )
    cross_review_rounds: int = Field(
        default=1,
        description="(council mode) Number of adversarial cross-review rounds between experts (1-3)",
    )
    chair_agent_type: str | None = Field(
        default=None,
        description="(council mode) Agent type for the synthesis chair (defaults to first expert)",
    )
