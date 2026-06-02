"""Consolidation judge — LLM-driven merge strategy decision.

Receives SkillCluster candidates and calls an LLM to determine optimal
consolidation actions (MERGE / CREATE_UMBRELLA / DEMOTE / KEEP).

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- .types::SkillCluster, ConsolidationAction, ConsolidationPlan (POS: consolidation types)
- backends.skills.types::SkillMetadata (POS: Skill system core data types.)

[OUTPUT]
- ConsolidationJudge: LLM-driven judge that produces a ConsolidationPlan.

[POS]
LLM judge layer for skill consolidation. Determines merge strategy per cluster.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from .types import (
    ConsolidationAction,
    ConsolidationActionType,
    ConsolidationPlan,
    SkillCluster,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class _ClusterJudgment(BaseModel):
    """Structured LLM output for a single cluster's consolidation decision."""

    action: Literal["merge", "create_umbrella", "demote", "keep"] = Field(
        ...,
        description=(
            "Action to take: "
            "'merge' = absorb members into an existing broader skill; "
            "'create_umbrella' = create a new class-level umbrella skill; "
            "'demote' = move narrow skills to support files; "
            "'keep' = no action needed."
        ),
    )
    target_skill_name: str = Field(
        ...,
        description=(
            "For 'merge': name of the existing broader skill to expand. "
            "For 'create_umbrella': proposed name for the new umbrella. "
            "For 'demote': name of the primary skill that keeps its identity. "
            "For 'keep': any member name."
        ),
    )
    reasoning: str = Field(
        ...,
        description="Concise explanation of why this action is appropriate.",
    )
    umbrella_description: str = Field(
        default="",
        description="For 'create_umbrella': brief description of the umbrella skill.",
    )
    umbrella_content_outline: str = Field(
        default="",
        description="For 'create_umbrella': markdown outline of what the umbrella covers.",
    )
    demote_target_dir: Literal["references", "templates", "scripts"] = Field(
        default="references",
        description="For 'demote': subdirectory to move content into.",
    )


_JUDGE_PROMPT_TEMPLATE = """You are an expert skill architect evaluating a cluster of similar agent skills.

**Context**: The system has detected a cluster of {cluster_size} skills that appear related.
Your task is to determine the optimal consolidation strategy.

**Cluster Information**:
- Domain: {shared_domain}
- Average similarity: {avg_similarity:.2f}
- Representative keywords: {keywords}

**Skills in this cluster**:
{skills_detail}

**Available broader skills outside this cluster** (potential merge targets):
{broader_skills}

**Instructions**:
1. Analyze the cluster members. Are they truly related, or just superficially similar?
2. If related, choose the BEST consolidation strategy:
   - **merge**: One existing skill is clearly the "umbrella" and others are sub-cases.
     Use when one skill is already broad enough to encompass the others.
   - **create_umbrella**: No single skill is broad enough. Create a new class-level
     skill that encompasses all members. Name it at the domain level (e.g. "git_operations_skill"
     instead of "git_commit_skill").
   - **demote**: Some skills are too narrow/specific to be standalone. Their content
     should become support files (references/templates/scripts) of a parent skill.
   - **keep**: The skills are related but serve distinct purposes. No consolidation needed.
3. For 'merge' or 'create_umbrella', the consolidated skill MUST use a class-level name.
4. Prefer 'merge' over 'create_umbrella' when a suitable target exists.
5. Choose 'keep' if consolidation would lose important distinctions.

**Output**: Respond with the structured JSON schema.
"""


