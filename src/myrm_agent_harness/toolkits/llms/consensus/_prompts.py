"""Aggregator prompt construction for consensus (MoA).

[INPUT]
- .types::ReferenceResponse (POS: successful reference answers to synthesise)

[OUTPUT]
- AGGREGATOR_SYSTEM: system instruction steering the synthesis
- build_aggregation_messages(): compose the aggregator chat prompt

[POS]
Stateless aggregation-prompt builder for the consensus engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.llms.consensus.types import ReferenceResponse

AGGREGATOR_SYSTEM = (
    "You have been provided with a set of responses from various models "
    "to the latest user query. Your task is to synthesise these responses "
    "into a single, high-quality response. Critically evaluate the "
    "information provided — some of it may be biased or incorrect. "
    "Offer a refined, accurate, and comprehensive reply. "
    "Do NOT simply repeat the given answers.\n\n"
    "Responses from models:"
)


def build_aggregation_messages(
    query: str,
    successful: list[ReferenceResponse],
    system_prompt: str | None = None,
) -> list[SystemMessage | HumanMessage]:
    """Compose the aggregator prompt from successful reference responses.

    ``system_prompt`` is the agent persona/instructions the reference models
    already honoured. It is prepended so the synthesised answer — streamed
    straight to the user as the final reply — stays faithful to the configured
    persona, language and format. Ordering preserves a cacheable static prefix:
    ``persona`` and ``AGGREGATOR_SYSTEM`` are stable across a given agent's
    calls, while the per-request reference answers follow and remain dynamic.
    """
    numbered = "\n".join(
        f"{i + 1}. [{r.model}]: {r.content}" for i, r in enumerate(successful)
    )
    base = AGGREGATOR_SYSTEM
    if system_prompt:
        base = f"{system_prompt}\n\n{AGGREGATOR_SYSTEM}"
    return [
        SystemMessage(content=f"{base}\n\n{numbered}"),
        HumanMessage(content=query),
    ]
