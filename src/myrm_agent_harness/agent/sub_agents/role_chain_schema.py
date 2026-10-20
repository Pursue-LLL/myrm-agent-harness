"""Subagent Role Chain Presets and Guidance Compiler.

[INPUT]
- dataclasses::dataclass, field (POS: Standard dataclass definition)
- typing::Literal, Final (POS: Type annotations)

[OUTPUT]
- RoleChainStage: Single stage within an orchestrated subagent role chain
- RoleChainPreset: Immutable specification for a multi-agent role chain preset
- BUILTIN_ROLE_CHAIN_PRESETS: Dict of official golden role chain presets
- get_role_chain_preset: Resolver for role chain preset by ID
- compile_role_chain_guidance: Prompt compiler that injects sequential and loop delegation constraints

[POS]
Harness-level declarative schema for subagent role chains and review-loops.
Enables structured "implement -> review -> fix" and specialized watchdog/editorial
chains with hard review round limits to prevent infinite loops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class RoleChainStage:
    """A distinct stage in an orchestrated subagent role chain."""

    stage_id: str
    role_name: str
    agent_type: str
    description: str
    suggested_model: str | None = None
    is_verifier: bool = False


@dataclass(frozen=True, slots=True)
class RoleChainPreset:
    """Immutable specification for a multi-agent sequential or looping role chain."""

    preset_id: str
    name: str
    description: str
    stages: tuple[RoleChainStage, ...]
    max_review_rounds: int = 3
    is_review_loop: bool = False
    category: str = "general"

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(s.stage_id for s in self.stages)


# 1. Implement -> Review -> Fix (Golden Engineering Loop)
IMPLEMENT_REVIEW_FIX_PRESET: Final[RoleChainPreset] = RoleChainPreset(
    preset_id="implement_review_fix",
    name="Implement -> Review -> Fix Chain",
    description="Full development loop: Implementation followed by strict multi-lens review and automated fix iterations (max 3 rounds).",
    stages=(
        RoleChainStage(
            stage_id="implementer",
            role_name="Implementer",
            agent_type="coder",
            description="Executes code changes, writes implementations and satisfies business requirements.",
        ),
        RoleChainStage(
            stage_id="reviewer",
            role_name="Reviewer",
            agent_type="code-reviewer",
            description="Examines diff for security, correctness, and code quality using fast/affordable model.",
            suggested_model="deepseek-chat",
            is_verifier=True,
        ),
        RoleChainStage(
            stage_id="fixer",
            role_name="Fixer",
            agent_type="coder",
            description="Addresses feedback and issues raised by the reviewer before re-validation.",
        ),
    ),
    max_review_rounds=3,
    is_review_loop=True,
    category="engineering",
)

# 2. Clarify -> Scout -> Worker (Deep Research & Delivery Chain)
CLARIFY_SCOUT_WORKER_PRESET: Final[RoleChainPreset] = RoleChainPreset(
    preset_id="clarify_scout_worker",
    name="Clarify -> Scout -> Worker Chain",
    description="Investigation loop: Clarifies ambiguous requirements, scouts repository/external sources, and delivers synthesized output.",
    stages=(
        RoleChainStage(
            stage_id="clarifier",
            role_name="Clarifier",
            agent_type="strategic-advisor",
            description="Analyzes requirements, identifies assumptions, and ensures scope alignment.",
            suggested_model="deepseek-chat",
            is_verifier=False,
        ),
        RoleChainStage(
            stage_id="scout",
            role_name="Scout",
            agent_type="researcher",
            description="Surveys codebase, documentation, or external resources to gather facts and context.",
            suggested_model="deepseek-chat",
            is_verifier=False,
        ),
        RoleChainStage(
            stage_id="worker",
            role_name="Worker",
            agent_type="coder",
            description="Produces the final consolidated implementation or comprehensive technical report.",
        ),
    ),
    max_review_rounds=1,
    is_review_loop=False,
    category="research",
)

# 3. Watchdog Guard Chain (Article 55 DoD)
WATCHDOG_GUARD_PRESET: Final[RoleChainPreset] = RoleChainPreset(
    preset_id="watchdog_guard",
    name="Watchdog & Adversarial Audit Chain",
    description="Safety gatekeeper chain: Intercepts high-risk operations and executes adversarial audits prior to execution.",
    stages=(
        RoleChainStage(
            stage_id="watchdog",
            role_name="Watchdog Gatekeeper",
            agent_type="strategic-advisor",
            description="Performs read-only pre-execution safety review and checks tool boundaries.",
            suggested_model="deepseek-chat",
            is_verifier=True,
        ),
        RoleChainStage(
            stage_id="adversarial_reviewer",
            role_name="Adversarial Reviewer",
            agent_type="adversarial-reviewer",
            description="Strictly probes edge-cases, destructive bash commands, and unexpected side effects.",
            suggested_model="deepseek-chat",
            is_verifier=True,
        ),
    ),
    max_review_rounds=2,
    is_review_loop=False,
    category="safety",
)

# 4. Editorial Publish Chain (Article 55 DoD)
EDITORIAL_PUBLISH_PRESET: Final[RoleChainPreset] = RoleChainPreset(
    preset_id="editorial_publish",
    name="Editorial & Knowledge Publish Chain",
    description="Content craft chain: Sets workspace voice/tone, drafts in-depth content with knowledge references, and performs final fact-checking.",
    stages=(
        RoleChainStage(
            stage_id="editorial_guide",
            role_name="Editorial Guide",
            agent_type="strategic-advisor",
            description="Establishes structural outline, target audience persona, and tone guidelines.",
            suggested_model="deepseek-chat",
            is_verifier=False,
        ),
        RoleChainStage(
            stage_id="draft_writer",
            role_name="Draft Writer",
            agent_type="researcher",
            description="Composes the long-form content adhering strictly to knowledge citations.",
        ),
        RoleChainStage(
            stage_id="proofreader",
            role_name="Proofreader",
            agent_type="code-reviewer",
            description="Fact-checks references, verifies output structure, and enforces editorial standards.",
            suggested_model="deepseek-chat",
            is_verifier=True,
        ),
    ),
    max_review_rounds=2,
    is_review_loop=True,
    category="content",
)

BUILTIN_ROLE_CHAIN_PRESETS: Final[dict[str, RoleChainPreset]] = {
    IMPLEMENT_REVIEW_FIX_PRESET.preset_id: IMPLEMENT_REVIEW_FIX_PRESET,
    CLARIFY_SCOUT_WORKER_PRESET.preset_id: CLARIFY_SCOUT_WORKER_PRESET,
    WATCHDOG_GUARD_PRESET.preset_id: WATCHDOG_GUARD_PRESET,
    EDITORIAL_PUBLISH_PRESET.preset_id: EDITORIAL_PUBLISH_PRESET,
}


def get_role_chain_preset(preset_id: str) -> RoleChainPreset | None:
    """Retrieve a role chain preset by ID."""
    return BUILTIN_ROLE_CHAIN_PRESETS.get(preset_id)


def compile_role_chain_guidance(preset_id_or_chain: str | tuple[str, ...], max_review_rounds: int = 3) -> str:
    """Compile structured orchestration guidance into the parent agent's system prompt.

    Args:
        preset_id_or_chain: Either an official preset ID (e.g. 'implement_review_fix')
            or a tuple of stage role names.
        max_review_rounds: Hard cap on review iterations to prevent unbounded loops.

    Returns:
        Structured system prompt segment for role chain orchestration.
    """
    preset: RoleChainPreset | None = None
    if isinstance(preset_id_or_chain, str):
        preset = get_role_chain_preset(preset_id_or_chain)

    if preset is not None:
        stages_desc = "\n".join(
            f"  {idx + 1}. [{stage.role_name}] (Type: `{stage.agent_type}`"
            f"{f', Model override: `{stage.suggested_model}`' if stage.suggested_model else ''}): {stage.description}"
            for idx, stage in enumerate(preset.stages)
        )
        loop_clause = (
            f"\n- **Review Loop Ceiling**: If issues are found during verification, iterate between "
            f"fixer and reviewer at most **{max_review_rounds}** rounds. Once {max_review_rounds} rounds are reached, "
            f"synthesize existing progress and report remaining findings directly."
            if preset.is_review_loop
            else ""
        )
        return (
            f"### Active Subagent Role Chain Protocol: {preset.name}\n"
            f"{preset.description}\n\n"
            f"**Execution Sequence**:\n{stages_desc}\n\n"
            f"**Orchestration Rules**:\n"
            f"- Always delegate to stages in sequential order using `delegate_task_tool`.\n"
            f"- Forward relevant context and diffs between consecutive stages.{loop_clause}\n"
            f"- Do not bypass verification stages."
        )

    # Custom chain tuple fallback
    chain_tuple = (
        preset_id_or_chain if isinstance(preset_id_or_chain, tuple) else (preset_id_or_chain,)
    )
    chain_sequence = " -> ".join(chain_tuple)
    return (
        f"### Active Subagent Role Chain Protocol: Custom Chain\n"
        f"**Sequence**: {chain_sequence}\n"
        f"- Delegate sequentially through each stage.\n"
        f"- Maximum review rounds capped at {max_review_rounds}."
    )
