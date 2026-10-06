# [POS] src/myrm_agent_harness/toolkits/memory/persona_router/router.py
# [INPUT] collections.abc.Sequence, typing, .types, .gate
# [OUTPUT] AntiPollutionContextRouter

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.persona_router.gate import (
    StyleSuppressionGate,
)
from myrm_agent_harness.toolkits.memory.persona_router.types import (
    PersonaFacet,
    PersonaRoutingDecision,
    TaskIntentCategory,
)

_FACET_DIRECTIVE_PATTERN = re.compile(
    r"/about-me:([a-zA-Z0-9_\-]+)", re.IGNORECASE
)


class AntiPollutionContextRouter:
    """Dynamic context router injecting persona facets strictly on demand and suppressing context pollution."""

    def __init__(self, gate: StyleSuppressionGate | None = None) -> None:
        self._gate = gate or StyleSuppressionGate()

    def route(
        self,
        query: str,
        facets: Sequence[PersonaFacet],
        explicit_facet_id: str | None = None,
    ) -> PersonaRoutingDecision:
        """Route user query against persona facets, enforcing zero-token pollution on technical tasks."""
        should_suppress, category, reason = self._gate.evaluate_intent(query)
        total_potential_tokens = sum(f.estimated_tokens for f in facets)

        # Detect explicit inline directive (e.g. /about-me:executive)
        inline_match = _FACET_DIRECTIVE_PATTERN.search(query)
        target_facet_id = explicit_facet_id
        if inline_match:
            target_facet_id = inline_match.group(1).lower()
            should_suppress = False
            category = TaskIntentCategory.CREATIVE_COMMUNICATION
            reason = (
                f"Explicit inline directive '/about-me:{target_facet_id}' forced persona activation."
            )

        # If suppressed, return clean empty injection
        if should_suppress or not facets:
            return PersonaRoutingDecision(
                is_suppressed=True,
                intent_category=category,
                active_facets=(),
                injected_content="",
                tokens_saved_estimate=total_potential_tokens,
                decision_reason=reason,
            )

        # Select matching facet
        chosen_facet: PersonaFacet | None = None
        if target_facet_id:
            for f in facets:
                if f.facet_id.lower() == target_facet_id:
                    chosen_facet = f
                    break

        if chosen_facet is None:
            # Fall back to matching target intents or default
            for f in facets:
                if category.value in f.target_intents or "creative" in f.target_intents:
                    chosen_facet = f
                    break
            if chosen_facet is None:
                for f in facets:
                    if f.is_default:
                        chosen_facet = f
                        break
            if chosen_facet is None and facets:
                chosen_facet = facets[0]

        if chosen_facet is None:
            return PersonaRoutingDecision(
                is_suppressed=True,
                intent_category=category,
                active_facets=(),
                injected_content="",
                tokens_saved_estimate=total_potential_tokens,
                decision_reason="No valid persona facet could be resolved.",
            )

        # Assemble compact on-demand persona prompt block
        lines = [
            f"【按需风格画像 · {chosen_facet.name}】",
            f"- 行文语气与沟通要求: {chosen_facet.tone_guidance}",
        ]
        if chosen_facet.sample_excerpts:
            lines.append("- 优质范例摘录:")
            for sample in chosen_facet.sample_excerpts[:2]:
                lines.append(f"  * \"{sample}\"")

        injected_block = "\n".join(lines)
        tokens_saved = max(
            0, total_potential_tokens - chosen_facet.estimated_tokens
        )

        return PersonaRoutingDecision(
            is_suppressed=False,
            intent_category=category,
            active_facets=(chosen_facet.facet_id,),
            injected_content=injected_block,
            tokens_saved_estimate=tokens_saved,
            decision_reason=(
                f"Activated persona facet '{chosen_facet.facet_id}' based on intent '{category.value}'."
            ),
        )
