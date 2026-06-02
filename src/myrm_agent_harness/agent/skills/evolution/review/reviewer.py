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
    """Class-First Rubric for skill extraction from trajectories."""

    accuracy_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Does the trajectory contain genuinely useful, non-trivial problem-solving steps?",
    )
    anti_fragmentation_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Is the proposed skill cohesive and generalizable? Low score if it hardcodes specific paths/names, uses fix-/debug-/audit- prefixes, or only applies to today's task.",
    )
    redundancy_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Is this workflow NOT already covered by existing skills?",
    )
    goal_alignment_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Did the execution path stay aligned with the original goal? (Low score if Goal Drift occurred).",
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
            (self.accuracy_score * 0.3)
            + (self.anti_fragmentation_score * 0.2)
            + (self.redundancy_score * 0.2)
            + (self.goal_alignment_score * 0.3)
        )


_REVIEW_PROMPT_TEMPLATE = """You are an expert software engineer reviewing a recent Agent conversation.

**Task**: Analyze the following conversation trajectory and determine if there's any valuable experience worth codifying as a reusable Skill or factual Semantic Memory.

**Original Goal**:
{original_goal}

**Active Skills Used in Session**:
{active_skills}

**All Available Skills (name — description)**:
{all_skills_catalog}

**Conversation Trajectory (Pruned)**:
{trajectory_skeleton}

**Instructions**:
1. Review the trajectory against the **Original Goal**. Did the agent achieve the goal? Was the path reasonable? Did the agent drift away from the original goal during execution?
2. Focus on **non-trivial decision paths** (e.g., exploring multiple approaches, recovering from errors, combining tools in a novel way).
3. Evaluate the potential extraction using the Class-First Rubric (Accuracy, Anti-fragmentation, Redundancy, Goal Alignment).
4. **ANTI-DRIFT GUARD**: If the execution path significantly deviated from the Original Goal (Goal Drift), or if the final result does not match the original specification, you MUST score `goal_alignment_score` low and output `result_type: "nothing"`. Do not learn from drifted or failed paths.
5. If the trajectory is trivial, or if the Rubric scores are low, output `result_type: "nothing"`.
6. **DO NOT CAPTURE** any of the following — they harden into self-imposed constraints that harm future performance:
   - Environment-dependent failures: missing binaries, fresh-install errors, unconfigured credentials, uninstalled packages, path mismatches. The user can fix these; they are not durable rules.
   - Negative claims about tools or features ("X tool is broken", "cannot use Y", "browser does not work"). These become permanent refusals the agent cites long after the underlying issue is fixed.
   - Session-specific transient errors that resolved before the conversation ended. If retrying worked, learn the retry pattern, not the original failure.
   - One-off task narratives that do not generalize into a class of work (e.g., "summarize today's report").
   If the ONLY signal in the trajectory is one of the above, output `result_type: "nothing"`.
7. **NAMING CONSTRAINT**: If proposing a `skill_draft`, the `skill_name` MUST be class-level:
   - FORBIDDEN: names starting with fix-/debug-/audit-, specific error strings, PR/issue numbers, feature codenames, library-alone names, or "today's task" patterns.
   - REQUIRED: a name that still makes sense 6 months from now and covers a reusable class of work.
   - If the best name you can think of only fits today's task, fall back to `skill_patch` on an existing skill instead.
8. **PRIORITY ORDER** — prefer the earliest action that fits:
   a. **skill_patch** to a currently-loaded skill (listed under "Active Skills Used in Session"). It was in play; it is the right place.
   b. **skill_patch** to an existing umbrella skill (listed under "All Available Skills").
   c. **skill_draft** only when no existing skill covers the class of work.
   Bias heavily toward patching existing skills over creating new ones.
9. **IMPORTANT**: Before proposing a new skill, check the "All Available Skills" list above. If a skill with similar functionality already exists, output a **skill_patch** to update it instead of creating a duplicate.
10. If valuable experience is found and passes the Rubric:
   a. **For Semantic Memory (Facts about user/project)**: Set `result_type: "semantic_memory"` and populate `content`.
   b. **For Skill Draft (New reusable operation flow)**: Set `result_type: "skill_draft"` and populate `skill_name`, `skill_description`, `trigger_condition`, and `skill_steps`.
   c. **For Skill Patch (Updating an existing skill)**: Set `result_type: "skill_patch"` and populate `skill_name` and `patch_content`.

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
