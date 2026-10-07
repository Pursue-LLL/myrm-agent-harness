"""Token Tax governor unifying thin prompt contracts, GC, and context auditing.

Quantifies the Token Tax imposed by harness overhead and intermediate tool outputs,
ensuring custom persona fidelity and transparent compound cost reduction.

[INPUT]
- runtime.context.transient_tool_output_gc::TransientToolOutputGCEngine (POS: Transient tool output garbage
  collection engine.)
- runtime.context.universal_thin_harness_types::ModelCapabilityTier, OperatingDisciplineMode,
  ThinPromptContract, TokenTaxAuditSnapshot (POS: Universal agent thin harness adaptive contract and Token
  Tax governor types.)
- runtime.context.universal_thin_prompt_generator::UniversalThinPromptGenerator (POS: Universal thin prompt
  generator for adaptive agent harnesses.)

[OUTPUT]
- TokenTaxGovernor: Manages adaptive harness prompt contracts, tool output GC, and Token Tax audits.

[POS]
Token Tax governor unifying thin prompt contracts, GC, and context auditing.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .transient_tool_output_gc import TransientToolOutputGCEngine
from .universal_thin_harness_types import (
    ModelCapabilityTier,
    OperatingDisciplineMode,
    ThinPromptContract,
    TokenTaxAuditSnapshot,
)
from .universal_thin_prompt_generator import UniversalThinPromptGenerator


class TokenTaxGovernor:
    """Manages adaptive harness prompt contracts, tool output GC, and Token Tax audits."""

    def __init__(
        self,
        prompt_generator: UniversalThinPromptGenerator | None = None,
        gc_engine: TransientToolOutputGCEngine | None = None,
        chars_per_token_ratio: float = 3.8,
    ) -> None:
        self._prompt_gen = prompt_generator or UniversalThinPromptGenerator(chars_per_token_ratio)
        self._gc_engine = gc_engine or TransientToolOutputGCEngine(
            chars_per_token_ratio=chars_per_token_ratio
        )
        self._chars_per_token_ratio = chars_per_token_ratio

    def estimate_tokens(self, text: str) -> int:
        """Estimates token count deterministically."""
        if not text.strip():
            return 0
        return max(1, math.ceil(len(text) / self._chars_per_token_ratio))

    def process_turn(
        self,
        mode: OperatingDisciplineMode,
        capability_tier: ModelCapabilityTier,
        custom_persona: str,
        messages: Sequence[dict[str, str]],
    ) -> tuple[ThinPromptContract, list[dict[str, str]], TokenTaxAuditSnapshot]:
        """Assembles thin prompt, runs GC dehydration, and yields transparent audit snapshot."""
        contract = self._prompt_gen.build_contract(
            mode=mode,
            capability_tier=capability_tier,
            custom_persona=custom_persona,
        )

        cleaned_messages, receipts = self._gc_engine.dehydrate_turn_history(messages)
        saved_tokens = sum(r.saved_tokens for r in receipts)

        audit_snapshot = self.audit_context(
            contract=contract,
            messages=cleaned_messages,
            cumulative_saved_tokens=saved_tokens,
        )

        return contract, cleaned_messages, audit_snapshot

    def audit_context(
        self,
        contract: ThinPromptContract,
        messages: Sequence[dict[str, str]],
        cumulative_saved_tokens: int = 0,
    ) -> TokenTaxAuditSnapshot:
        """Audits context distribution across harness, persona, tools, and history."""
        overhead_tokens = contract.estimated_overhead_tokens
        persona_tokens = self.estimate_tokens(contract.custom_persona_prompt)

        tool_tokens = 0
        history_tokens = 0

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            t_count = self.estimate_tokens(content)
            if role in ("tool", "tool_result", "observation"):
                tool_tokens += t_count
            else:
                history_tokens += t_count

        total_active = overhead_tokens + persona_tokens + tool_tokens + history_tokens
        tax_burden = overhead_tokens + tool_tokens
        tax_ratio = round(tax_burden / total_active, 4) if total_active > 0 else 0.0

        return TokenTaxAuditSnapshot(
            mode=contract.mode,
            harness_overhead_tokens=overhead_tokens,
            custom_persona_tokens=persona_tokens,
            tool_output_tokens=tool_tokens,
            conversation_history_tokens=history_tokens,
            total_active_tokens=total_active,
            cumulative_dehydrated_saved_tokens=cumulative_saved_tokens,
            effective_tax_ratio=tax_ratio,
        )
