"""Unified facade suite orchestrating prefix-caching aligned context layout and hidden reasoning token ledgers.

[INPUT]
- ContextBlockDescriptor: Structured tier-annotated prompt blocks.
- PrefixCachingLayoutConfig: Config governing ordering and pricing rules.
- HiddenReasoningTokensPenetrationAuditor: Penetration auditor for heterogeneous usages.
- MultiDimensionalSessionTokenLedger: Session-scoped token ledger.
- PrefixCachingAlignedLayoutEngine: Deterministic layout assembler.

[OUTPUT]
- PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite: Complete facade coordinating prompt assembly and token tracking.

[POS]
Top-level context management facade for Item 308.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .hidden_reasoning_tokens_penetration_auditor import (
    HiddenReasoningTokensPenetrationAuditor,
)
from .multi_dimensional_session_token_ledger import MultiDimensionalSessionTokenLedger
from .prefix_caching_aligned_layout_engine import PrefixCachingAlignedLayoutEngine
from .prefix_caching_types import (
    ContextBlockDescriptor,
    PrefixCachingLayoutConfig,
    TokenUsageBreakdown,
    TurnLedgerRecord,
)


class PrefixCachingAlignedContextLayoutAndHiddenReasoningTokenLedgerSuite:
    """Unified facade for prompt prefix-caching optimization and penetrating usage accounting."""

    def __init__(self, config: PrefixCachingLayoutConfig | None = None) -> None:
        self._config = config or PrefixCachingLayoutConfig()
        self._layout_engine = PrefixCachingAlignedLayoutEngine(self._config)
        self._auditor = HiddenReasoningTokensPenetrationAuditor()
        self._ledgers: dict[str, MultiDimensionalSessionTokenLedger] = {}

    @property
    def config(self) -> PrefixCachingLayoutConfig:
        """The configuration in effect."""
        return self._config

    def get_or_create_ledger(self, session_id: str) -> MultiDimensionalSessionTokenLedger:
        """Retrieve or initialize the token ledger for a given session."""
        if session_id not in self._ledgers:
            self._ledgers[session_id] = MultiDimensionalSessionTokenLedger(
                session_id=session_id,
                config=self._config,
            )
        return self._ledgers[session_id]

    def assemble_aligned_prompt(
        self,
        blocks: Sequence[ContextBlockDescriptor],
        separator: str = "\n\n",
    ) -> tuple[str, str]:
        """Assemble context blocks into a cache-friendly prompt and compute the Tier 1 stability hash.

        Returns:
            A tuple of (assembled_prompt_text, prefix_sha256_hash).
        """
        prompt = self._layout_engine.assemble_prompt(blocks, separator=separator)
        prefix_hash = self._layout_engine.compute_prefix_hash(blocks)
        return prompt, prefix_hash

    def audit_and_record_turn(
        self,
        session_id: str,
        turn_id: str,
        model_name: str,
        raw_usage: Mapping[str, object],
        timestamp: float | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> TurnLedgerRecord:
        """Audit raw provider usage and record the standardized breakdown into the session ledger."""
        ledger = self.get_or_create_ledger(session_id)
        breakdown = self._auditor.audit_raw_usage(raw_payload=raw_usage)
        return ledger.record_turn(
            turn_id=turn_id,
            model_name=model_name,
            usage=breakdown,
            timestamp=timestamp,
            metadata=metadata,
        )

    def get_session_aggregate(self, session_id: str) -> TokenUsageBreakdown:
        """Retrieve the cumulative token usage breakdown for a session."""
        ledger = self.get_or_create_ledger(session_id)
        return ledger.get_session_aggregate()

    def diagnose_session_health(self, session_id: str) -> Mapping[str, object]:
        """Expose an operational health report for a session's token consumption and caching."""
        ledger = self.get_or_create_ledger(session_id)
        return ledger.diagnose_ledger_health()

    def remove_session_ledger(self, session_id: str) -> bool:
        """Prune an inactive session ledger from memory."""
        return self._ledgers.pop(session_id, None) is not None
