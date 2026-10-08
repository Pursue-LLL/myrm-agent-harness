# [INPUT]: AssembledContextPayload, ContextTierKind, FourTierContextConfig, JitHandle, JitRetrievalProtocol, KnowledgeSynthesisEngine, SynthesisInput, SynthesizedDirective, TriggerDomainKind, TriggeredContextRouter, TriggeredRule
# [OUTPUT]: FourTierContextRoutingAndSynthesisEngineSuite
# [POS]: agent/context_management/four_tier_routing/four_tier_context_suite.py

"""Comprehensive facade suite for the Four-Tier Context Engineering Architecture.

[INPUT]
- AssembledContextPayload, ContextTierKind, FourTierContextConfig, JitHandle, SynthesisInput,
  SynthesizedDirective, TriggerDomainKind, TriggeredRule: Domain contracts from four_tier_types.
- TriggeredContextRouter from triggered_context_router.
- JitRetrievalProtocol from jit_retrieval_protocol.
- KnowledgeSynthesisEngine from knowledge_synthesis_engine.

[OUTPUT]
- FourTierContextRoutingAndSynthesisEngineSuite: Central facade orchestrating deterministic baselines,
  dynamic domain rule routing, JIT reference catalogs, and multi-source knowledge synthesis.

[POS]
Top-level entrypoint providing Anthropic Context Engineering inspired four-tier context assembly.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .four_tier_types import (
    AssembledContextPayload,
    ContextTierKind,
    FourTierContextConfig,
    JitHandle,
    SynthesisInput,
    SynthesizedDirective,
    TriggerDomainKind,
    TriggeredRule,
)
from .jit_retrieval_protocol import JitRetrievalProtocol
from .knowledge_synthesis_engine import KnowledgeSynthesisEngine
from .triggered_context_router import TriggeredContextRouter


class FourTierContextRoutingAndSynthesisEngineSuite:
    """Orchestrates four-tier context assembly across deterministic, triggered, JIT, and synthesis layers."""

    def __init__(
        self,
        config: FourTierContextConfig | None = None,
        deterministic_baseline: str = "",
    ) -> None:
        self._config = config or FourTierContextConfig()
        self._deterministic_baseline = deterministic_baseline
        self._router = TriggeredContextRouter(config=self._config)
        self._jit = JitRetrievalProtocol(config=self._config)
        self._synthesis = KnowledgeSynthesisEngine(config=self._config)

    @property
    def config(self) -> FourTierContextConfig:
        return self._config

    @property
    def router(self) -> TriggeredContextRouter:
        return self._router

    @property
    def jit(self) -> JitRetrievalProtocol:
        return self._jit

    @property
    def synthesis(self) -> KnowledgeSynthesisEngine:
        return self._synthesis

    def set_deterministic_baseline(self, baseline_text: str) -> None:
        """Set or update Tier 1 deterministic project baseline."""
        self._deterministic_baseline = baseline_text.strip()

    def register_domain_rule(self, rule: TriggeredRule) -> None:
        """Register a custom Tier 2 triggered rule."""
        self._router.register_rule(rule)

    def register_jit_handle(self, handle: JitHandle) -> None:
        """Register a Tier 3 JIT pointer handle."""
        self._jit.register_handle(handle)

    def hydrate_jit_handle(self, handle_id: str, content: str | None = None) -> Optional[JitHandle]:
        """Hydrate a Tier 3 JIT handle on demand."""
        return self._jit.hydrate_handle(handle_id, content)

    def synthesize_knowledge(self, input_data: SynthesisInput) -> SynthesizedDirective:
        """Execute Tier 4 multi-source pre-prompt synthesis."""
        return self._synthesis.synthesize(input_data)

    def assemble_context(
        self,
        target_paths: Sequence[str] = (),
        intent_text: str = "",
        synthesis_inputs: Sequence[SynthesisInput] = (),
        include_jit_catalog: bool = True,
    ) -> AssembledContextPayload:
        """Assemble complete context across all 4 tiers with explicit boundaries and accounting."""
        sections: List[str] = []
        tier_counts: Dict[ContextTierKind, int] = {
            ContextTierKind.DETERMINISTIC: 0,
            ContextTierKind.TRIGGERED: 0,
            ContextTierKind.JIT_RETRIEVAL: 0,
            ContextTierKind.SYNTHESIS: 0,
        }
        active_domains: List[TriggerDomainKind] = []

        # Tier 1: Deterministic Baseline
        if self._deterministic_baseline:
            tier_counts[ContextTierKind.DETERMINISTIC] = 1
            sections.append(
                f"## [TIER 1: DETERMINISTIC BASELINE]\n{self._deterministic_baseline}"
            )

        # Tier 2: Triggered Domain Rules
        routed_rules = self._router.route_rules(target_paths=target_paths, intent_text=intent_text)
        if routed_rules:
            tier_counts[ContextTierKind.TRIGGERED] = len(routed_rules)
            active_domains.extend([r.domain for r in routed_rules])
            rule_texts = [f"- **[{r.domain.value}]**: {r.content}" for r in routed_rules]
            sections.append(
                f"## [TIER 2: TRIGGERED DOMAIN DISCIPLINE]\n" + "\n".join(rule_texts)
            )

        # Tier 3: JIT Retrieval Handles
        if include_jit_catalog and self._jit.total_handles() > 0:
            catalog_text = self._jit.render_catalog()
            if catalog_text:
                tier_counts[ContextTierKind.JIT_RETRIEVAL] = self._jit.total_handles()
                sections.append(
                    f"## [TIER 3: JIT REFERENCE HANDLES (ON-DEMAND)]\n{catalog_text}"
                )

        # Tier 4: Knowledge Synthesis
        synthesized_blocks: List[str] = []
        for s_input in synthesis_inputs:
            directive = self._synthesis.synthesize(s_input)
            synthesized_blocks.append(self._synthesis.format_directive(directive))

        if synthesized_blocks:
            tier_counts[ContextTierKind.SYNTHESIS] = len(synthesized_blocks)
            sections.append(
                f"## [TIER 4: MULTI-SOURCE KNOWLEDGE SYNTHESIS]\n" + "\n\n".join(synthesized_blocks)
            )

        assembled_text = "\n\n".join(sections)
        total_chars = len(assembled_text)
        estimated_tokens = total_chars // 4

        return AssembledContextPayload(
            assembled_text=assembled_text,
            tier_counts=tier_counts,
            total_characters=total_chars,
            estimated_tokens=estimated_tokens,
            active_domains=list(dict.fromkeys(active_domains)),
        )

    @classmethod
    def create(
        cls,
        deterministic_baseline: str = "",
        max_triggered_rules: int = 4,
    ) -> FourTierContextRoutingAndSynthesisEngineSuite:
        """Factory constructor for standard 4-tier configurations."""
        config = FourTierContextConfig(max_triggered_rules=max_triggered_rules)
        return cls(config=config, deterministic_baseline=deterministic_baseline)
