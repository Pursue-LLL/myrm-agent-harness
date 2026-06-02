"""Batch LLM confirmation for evolution candidates.

Provides production-optimized batch confirmation:
- Single LLM call for multiple candidates (90% cost reduction vs lime)
- Rejection reason tracking (for rule-based strategy optimization)
- Confidence scores (for threshold tuning)
- Async batch processing with exception tolerance

vs OpenSpace (lime):
-  Batch processing (lime: one-by-one, 10 skills = 10 LLM calls)
-  Rejection analysis (lime: no reason tracking)
-  Confidence scores (lime: no confidence)
-  90% cost reduction (10 skills → 1 LLM call)

[INPUT]
- (none)

[OUTPUT]
- ConfirmationResult: Result of LLM confirmation for a single candidate.
- BatchEvolutionConfirmer: Batch LLM confirmation for evolution candidates.

[POS]
Batch LLM confirmation for evolution candidates.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


logger = logging.getLogger(__name__)

__all__ = [
    "BatchEvolutionConfirmer",
    "ConfirmationResult",
]


@dataclass
class ConfirmationResult:
    """Result of LLM confirmation for a single candidate."""

    skill_id: str
    confirmed: bool
    reason: str  # Why confirmed/rejected (for analysis)
    confidence: float  # 0.0-1.0 (for threshold tuning)


class BatchEvolutionConfirmer:
    """Batch LLM confirmation for evolution candidates.

    Framework layer component (开箱即用):
    - Optimizes multiple confirmations into single LLM call
    - Tracks rejection reasons for rule-based strategy optimization
    - Provides confidence scores for threshold tuning
    """

    def __init__(self, llm: BaseChatModel):
        """Initialize batch confirmer.

        Args:
            llm: LLM client (BaseChatModel)
        """
        self._llm = llm

    async def batch_confirm_evolution(self, candidates: list[dict], trigger_context: str) -> list[ConfirmationResult]:
        """Batch confirm multiple evolution candidates in a single LLM call.

        Args:
            candidates: List of dicts with:
                - skill_id: str
                - skill_name: str
                - skill_content_summary: str (truncated, ~500 chars)
                - proposed_type: str ("FIX", "DERIVED", etc.)
                - proposed_direction: str (evolution direction)
                - recent_metrics: Optional[str] (metric summary)
            trigger_context: Context about what triggered these evolutions

        Returns:
            List of ConfirmationResults (one per candidate)
            Returns empty results (confirmed=False) if LLM call fails
        """
        if not candidates:
            return []

        # Build batch confirmation prompt
        prompt = self._build_batch_prompt(candidates, trigger_context)

        try:
            from langchain_core.messages import HumanMessage

            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            response_text = response.content

            # Parse JSON array
            data = self._extract_json(response_text)
            if not data or "confirmations" not in data:
                logger.error("Batch confirmation: LLM response missing 'confirmations' key")
                return self._default_rejections(candidates)

            confirmations = data["confirmations"]
            if not isinstance(confirmations, list):
                logger.error("Batch confirmation: 'confirmations' is not a list")
                return self._default_rejections(candidates)

            # Map results back to candidates (by skill_id)
            results = []
            for candidate in candidates:
                skill_id = candidate["skill_id"]
                # Find matching confirmation
                confirmation = next((c for c in confirmations if c.get("skill_id") == skill_id), None)

                if confirmation:
                    results.append(
                        ConfirmationResult(
                            skill_id=skill_id,
                            confirmed=bool(confirmation.get("confirmed", False)),
                            reason=str(confirmation.get("reason", "No reason provided")),
                            confidence=float(confirmation.get("confidence", 0.5)),
                        )
                    )
                else:
                    # LLM didn't return confirmation for this skill - default reject
                    logger.warning(f"Batch confirmation: no result for skill {skill_id}")
                    results.append(
                        ConfirmationResult(
                            skill_id=skill_id,
                            confirmed=False,
                            reason="LLM did not return confirmation for this skill",
                            confidence=0.0,
                        )
                    )

            logger.info(f"Batch confirmation: {sum(1 for r in results if r.confirmed)}/{len(results)} confirmed")
            return results

        except Exception as e:
            logger.error(f"Batch confirmation failed: {e}", exc_info=True)
            return self._default_rejections(candidates)

    def _build_batch_prompt(self, candidates: list[dict], trigger_context: str) -> str:
        """Build batch confirmation prompt.

        Args:
            candidates: List of candidate dicts
            trigger_context: Trigger context

        Returns:
            Formatted prompt for LLM
        """
        # Build candidate summary
        candidate_lines = []
        for i, c in enumerate(candidates, 1):
            metrics_str = f"\n   Metrics: {c['recent_metrics']}" if c.get("recent_metrics") else ""
            candidate_lines.append(
                f"{i}. **{c['skill_id']}** ({c['skill_name']})\n"
                f" Type: {c['proposed_type']}\n"
                f" Direction: {c['proposed_direction']}{metrics_str}"
            )

        candidates_text = "\n\n".join(candidate_lines)

        return f"""You are reviewing {len(candidates)} potential skill evolution actions.
For each candidate, determine if evolution is truly necessary based on the provided context.

## Trigger Context

{trigger_context}

## Evolution Candidates

{candidates_text}

## Your Task

For each candidate, analyze:
1. Is the proposed evolution truly necessary?
2. Will the evolution likely succeed and improve the skill?
3. Is the direction clear and actionable?

Output a JSON object with the following format:

```json
{{
  "confirmations": [
    {{
      "skill_id": "exact_skill_id_from_above",
      "confirmed": true/false,
      "reason": "Brief reason for your decision (1-2 sentences)",
      "confidence": 0.0-1.0
    }}
  ]
}}
```

Guidelines:
- Confirm (true) if: Clear improvement opportunity, actionable direction, high success likelihood
- Reject (false) if: Unclear direction, low success probability, or insufficient evidence
- Confidence: 0.0=very uncertain, 0.5=moderate, 1.0=very confident
- Ensure you output one confirmation for each candidate listed above
"""

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract JSON object from LLM response.

        Handles markdown code fences and bare JSON.

        Args:
            text: LLM response text

        Returns:
            Parsed JSON dict, or None if parsing failed
        """
        # Try code block first
        code_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if code_match:
            text = code_match.group(1).strip()
        else:
            # Try bare JSON object
            json_match = re.search(r"\{.*\}", text, re.DOTALL)
            if json_match:
                text = json_match.group()

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            logger.warning(f"Batch confirmation: LLM returned non-dict JSON: {type(data)}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Batch confirmation: Failed to parse JSON: {e}")
            logger.debug(f"Raw LLM output (first 500 chars): {text[:500]}")
            return None

    @staticmethod
    def _default_rejections(candidates: list[dict]) -> list[ConfirmationResult]:
        """Return default rejection results (fallback on error).

        Args:
            candidates: List of candidate dicts

        Returns:
            List of rejected ConfirmationResults
        """
        return [
            ConfirmationResult(
                skill_id=c["skill_id"], confirmed=False, reason="Batch confirmation failed", confidence=0.0
            )
            for c in candidates
        ]
