"""Skill review engine — LLM-driven trajectory analysis for experience distillation.

Analyzes pruned conversation trajectories to extract reusable skills or semantic memories.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- myrm_agent_harness.utils.logger_utils::get_agent_logger (POS: Agent logger factory)

[OUTPUT]
- review_trajectory_with_llm(): analyze trajectory, return SkillReviewResult
- SkillReviewResult: structured review output (skill_draft | semantic_memory | no value)

[POS]
Skill review engine. Calls cheap LLM to judge if a conversation trajectory
contains reusable experience worth codifying as a Skill or Semantic Memory.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SkillExtractionRubric(BaseModel):
    """Class-First 10-Dim Rubric for skill extraction from trajectories."""

    structure_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Frontmatter quality and structured format.",
    )
    workflow_clarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Clarity of execution steps and parameters. Must be actionable.",
    )
    failure_mode_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Explicit encoding of failure modes (if-then recovery branches). Low score if no error recovery is documented.",
    )
    anti_pattern_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Clear negative examples and blacklists (what NOT to do).",
    )
    human_in_loop_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Safe checkpoints for dangerous operations. Uses explicit visual markers.",
    )
    resource_integration_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Proper use of artifacts, files, and scripts without hallucinated resources.",
    )
    anti_fluff_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Free of AI-fluff words, concise and strict. No 'suggest' or 'maybe'.",
    )
    anti_fragmentation_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Generalizable, does not hardcode specific paths/names. Not specific to today's task only.",
    )
    sandbox_compatibility_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Sandbox-safe. Does not assume external global credentials or break out of workspace.",
    )
    multi_agent_isolation_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Safe for shared usage, specifies targeted Agent_ID constraints or avoids polluting other agents' scopes.",
    )

    reasoning: str = Field(..., description="Detailed explanation for the scores.")

    result_type: Literal["nothing", "semantic_memory", "skill_draft", "skill_patch"] = (
        Field(
            ...,
            description="The type of extraction to perform based on the scores. If total score is low, choose 'nothing'.",
        )
    )

    # Only populate these if result_type != "nothing"
    content: str | None = Field(
        None, description="For semantic_memory: The factual statement."
    )
    skill_name: str | None = Field(
        None, description="For skill_draft or skill_patch: The name of the skill."
    )
    skill_description: str | None = Field(
        None, description="For skill_draft: Brief description."
    )
    trigger_condition: str | None = Field(
        None, description="For skill_draft: When should this be used."
    )
    skill_steps: str | None = Field(
        None, description="For skill_draft: Step-by-step guide or code snippet."
    )
    patch_content: str | None = Field(
        None, description="For skill_patch: DIFF patch blocks."
    )

    @property
    def total_score(self) -> float:
        """Calculate weighted total score."""
        return (
            (self.structure_score * 0.05)
            + (self.workflow_clarity_score * 0.15)
            + (self.failure_mode_score * 0.15)
            + (self.anti_pattern_score * 0.10)
            + (self.human_in_loop_score * 0.05)
            + (self.resource_integration_score * 0.05)
            + (self.anti_fluff_score * 0.10)
            + (self.anti_fragmentation_score * 0.10)
            + (self.sandbox_compatibility_score * 0.15)
            + (self.multi_agent_isolation_score * 0.10)
        )


_REVIEW_PROMPT_TEMPLATE = """You are an expert software architect reviewing an Agent conversation trajectory to extract durable skills.

**Task**: Extract reusable Skills or Semantic Memory using our 10-Dimensional Sandbox-Ready Rubric.

**Original Goal**:
{original_goal}

**Active Skills Used in Session**:
{active_skills}

**All Available Skills (name — description)**:
{all_skills_catalog}

**Conversation Trajectory (Pruned)**:
{trajectory_skeleton}

**Instructions**:
1. Focus heavily on **non-trivial error recovery** and **if-then failure modes**. If the agent hit a bug and recovered, you MUST extract the failure context and the fallback action.
2. Evaluate using the 10-Dim Rubric:
   - Structure & Workflow Clarity (no ambiguous "suggest" or "maybe").
   - Failure Modes & Anti-patterns (explicitly state what NOT to do).
   - Human-in-the-Loop & Resource Integration.
   - Anti-fluff & Anti-fragmentation (must be generalizable).
   - Sandbox & Multi-Agent Compatibility (must not break sandbox bounds or pollute other agents).
3. **DO NOT CAPTURE** transient environment failures (e.g., "apt-get is missing", "network timed out") as permanent rules unless they represent a consistent fallback pattern (e.g., "always use pnpm instead of npm").
4. **NAMING CONSTRAINT**: For `skill_draft`, the name MUST be class-level, generalized, and lowercase with hyphens (e.g. `nextjs-pnpm-resilient-install`).
5. **PRIORITY ORDER**:
   a. **skill_patch** to a currently-loaded skill.
   b. **skill_patch** to an existing umbrella skill.
   c. **skill_draft** only when no existing skill covers it.
6. If the scores across the 10 dimensions are generally low (< 0.6 average) or if the skill is trivial, output `result_type: "nothing"`.

