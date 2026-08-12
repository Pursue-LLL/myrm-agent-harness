"""[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LLM instance for structured skill extraction)
- myrm_agent_harness.utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取 — 兼容 reasoning 模型 content 空回退)
- myrm_agent_harness.utils.json_parsing::parse_llm_json_object (POS: robust JSON object extraction from LLM output — fences, prose, bare control chars, trailing commas)

[OUTPUT]
- SkillCaptureResult: Structured output for skill extraction with form routing.
- StructuredExtractor: Extracts skills using structured LLM output.

[POS]
Provides SkillCaptureResult, StructuredExtractor.
"""

import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from myrm_agent_harness.utils.chat_utils import (
    extract_answer_text,
    parse_llm_json_object,
)

logger = logging.getLogger(__name__)


class SkillCaptureResult(BaseModel):
    """Structured output for skill extraction with form routing."""

    is_general: bool = Field(
        ...,
        description="Whether the skill is generalizable and reusable across different contexts, projects, or users. False if it's tied to highly specific local file paths or one-off tasks.",
    )
    confidence: float | str = Field(
        ...,
        description="Confidence score between 0.0 and 1.0 that this skill is correct and valuable.",
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def parse_confidence(cls, v: object) -> float:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ("high", "very high", "certain"):
                return 1.0
            if v_lower in ("medium", "moderate"):
                return 0.5
            if v_lower in ("low", "very low", "uncertain"):
                return 0.1
            try:
                return float(v)
            except ValueError:
                return 0.8  # fallback
        if isinstance(v, (int, float)):
            return float(v)
        return 0.8  # 非数值输入的安全回退

    safety_analysis: str = Field(
        ...,
        description="Brief analysis of potential safety risks (e.g., does it execute destructive commands? leak credentials?).",
    )
    name: str = Field(
        ...,
        description="A short, kebab-case name for the skill (e.g., 'nginx-502-fix').",
    )
    content: str = Field(
        ...,
        description="The complete, valid SKILL.md file content including YAML frontmatter and Markdown instructions.",
    )
    recommended_form: Literal["skill", "cron_job", "skip"] = Field(
        default="skill",
        description=(
            "The smallest appropriate form for this pattern. "
            "'skill' = reusable instructions invoked on demand; "
            "'cron_job' = a recurring/scheduled task that should run automatically on a time schedule; "
            "'skip' = not worth capturing (too trivial or one-off)."
        ),
    )
    schedule_hint: str | None = Field(
        default=None,
        description="When recommended_form is 'cron_job', a natural-language schedule suggestion (e.g., 'every weekday at 9am', 'every Monday'). Null otherwise.",
    )
    form_reasoning: str = Field(
        default="",
        description="Brief explanation of why this form was chosen over alternatives.",
    )
    eval_cases: list[dict[str, object]] | None = Field(
        default=None,
        description=(
            "1-3 lightweight regression test cases for this skill. "
            "Each case: {'message': str, 'sandbox_assertions': [{'type': str, 'target': str}]}. "
            "Types: 'code_contains', 'code_not_contains', 'ast_valid', 'imports_module', 'regex_match'."
        ),
    )


_EXTRACTION_PROMPT = """You are an expert AI Architect and Skill Extraction Engine.
Your task is to analyze the provided conversation trajectory between a User and an Assistant.
Determine if the Assistant successfully completed a complex, multi-step task that could be generalized into a reusable "Skill".

A "Skill" is a structured set of instructions that teaches an AI how to perform a specific task.

CRITERIA FOR A GOOD SKILL:
1. Complex enough to require multiple steps or specific tool usage.
2. Generalizable (not tied to a single, highly specific instance or absolute path).
3. Safe (does not contain `rm -rf /` or credential exposure).

FORM ROUTING — Choose the smallest appropriate form:
- "skill": The pattern is best captured as reusable instructions invoked on demand by the user.
- "cron_job": The pattern involves a task the user performs on a regular schedule (daily, weekly, etc.) and would benefit from automatic execution. Look for temporal cues like "every day", "every week", "check regularly", or repeated identical requests across sessions.
- "skip": The conversation is too trivial, too specific, or a one-off to be worth capturing.

If the conversation meets the criteria, you must output the structured data containing `is_general`, `confidence`, `safety_analysis`, `name`, `content`, `recommended_form`, `schedule_hint`, `form_reasoning`, and `eval_cases`.

EVAL CASES (required for non-skip skills):
Generate 1-3 lightweight regression test cases in `eval_cases`. Each case should have:
- `message`: A representative user input that would trigger this skill.
- `sandbox_assertions`: Objective checks on the skill code. Each assertion has `type` (one of: `code_contains`, `code_not_contains`, `ast_valid`, `imports_module`, `regex_match`) and `target` (the value to check).
Focus on invariant properties that should always hold when the skill evolves.

The SKILL.md `content` MUST strictly follow this structure:
---
name: <kebab-case-short-name>
description: <A clear, concise description of what this skill does (max 100 chars)>
version: 1.0.0
category: custom
tags: [<tag1>, <tag2>]
---

# <Skill Title>

## Objective
<Brief objective>

## Instructions
<Step-by-step generalized instructions extracted from the successful interaction>
1. Step 1...
2. Step 2...

(If the skill involves executing code, include the full Python code wrapped in ```python blocks here)

## Best Practices
- <Any best practices or edge cases observed>

CRITICAL JSON FORMATTING INSTRUCTION:
Your output MUST be a single, valid JSON object matching the requested schema.
The entire Markdown content (including the YAML frontmatter, headers, and code blocks) MUST be placed INSIDE the `content` field of the JSON object as a single string, with newlines properly escaped as `\\n`.
DO NOT output any markdown outside of the JSON structure!
"""


class StructuredExtractor:
    """Extracts skills using structured LLM output."""

    def __init__(self, llm: BaseChatModel):
        self._llm = llm

    async def extract_from_trajectory(
        self, trajectory: str
    ) -> SkillCaptureResult | None:
        """Extract a skill from a conversation trajectory."""
        messages = [
            SystemMessage(content=_EXTRACTION_PROMPT),
            HumanMessage(
                content=f"Analyze this conversation trajectory:\n\n{trajectory}"
            ),
        ]

        try:
            # Try to use with_structured_output for robust extraction
            # If the model supports it, it will return the Pydantic object
            structured_llm = self._llm.with_structured_output(SkillCaptureResult)

            result = await structured_llm.ainvoke(messages)

            if isinstance(result, SkillCaptureResult):
                logger.info(
                    f"Extracted structured skill: {result.name} (general: {result.is_general}, conf: {result.confidence})"
                )
                return result
            else:
                logger.warning("LLM failed to return structured SkillCaptureResult.")

        except Exception as e:
            logger.error(f"Structured extraction failed: {e}")

        # Fallback to raw JSON parsing
        try:
            logger.info("Falling back to raw JSON parsing for skill extraction.")
            raw_result = await self._llm.ainvoke(messages)
            # 兼容 reasoning 模型 content 空回退（Qwen3/DeepSeek-R1 等）
            content = extract_answer_text(raw_result)
            data = parse_llm_json_object(content)
            if data is not None:
                result = SkillCaptureResult.model_validate(data)
                logger.info(
                    f"Fallback extracted structured skill: {result.name} (general: {result.is_general}, conf: {result.confidence})"
                )
                return result
        except Exception as fallback_e:
            logger.error(f"Fallback extraction failed: {fallback_e}")

        return None