class ConsolidationJudge:
    """LLM-driven judge for skill consolidation decisions.

    Evaluates each SkillCluster independently and determines the optimal
    consolidation action. Uses structured output for reliable parsing.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    async def judge_clusters(
        self,
        clusters: list[SkillCluster],
        all_skills: list[SkillMetadata],
    ) -> ConsolidationPlan:
        """Evaluate all clusters and produce a consolidation plan.

        Args:
            clusters: Detected skill clusters to evaluate.
            all_skills: Complete skill list (for identifying broader merge targets).

        Returns:
            ConsolidationPlan with actions for each cluster that needs consolidation.
        """
        plan = ConsolidationPlan()

        for cluster in clusters:
            action = await self._judge_single_cluster(cluster, all_skills)
            if action is not None:
                plan.actions.append(action)
                plan.total_skills_affected += len(action.source_skills)
                if action.action_type != ConsolidationActionType.KEEP:
                    plan.estimated_reduction += len(action.source_skills) - 1

        plan.preview_summary = self._build_preview_summary(plan)
        return plan

    async def _judge_single_cluster(
        self,
        cluster: SkillCluster,
        all_skills: list[SkillMetadata],
    ) -> ConsolidationAction | None:
        """Judge a single cluster using LLM structured output."""
        cluster_skill_set = set(cluster.skill_names)
        cluster_skills = [s for s in all_skills if s.name in cluster_skill_set]
        broader_skills = [s for s in all_skills if s.name not in cluster_skill_set]

        skills_detail = "\n".join(
            f"- **{s.name}**: {s.description} (calls: {s.usage_stats.call_count}, "
            f"last used: {s.usage_stats.last_used_at or 'never'})"
            for s in cluster_skills
        )

        broader_detail = "\n".join(
            f"- {s.name}: {s.description}"
            for s in broader_skills[:15]
        ) or "None"

        prompt = _JUDGE_PROMPT_TEMPLATE.format(
            cluster_size=len(cluster.skill_names),
            shared_domain=cluster.shared_domain,
            avg_similarity=cluster.avg_similarity,
            keywords=", ".join(cluster.representative_keywords) or "N/A",
            skills_detail=skills_detail,
            broader_skills=broader_detail,
        )

        try:
            structured_llm = self._llm.with_structured_output(_ClusterJudgment)
            judgment: _ClusterJudgment | None = await structured_llm.ainvoke(prompt)

            if judgment is None:
                logger.warning(
                    "ConsolidationJudge: LLM returned None for cluster '%s'",
                    cluster.cluster_id,
                )
                return None

            action_type = ConsolidationActionType(judgment.action)

            if action_type == ConsolidationActionType.KEEP:
                logger.info(
                    "ConsolidationJudge: KEEP cluster '%s' — %s",
                    cluster.cluster_id,
                    judgment.reasoning,
                )
                return None

            source_skills = tuple(
                name for name in cluster.skill_names
                if name != judgment.target_skill_name
            )

            return ConsolidationAction(
                action_type=action_type,
                target_skill=judgment.target_skill_name,
                source_skills=source_skills,
                reasoning=judgment.reasoning,
                umbrella_description=judgment.umbrella_description,
                umbrella_content_outline=judgment.umbrella_content_outline,
                demote_target_dir=judgment.demote_target_dir,
            )

        except Exception as e:
            logger.error(
                "ConsolidationJudge: Failed to judge cluster '%s': %s",
                cluster.cluster_id,
                e,
            )
            return None

    @staticmethod
    def _build_preview_summary(plan: ConsolidationPlan) -> str:
        """Build a human-readable preview summary for GUI display."""
        if plan.is_empty:
            return "No consolidation needed — all skills are well-organized."

        lines: list[str] = []
        for action in plan.actions:
            match action.action_type:
                case ConsolidationActionType.MERGE:
                    lines.append(
                        f"• Merge {len(action.source_skills)} skills into '{action.target_skill}'"
                    )
                case ConsolidationActionType.CREATE_UMBRELLA:
                    lines.append(
                        f"• Create umbrella '{action.target_skill}' absorbing "
                        f"{len(action.source_skills)} skills"
                    )
                case ConsolidationActionType.DEMOTE:
                    lines.append(
                        f"• Demote {len(action.source_skills)} skills to "
                        f"{action.demote_target_dir}/ of '{action.target_skill}'"
                    )
                case ConsolidationActionType.KEEP:
                    pass

        lines.append(
            f"\nEstimated net reduction: {plan.estimated_reduction} active skills"
        )
        return "\n".join(lines)
