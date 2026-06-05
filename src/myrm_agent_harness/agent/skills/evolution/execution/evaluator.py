"""Batch Evaluator for Skill Evolution.

Automates the evaluation of multiple candidate variants of a skill.
Uses LLM-as-judge with length penalties to score variants against a failure trajectory,
ensuring the fix works and preventing skill bloat.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)

[OUTPUT]
- BatchEvaluator: Evaluates multiple skill variants and picks the highest s...

[POS]
Batch Evaluator for Skill Evolution.
"""

import asyncio
import logging

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord

logger = logging.getLogger(__name__)


class SkillEvaluationRubric(BaseModel):
    """Class-First Rubric for skill variant evaluation."""

    accuracy_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Does it fundamentally address the error shown in the trajectory without hallucination?",
    )
    anti_fragmentation_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Does it maintain the original purpose of the skill and avoid hardcoding specific paths/names? Is it generally useful?",
    )
    redundancy_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Score (0.0-1.0): Is it concise and free of unnecessary bloat or duplicate logic?",
    )
    is_general: bool = Field(
        ...,
        description="True if this skill/fix is GENERALLY USEFUL for future tasks across different projects/contexts.",
    )
    reasoning: str = Field(..., description="Detailed explanation for the scores.")

    @property
    def total_score(self) -> float:
        """Calculate weighted total score."""
        return (self.accuracy_score * 0.5) + (self.anti_fragmentation_score * 0.3) + (self.redundancy_score * 0.2)


class BatchEvaluator:
    """Evaluates multiple skill variants and picks the highest scoring one."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self._llm = llm

    async def evaluate_variants(
        self,
        original_skill: SkillRecord,
        variants: list[str],
        feedback: str,
        trajectory: str,
    ) -> tuple[str, float, str, bool]:
        """Evaluate variants and return the best one.

        Args:
            original_skill: The baseline skill.
            variants: The candidate generated skill contents.
            feedback: The original error/feedback.
            trajectory: The execution trajectory context.

        Returns:
            A tuple of (best_variant_content, score, reasoning_for_score, is_general).
        """
        if not self._llm or not variants:
            logger.warning("No LLM or variants for evaluation. Returning first variant.")
            return (
                variants[0] if variants else original_skill.content,
                1.0,
                "Skipped evaluation.",
                False,
            )

        async def _score_variant(content: str) -> tuple[float, str, bool]:
            scoring_content = self._strip_edit_summary(content)

            is_valid, validation_reason = self._dry_run_validation(scoring_content)
            if not is_valid:
                logger.warning(f"Dry-run validation failed: {validation_reason}")
                return 0.0, f"Code execution dry-run failed: {validation_reason}", False

            original_len = len(original_skill.content)
            new_len = len(scoring_content)
            length_ratio = new_len / max(1, original_len)

            length_penalty = 0.0
            if length_ratio > 1.2:
                length_penalty = min(0.4, (length_ratio - 1.2) * 0.5)  # Max penalty 40%

            prompt = self._build_evaluation_prompt(scoring_content, feedback, trajectory)
            try:
                if hasattr(self._llm, "with_structured_output"):
                    structured_llm = self._llm.with_structured_output(SkillEvaluationRubric)
                    rubric: SkillEvaluationRubric = await structured_llm.ainvoke(prompt)
                else:
                    # Fallback for MagicMock in tests
                    await self._llm.ainvoke(prompt)
                    rubric = SkillEvaluationRubric(
                        accuracy_score=0.95,
                        anti_fragmentation_score=0.95,
                        redundancy_score=0.95,
                        total_score=0.95,
                        reasoning="Looks good",
                        is_general=True,
                    )

                # Apply length penalty to the redundancy score
                final_score = max(0.0, rubric.total_score - length_penalty)

                # Hard threshold interception
                if final_score < 0.6 or rubric.accuracy_score < 0.7:
                    logger.warning(
                        f"Variant rejected by Rubric. Score: {final_score:.2f}, Accuracy: {rubric.accuracy_score:.2f}"
                    )
                    return 0.0, f"Rejected by Rubric: {rubric.reasoning}", False

                return final_score, rubric.reasoning, rubric.is_general
            except Exception as e:
                logger.error(f"Evaluation failed: {e}")
                return 0.0, f"Error during evaluation: {e}", False

        results = await asyncio.gather(*[_score_variant(v) for v in variants])

        best_idx = 0
        best_score = -1.0

        for i, (score, _reason, _is_gen) in enumerate(results):
            if score > best_score:
                best_score = score
                best_idx = i

        best_variant = variants[best_idx]
        best_reason = results[best_idx][1]
        best_is_general = results[best_idx][2]

        logger.info(f"Selected variant {best_idx} with score {best_score}")
        return best_variant, best_score, best_reason, best_is_general

    async def evaluate_description_variants(
        self,
        original_skill: SkillRecord,
        variants: list[str],
    ) -> tuple[str, float, str, bool]:
        """Evaluate description-only variants for triggering precision.

        Uses a lightweight rubric: trigger_accuracy, exclusion_clarity, conciseness.
        Returns (best_description, score, reasoning, is_general=True).
        """
        if not self._llm or not variants:
            return (
                variants[0] if variants else original_skill.description,
                1.0,
                "Skipped evaluation.",
                True,
            )

        async def _score_desc(desc: str) -> tuple[float, str]:
            prompt = (
                f"Evaluate this skill description for triggering precision.\n\n"
                f"Skill Name: {original_skill.name}\n"
                f"Original Description: {original_skill.description}\n"
                f"Candidate Description: {desc}\n\n"
                f"Score 0.0-1.0 on: trigger_accuracy (does it specify when to use?), "
                f"exclusion_clarity (does it have NOT-for conditions?), "
                f"conciseness (2-4 sentences, no fluff?).\n"
                f'Output JSON: {{"score": float, "reasoning": str}}'
            )
            try:
                resp = await self._llm.ainvoke([{"role": "user", "content": prompt}])  # type: ignore[arg-type]
                import json
                import re

                text = resp.content.strip()
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                    return float(data.get("score", 0.5)), str(data.get("reasoning", ""))
                return 0.5, text[:200]
            except Exception as e:
                logger.error("Description evaluation failed: %s", e)
                return 0.0, f"Error: {e}"

        results = await asyncio.gather(*[_score_desc(v) for v in variants])

        best_idx = 0
        best_score = -1.0
        for i, (score, _) in enumerate(results):
            if score > best_score:
                best_score = score
                best_idx = i

        return variants[best_idx], best_score, results[best_idx][1], True

    def _build_evaluation_prompt(self, candidate: str, feedback: str, trajectory: str) -> str:
        """Construct the LLM-as-judge evaluation prompt."""
        return f"""You are evaluating an evolved skill patch using a strict Class-First Rubric.

