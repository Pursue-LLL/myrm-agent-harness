"""Unified suite for inline workspace deck, multi-model arbitrage, and persona switching.

[INPUT]
- arbitrage_types: All contracts and configuration.
- inline_deck_manager: InlineDeckManager.
- cost_performance_arbitrage_router: CostPerformanceArbitrageRouter.
- dual_persona_switcher: DualPersonaSwitcher.
- anti_downgrade_budget_guard: AntiDowngradeBudgetGuard.

[OUTPUT]
- WorkWithChatUnifiedWorkspaceDeckAndMultiModelCostArbitrageSuite: Unified facade
  orchestrating inline widgets, model arbitrage, dual-persona warmth, and budget safeguards.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.workspace_arbitrage
- Module: workspace_arbitrage_suite.py
"""

from typing import Dict, Mapping, Optional, Sequence, Tuple
from myrm_agent_harness.agent.context_management.workspace_arbitrage.anti_downgrade_budget_guard import (
    AntiDowngradeBudgetGuard,
)
from myrm_agent_harness.agent.context_management.workspace_arbitrage.arbitrage_types import (
    BudgetWatermarkStatus,
    CostSavingsRecord,
    DeckActionResult,
    DeckInteractionEvent,
    DeckWidgetSpec,
    ModelArbitrageTier,
    ModelFingerprintProfile,
    PersonaMode,
    RoutingDecision,
    WorkspaceArbitrageConfig,
)
from myrm_agent_harness.agent.context_management.workspace_arbitrage.cost_performance_arbitrage_router import (
    CostPerformanceArbitrageRouter,
)
from myrm_agent_harness.agent.context_management.workspace_arbitrage.dual_persona_switcher import (
    DualPersonaSwitcher,
)
from myrm_agent_harness.agent.context_management.workspace_arbitrage.inline_deck_manager import (
    InlineDeckManager,
)


class WorkWithChatUnifiedWorkspaceDeckAndMultiModelCostArbitrageSuite:
    """Master facade uniting inline work decks, cost arbitrage routing, persona, and budget guards."""

    def __init__(self, config: Optional[WorkspaceArbitrageConfig] = None) -> None:
        self._config = config or WorkspaceArbitrageConfig()
        self._deck_manager = InlineDeckManager()
        self._arbitrage_router = CostPerformanceArbitrageRouter(self._config)
        self._persona_switcher = DualPersonaSwitcher()
        self._budget_guard = AntiDowngradeBudgetGuard(self._config)

    @property
    def deck_manager(self) -> InlineDeckManager:
        """Access the inline deck manager."""
        return self._deck_manager

    @property
    def arbitrage_router(self) -> CostPerformanceArbitrageRouter:
        """Access the cost-performance arbitrage router."""
        return self._arbitrage_router

    @property
    def persona_switcher(self) -> DualPersonaSwitcher:
        """Access the dual-persona demeanor switcher."""
        return self._persona_switcher

    @property
    def budget_guard(self) -> AntiDowngradeBudgetGuard:
        """Access the anti-downgrade budget guard."""
        return self._budget_guard

    def register_widget(self, spec: DeckWidgetSpec) -> DeckWidgetSpec:
        """Registers a new interactive widget into the active chat session."""
        return self._deck_manager.register_widget(spec)

    def handle_widget_action(self, event: DeckInteractionEvent) -> DeckActionResult:
        """Dispatches an interactive event to the inline deck manager."""
        return self._deck_manager.handle_interaction(event)

    def prepare_turn_execution(
        self,
        session_id: str,
        prompt: str,
        base_system_prompt: str,
        forced_tier: Optional[ModelArbitrageTier] = None,
        persona_mode: Optional[PersonaMode] = None,
        warmth_level: float = 0.5,
    ) -> Tuple[RoutingDecision, str, Tuple[float, float], str]:
        """Prepares turn execution by computing routing, tailored system prompt, and context.

        Args:
            session_id: Current session identifier.
            prompt: User message prompt.
            base_system_prompt: Base system instructions.
            forced_tier: Optional user explicit tier override.
            persona_mode: Optional persona override for this turn.
            warmth_level: Warmth level between 0.0 and 1.0.

        Returns:
            Tuple of:
            - RoutingDecision (selected tier and model)
            - Modified system prompt with persona guidance
            - Recommended sampling parameters (temperature, top_p)
            - Inline deck context projection markdown block
        """
        # 1. Budget check first: if hard-fused, fallback to local model unconditionally
        watermark = self._budget_guard.get_watermark_status(session_id)
        if watermark.enforce_fallback_to_local:
            routing = RoutingDecision(
                selected_tier=ModelArbitrageTier.L1_FAST_LOCAL,
                target_model_name=self._config.local_fallback_model,
                estimated_input_tokens=max(50, len(prompt) // 4),
                complexity=self._arbitrage_router._analyzer.analyze(prompt),
                promoted_from_l1=False,
                decision_reason="Session hard budget limit reached; routed to local fallback.",
            )
        else:
            routing = self._arbitrage_router.route_prompt(
                prompt=prompt,
                session_id=session_id,
                forced_tier=forced_tier,
            )

        # 2. Modify system prompt with persona directive
        modified_prompt = self._persona_switcher.modify_system_prompt(
            base_prompt=base_system_prompt,
            mode=persona_mode,
            warmth_level=warmth_level,
        )

        # 3. Sampling params
        sampling_params = self._persona_switcher.recommend_generation_params(
            mode=persona_mode
        )

        # 4. Context projection from active inline widgets
        deck_context = self._deck_manager.render_context_summary()

        return routing, modified_prompt, sampling_params, deck_context

    def record_turn_outcome(
        self,
        session_id: str,
        decision: RoutingDecision,
        total_tokens: int,
        system_fingerprint: str = "",
        latency_ms: float = 0.0,
        is_truncated: bool = False,
    ) -> Tuple[CostSavingsRecord, ModelFingerprintProfile, BudgetWatermarkStatus]:
        """Records turn telemetry across cost savings, model fingerprinting, and budget tracking.

        Returns:
            Tuple of (CostSavingsRecord, ModelFingerprintProfile, BudgetWatermarkStatus).
        """
        # 1. Track cost savings
        savings_record = self._arbitrage_router.record_arbitrage_savings(
            session_id=session_id,
            total_tokens=total_tokens,
            actual_tier=decision.selected_tier,
        )

        # 2. Track provider fingerprint drift
        fingerprint_profile = self._budget_guard.record_model_call(
            model_name=decision.target_model_name,
            system_fingerprint=system_fingerprint,
            latency_ms=latency_ms,
            output_token_count=total_tokens,
            is_truncated=is_truncated,
        )

        # 3. Track spending against budget watermark
        watermark_status = self._budget_guard.track_spending(
            session_id=session_id,
            cost_usd=savings_record.l1_actual_cost_usd,
        )

        return savings_record, fingerprint_profile, watermark_status
