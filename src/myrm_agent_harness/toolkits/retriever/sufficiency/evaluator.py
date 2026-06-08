"""Retrieval sufficiency evaluator.

[INPUT]
- core.config.llm::LLMConfig (POS: LLM configuration for the evaluation model)
- toolkits.llms.core.llm::create_litellm_model (POS: LiteLLM model factory)
- .types::SufficiencyVerdict, SufficiencyConfig (POS: result and config types)
- .prompts::SUFFICIENCY_EVAL_SYSTEM, SUFFICIENCY_EVAL_USER_TEMPLATE, SUFFICIENCY_JSON_SCHEMA (POS: prompt templates)

[OUTPUT]
- evaluate_sufficiency(): async function that evaluates whether retrieved snippets
  are sufficient to answer a user query.

[POS]
Core evaluator for the Retrieval Sufficiency Guard. Uses a lightweight LLM
(same model as main agent or a dedicated cheap model) to assess retrieval quality.
Designed for conditional activation: only runs when explicitly enabled and on
queries that benefit from evaluation (e.g., complex multi-aspect queries,
queries with negative constraints).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from .prompts import SUFFICIENCY_EVAL_SYSTEM, SUFFICIENCY_EVAL_USER_TEMPLATE, SUFFICIENCY_JSON_SCHEMA
from .types import SufficiencyConfig, SufficiencyVerdict

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.core.config.llm import LLMConfig

logger = logging.getLogger(__name__)

_FALLBACK_SUFFICIENT = SufficiencyVerdict(is_sufficient=True, confidence=0.0)


def _build_eval_model(llm_config: LLMConfig) -> BaseChatModel:
    """Create a lightweight LLM instance for sufficiency evaluation."""
    from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model

    return create_litellm_model(
        model=llm_config.model,
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        temperature=0.0,
        streaming=False,
        **(llm_config.model_kwargs or {}),
    )


def _truncate_snippets(snippets: str, max_chars: int) -> str:
    """Truncate snippets to fit within evaluation budget."""
    if len(snippets) <= max_chars:
        return snippets
    return snippets[:max_chars] + "\n\n[... truncated for evaluation ...]"


def _parse_verdict(raw_text: str, config: SufficiencyConfig) -> SufficiencyVerdict:
    """Parse LLM JSON output into a SufficiencyVerdict.

    Falls back to 'sufficient' on parse failure (fail-open to avoid blocking the agent).
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # skip ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("RSG: Failed to parse evaluator response as JSON, defaulting to sufficient")
        return _FALLBACK_SUFFICIENT

    confidence = float(data.get("confidence", 0.0))
    if confidence < config.confidence_threshold:
        logger.debug(
            "RSG: Evaluator confidence %.2f below threshold %.2f, discarding verdict",
            confidence, config.confidence_threshold,
        )
        return _FALLBACK_SUFFICIENT

    return SufficiencyVerdict(
        is_sufficient=bool(data.get("is_sufficient", True)),
        confidence=confidence,
        missing_aspects=tuple(data.get("missing_aspects", ())),
        suggested_queries=tuple(data.get("suggested_queries", ())),
        negative_constraint_violations=tuple(data.get("negative_constraint_violations", ())),
    )


async def evaluate_sufficiency(
    query: str,
    snippets: str,
    llm_config: LLMConfig,
    config: SufficiencyConfig | None = None,
) -> SufficiencyVerdict:
    """Evaluate whether retrieved snippets sufficiently answer a query.

    This function is designed to be called conditionally by retrieval tools
    when sufficiency evaluation is enabled. It uses a lightweight LLM call
    with JSON Schema enforcement for reliable structured output.

    Args:
        query: The user's original query.
        snippets: Formatted retrieval results (text content).
        llm_config: LLM configuration for the evaluation model.
        config: Evaluation configuration. Defaults to SufficiencyConfig() if None.

    Returns:
        SufficiencyVerdict with evaluation results.
        On any error, returns a fail-open verdict (is_sufficient=True, confidence=0.0).
    """
    config = config or SufficiencyConfig()

    if not config.enabled:
        return _FALLBACK_SUFFICIENT

    if not snippets or not snippets.strip():
        return SufficiencyVerdict(
            is_sufficient=False,
            confidence=1.0,
            missing_aspects=("No results retrieved.",),
            suggested_queries=(query,),
        )

    truncated_snippets = _truncate_snippets(snippets, config.max_snippets_for_eval)

    user_content = SUFFICIENCY_EVAL_USER_TEMPLATE.format(
        query=query,
        snippets=truncated_snippets,
    )

    messages = [
        SystemMessage(content=SUFFICIENCY_EVAL_SYSTEM),
        HumanMessage(content=user_content),
    ]

    try:
        model = _build_eval_model(llm_config)

        invoke_kwargs: dict[str, object] = {}
        invoke_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "sufficiency_evaluation",
                "strict": True,
                "schema": SUFFICIENCY_JSON_SCHEMA,
            },
        }

        response = await model.ainvoke(messages, **invoke_kwargs)
        raw_text = response.content if hasattr(response, "content") else str(response)

        return _parse_verdict(raw_text, config)

    except Exception:
        logger.warning("RSG: Evaluation failed, defaulting to sufficient (fail-open)", exc_info=True)
        return _FALLBACK_SUFFICIENT