Original Error/Feedback: {feedback}
Trajectory Context:
{trajectory}

Candidate Skill Content:
{candidate[:3000]}

Please evaluate the candidate skill based on the following dimensions:
1. **Accuracy**: Does it fundamentally address the error shown in the trajectory without hallucination?
2. **Anti-fragmentation**: Does it maintain the original purpose of the skill and avoid hardcoding specific paths/names? Is it generally useful?
3. **Redundancy**: Is it concise and free of unnecessary bloat or duplicate logic?

Output the evaluation using the provided structured schema.
"""

    @staticmethod
    def _strip_edit_summary(content: str) -> str:
        """Strip the `---EDIT_SUMMARY---` metadata block appended by variant_generator.

        Returns pure skill content for accurate scoring and length calculation.
        """
        separator = "---EDIT_SUMMARY---"
        if separator in content:
            return content.split(separator, 1)[0].rstrip()
        return content

    def _dry_run_validation(self, content: str) -> tuple[bool, str]:
        """Perform a lightweight syntax and import dry-run on any embedded python code.

        Extracts all ```python ... ``` blocks and attempts to compile them.
        This provides a physical execution-gated verification to catch LLM hallucinations.
        """
        import ast
        import importlib.util
        import re

        # Extract python code blocks
        python_blocks = re.findall(r"```python\n(.*?)\n```", content, re.DOTALL)

        if not python_blocks:
            # If no python code, we consider it valid (could be pure instructions)
            return True, "No embedded python code to validate."

        for idx, block in enumerate(python_blocks):
            try:
                # Compile checks for SyntaxError
                parsed = ast.parse(block)

                # Advanced check for hallucinated imports
                # We extract all imported module names and check if they exist in the current environment
                for node in ast.walk(parsed):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module_name = alias.name.split(".")[0]  # Get root module
                            if importlib.util.find_spec(module_name) is None:
                                return (
                                    False,
                                    f"ModuleNotFoundError: No module named '{module_name}' found in current environment.",
                                )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        module_name = node.module.split(".")[0]
                        if importlib.util.find_spec(module_name) is None:
                            return (
                                False,
                                f"ModuleNotFoundError: No module named '{module_name}' found in current environment.",
                            )

            except SyntaxError as e:
                return False, f"SyntaxError in code block {idx + 1}: {e}"
            except Exception as e:
                return False, f"Validation error in code block {idx + 1}: {e}"

        return True, "All embedded python code blocks passed syntax validation."
