"""Evolution judge - LLM-as-Judge confidence scoring.

[INPUT] Evolved skill content
[OUTPUT] JudgeResult
[POS] myrm_agent_harness/agent/skills/evolution/judge.py

## Architecture

Post-patch LLM-as-Judge to score the elegance and safety of the fix.
Outputs a confidence score (0.0-1.0) used by the Server layer to determine
if the patch can be silently applied or requires human review.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

__all__ = ["EvolutionJudge", "JudgeResult"]


@dataclass
class JudgeResult:
    """Result of evolution LLM-as-Judge scoring."""

    confidence: float  # 0.0 to 1.0
    reason: str


class EvolutionJudge:
    """Evaluates evolved skill code quality using a cheap LLM."""

    def __init__(self, judge_llm: BaseChatModel | None = None):
        """Initialize judge.

        Args:
            judge_llm: Cheap LLM for judging (e.g., gpt-4o-mini, claude-haiku-3)
        """
        self._judge_llm = judge_llm

    async def evaluate(self, original_content: str, evolved_content: str, error_message: str) -> JudgeResult:
        """Evaluate evolved code.

        Args:
            original_content: Original skill source code
            evolved_content: Evolved skill source code
            error_message: The error that triggered the evolution

        Returns:
            JudgeResult with confidence score and reasoning
        """
        if not self._judge_llm:
            # If no judge LLM configured, default to manual review required (confidence 0.5)
            return JudgeResult(confidence=0.5, reason="No judge LLM configured")

        prompt = self._build_judge_prompt(original_content, evolved_content, error_message)

        try:
            response = await self._judge_llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()

            confidence, reason = self._parse_llm_response(content)

            logger.info("Evolution Judge scored fix with confidence %.2f: %s", confidence, reason[:100])
            return JudgeResult(confidence=confidence, reason=reason)

        except Exception as e:
            logger.error("LLM judge evaluation failed: %s", e)
            # Fail-safe: default to manual review required
            return JudgeResult(confidence=0.5, reason=f"LLM judge evaluation failed: {e}")

    def _parse_llm_response(self, content: str) -> tuple[float, str]:
        """Parse LLM judge response.

        Looks for a JSON-like or explicit confidence score.

        Args:
            content: LLM response content

        Returns:
            Tuple of (confidence: float, reason: str)
        """
        confidence = 0.5  # Default

        # Try to extract confidence score
        confidence_pattern = r"confidence[:\s]+([0-9.]+)"
        confidence_match = re.search(confidence_pattern, content, re.IGNORECASE)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                if confidence > 1.0:  # Handle percentage format (e.g. 95)
                    confidence = confidence / 100.0
            except ValueError:
                pass

        # Clamp between 0 and 1
        confidence = max(0.0, min(1.0, confidence))

        return confidence, content.strip()

    def _build_judge_prompt(self, original_content: str, evolved_content: str, error_message: str) -> str:
        """Build prompt for LLM judge."""
        return f"""You are an expert Python code reviewer. Evaluate the quality and safety of an automated code fix.

Error that triggered the fix:
{error_message[:1000]}

Original Code (first 2000 chars):
{original_content[:2000]}

Evolved Code (first 2000 chars):
{evolved_content[:2000]}

Evaluate the evolved code on three dimensions:
1. Correctness: Does it actually fix the reported error?
2. Safety: Does it introduce any obvious security vulnerabilities or destructive operations?
3. Conciseness: Is the fix elegant, or does it add unnecessary bloat?

Provide a confidence score between 0.0 and 1.0, where:
- 0.9 to 1.0: Perfect fix, safe to apply silently without human review.
- 0.5 to 0.8: Seems okay, but requires human review just in case.
- 0.0 to 0.4: Dangerous or incorrect fix, must be rejected.

Format your response exactly like this:
Confidence: 0.95
Reasoning: The fix correctly addresses the KeyError by adding a safe .get() fallback. No new dependencies or risky operations were introduced.
"""
