"""Thinking parameter normalizer translating unified budget modes into vendor-specific API wire parameters.

Supports Anthropic thinking type disabled, DeepSeek chat fallback route,
and OpenAI reasoning_effort overrides to guarantee zero reasoning token overhead on mechanical tasks.

[INPUT]
- agent.context_management.zero_thinking_route.zero_thinking_types::ModelProviderKind,
  ProviderThinkingPayload, ThinkingBudgetMode (POS: Data contracts and type definitions for zero thinking
  budget direct routing and cost decoupling.)

[OUTPUT]
- ThinkingParameterNormalizer: Normalizes cross-vendor thinking budget parameters across Anthropic, DeepSeek,
  and OpenAI.

[POS]
Thinking parameter normalizer translating unified budget modes into vendor-specific API wire parameters.
"""

from __future__ import annotations

from .zero_thinking_types import (
    ModelProviderKind,
    ProviderThinkingPayload,
    ThinkingBudgetMode,
)


class ThinkingParameterNormalizer:
    """Normalizes cross-vendor thinking budget parameters across Anthropic, DeepSeek, and OpenAI."""

    @staticmethod
    def detect_provider(model_id: str) -> ModelProviderKind:
        """Heuristically identify the underlying provider family from model name."""
        lower = model_id.lower()
        if "claude" in lower or "anthropic" in lower:
            return ModelProviderKind.ANTHROPIC
        if "deepseek" in lower or "r1" in lower:
            return ModelProviderKind.DEEPSEEK
        if "o1" in lower or "o3" in lower or "openai" in lower or "gpt" in lower:
            return ModelProviderKind.OPENAI
        return ModelProviderKind.GENERIC

    def normalize(
        self,
        model_id: str,
        mode: ThinkingBudgetMode = ThinkingBudgetMode.AUTO,
        custom_budget: int | None = None,
    ) -> ProviderThinkingPayload:
        """Convert a unified ThinkingBudgetMode into raw wire parameters for the specified model."""
        provider = self.detect_provider(model_id)

        if provider == ModelProviderKind.ANTHROPIC:
            return self._normalize_anthropic(model_id, mode, custom_budget)
        if provider == ModelProviderKind.DEEPSEEK:
            return self._normalize_deepseek(model_id, mode)
        if provider == ModelProviderKind.OPENAI:
            return self._normalize_openai(model_id, mode)

        return self._normalize_generic(model_id, mode)

    def _normalize_anthropic(
        self,
        model_id: str,
        mode: ThinkingBudgetMode,
        custom_budget: int | None,
    ) -> ProviderThinkingPayload:
        """Map Anthropic Claude 3.7 extended thinking parameter."""
        if mode == ThinkingBudgetMode.ZERO_DIRECT:
            return ProviderThinkingPayload(
                provider=ModelProviderKind.ANTHROPIC,
                mode=mode,
                budget_tokens=0,
                extra_body_params={"thinking": {"type": "disabled"}},
                is_thinking_disabled=True,
                explanation="Anthropic thinking disabled completely (MAX_THINKING_TOKENS=0 equivalent).",
            )

        budget_map = {
            ThinkingBudgetMode.LOW: 1024,
            ThinkingBudgetMode.MEDIUM: 4096,
            ThinkingBudgetMode.HIGH: 16384,
            ThinkingBudgetMode.AUTO: 2048,
        }
        tokens = custom_budget or budget_map.get(mode, 2048)
        return ProviderThinkingPayload(
            provider=ModelProviderKind.ANTHROPIC,
            mode=mode,
            budget_tokens=tokens,
            extra_body_params={"thinking": {"type": "enabled", "budget_tokens": tokens}},
            is_thinking_disabled=False,
            explanation=f"Anthropic thinking enabled with budget of {tokens} tokens.",
        )

    def _normalize_deepseek(
        self,
        model_id: str,
        mode: ThinkingBudgetMode,
    ) -> ProviderThinkingPayload:
        """Map DeepSeek R1 reasoning parameters or route to V3 chat on zero thinking."""
        if mode == ThinkingBudgetMode.ZERO_DIRECT:
            # Route to standard non-reasoning model (deepseek-chat) for instant generation
            model_override = "deepseek-chat" if "reasoner" in model_id.lower() or "r1" in model_id.lower() else None
            return ProviderThinkingPayload(
                provider=ModelProviderKind.DEEPSEEK,
                mode=mode,
                budget_tokens=0,
                extra_body_params={},
                is_thinking_disabled=True,
                routed_model_override=model_override,
                explanation="Routed to fast-path DeepSeek-Chat to eliminate R1 reasoning overhead.",
            )

        return ProviderThinkingPayload(
            provider=ModelProviderKind.DEEPSEEK,
            mode=mode,
            budget_tokens=4096 if mode in (ThinkingBudgetMode.MEDIUM, ThinkingBudgetMode.HIGH) else 1024,
            extra_body_params={},
            is_thinking_disabled=False,
            explanation="Native DeepSeek reasoning mode active.",
        )

    def _normalize_openai(
        self,
        model_id: str,
        mode: ThinkingBudgetMode,
    ) -> ProviderThinkingPayload:
        """Map OpenAI o-series reasoning_effort parameters."""
        if mode == ThinkingBudgetMode.ZERO_DIRECT:
            # Fall back to gpt-4o or set lowest reasoning effort
            override = "gpt-4o" if model_id.startswith(("o1", "o3")) else None
            return ProviderThinkingPayload(
                provider=ModelProviderKind.OPENAI,
                mode=mode,
                budget_tokens=0,
                extra_body_params={"reasoning_effort": "low"} if not override else {},
                is_thinking_disabled=True,
                routed_model_override=override,
                explanation="Zero-thinking direct routing applied (swapped to direct model or minimal effort).",
            )

        effort_map = {
            ThinkingBudgetMode.LOW: "low",
            ThinkingBudgetMode.MEDIUM: "medium",
            ThinkingBudgetMode.HIGH: "high",
            ThinkingBudgetMode.AUTO: "medium",
        }
        effort = effort_map.get(mode, "medium")
        return ProviderThinkingPayload(
            provider=ModelProviderKind.OPENAI,
            mode=mode,
            budget_tokens=2048,
            extra_body_params={"reasoning_effort": effort},
            is_thinking_disabled=False,
            explanation=f"OpenAI reasoning effort set to '{effort}'.",
        )

    def _normalize_generic(
        self,
        model_id: str,
        mode: ThinkingBudgetMode,
    ) -> ProviderThinkingPayload:
        """Fallback for generic or unclassified models."""
        return ProviderThinkingPayload(
            provider=ModelProviderKind.GENERIC,
            mode=mode,
            budget_tokens=0 if mode == ThinkingBudgetMode.ZERO_DIRECT else 2048,
            extra_body_params={},
            is_thinking_disabled=(mode == ThinkingBudgetMode.ZERO_DIRECT),
            explanation="Generic provider parameters normalized.",
        )