**Output Format**: Use the provided structured JSON schema.
"""


class SkillReviewResult:
    """Review result structure.

    Defined at framework layer; business layer handles persistence and notifications.
    Carries session context (user_id/agent_id/chat_id) for business layer persistence.
    """

    def __init__(
        self,
        has_value: bool,
        result_type: str | None = None,
        content: str | None = None,
        skill_name: str | None = None,
        skill_description: str | None = None,
        trigger_condition: str | None = None,
        skill_steps: str | None = None,
        patch_content: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.has_value = has_value
        self.result_type = result_type
        self.content = content
        self.skill_name = skill_name
        self.skill_description = skill_description
        self.trigger_condition = trigger_condition
        self.skill_steps = skill_steps
        self.patch_content = patch_content
        self.user_id = user_id
        self.agent_id = agent_id
        self.chat_id = chat_id

    def to_dict(self) -> dict[str, object]:
        return {
            "has_value": self.has_value,
            "type": self.result_type,
            "content": self.content,
            "skill_name": self.skill_name,
            "skill_description": self.skill_description,
            "trigger_condition": self.trigger_condition,
            "skill_steps": self.skill_steps,
            "patch_content": self.patch_content,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "chat_id": self.chat_id,
        }


async def review_trajectory_with_llm(
    trajectory_skeleton: str,
    llm: BaseChatModel,
    active_skills: list[str] | None = None,
    all_skills_catalog: str | None = None,
    original_goal: str | None = None,
) -> SkillReviewResult | None:
    """Call LLM to review a pruned trajectory.

    Args:
        trajectory_skeleton: Pruned conversation trajectory string.
        llm: LLM for review (recommend using cheap extraction_llm).
        active_skills: List of skill names loaded/used in current session.
        all_skills_catalog: Summary of all existing skills (name + description),
            formatted as "name -- description" per line, built by caller.
        original_goal: Original task goal, used for anti-drift (Goal Drift) evaluation.

    Returns:
        SkillReviewResult structure, or None if review failed.

    Example:
        >>> skeleton = "<User>: How to fix this bug?\\n<Tool-Call>: bash(cmd='grep error')"
        >>> catalog = "create-react-page — Create a new React page component"
        >>> result = await review_trajectory_with_llm(skeleton, cheap_llm, all_skills_catalog=catalog, original_goal="Fix the bug")
        >>> if result and result.has_value:
        ...     print(f"Found skill: {result.skill_name}")
    """
    if not trajectory_skeleton:
        return None

    active_skills_str = (
        "\\n".join([f"- {s}" for s in active_skills]) if active_skills else "None"
    )
    catalog_str = all_skills_catalog if all_skills_catalog else "None"
    goal_str = original_goal if original_goal else "Not explicitly provided."

    prompt = _REVIEW_PROMPT_TEMPLATE.format(
        original_goal=goal_str,
        trajectory_skeleton=trajectory_skeleton,
        active_skills=active_skills_str,
        all_skills_catalog=catalog_str,
    )

    try:
        structured_llm = llm.with_structured_output(SkillExtractionRubric)
        rubric: SkillExtractionRubric | None = await structured_llm.ainvoke(prompt)

        if rubric is None:
            logger.warning("Skill review: LLM returned None for structured output")
            return SkillReviewResult(has_value=False)

        if (
            rubric.result_type == "nothing"
            or rubric.total_score < 0.6
            or rubric.anti_fragmentation_score < 0.6
        ):
            logger.info(
                f" Skill review: nothing valuable found or rejected by Rubric (Score: {rubric.total_score:.2f}). Reason: {rubric.reasoning}"
            )
            return SkillReviewResult(has_value=False)

        if rubric.result_type == "semantic_memory":
            content = str(rubric.content or "").strip()
            if not content:
                logger.warning(
                    " Skill review: semantic_memory has empty content, discarding"
                )
                return SkillReviewResult(has_value=False)
            logger.info(
                f" Skill review: found semantic memory (Score: {rubric.total_score:.2f})"
            )
            return SkillReviewResult(
                has_value=True, result_type="semantic_memory", content=content
            )

        elif rubric.result_type == "skill_draft":
            skill_name = str(rubric.skill_name or "").strip()
            skill_steps = str(rubric.skill_steps or "").strip()
            if not skill_name or not skill_steps:
                logger.warning(
                    " Skill review: skill_draft missing name or steps, discarding"
                )
                return SkillReviewResult(has_value=False)
            logger.info(
                f" Skill review: found skill draft (Score: {rubric.total_score:.2f})"
            )
            return SkillReviewResult(
                has_value=True,
                result_type="skill_draft",
                skill_name=skill_name,
                skill_description=str(rubric.skill_description or "").strip(),
                trigger_condition=str(rubric.trigger_condition or "").strip(),
                skill_steps=skill_steps,
            )

        elif rubric.result_type == "skill_patch":
            skill_name = str(rubric.skill_name or "").strip()
            patch_content = str(rubric.patch_content or "").strip()
            if not skill_name or not patch_content:
                logger.warning(
                    " Skill review: skill_patch missing name or patch_content, discarding"
                )
                return SkillReviewResult(has_value=False)
            logger.info(
                f" Skill review: found skill patch for {skill_name} (Score: {rubric.total_score:.2f})"
            )
            return SkillReviewResult(
                has_value=True,
                result_type="skill_patch",
                skill_name=skill_name,
                patch_content=patch_content,
            )

        else:
            logger.warning("Skill review: unknown result type '%s'", rubric.result_type)
            return SkillReviewResult(has_value=False)

    except Exception as e:
        error_msg = str(e)
        if '"result_type": "nothing"' in error_msg or "'result_type': 'nothing'" in error_msg:
            logger.info("Skill review: LLM judged nothing valuable (partial output)")
            return SkillReviewResult(has_value=False)
        logger.error("Skill review: LLM invocation failed - %s", e)
        return None
