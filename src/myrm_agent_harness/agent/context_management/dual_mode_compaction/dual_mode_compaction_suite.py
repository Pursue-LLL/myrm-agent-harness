"""Main suite orchestrating proactive watermark compaction and reactive provider 400 self-healing.

[INPUT]
- agent.context_management.dual_mode_compaction.dual_mode_compaction_types::CompactableMessage,
  CompactionExecutionResult, CompactionTriggerKind, ContextWindowBudgetConfig, ProviderOverflowKind,
  SelfHealingAuditReceipt (POS: Types and schemas for proactive watermark compaction and reactive 400
  self-healing.)
- agent.context_management.dual_mode_compaction.overflow_detector::ProviderOverflowDetector (POS: Precision
  detector for provider 400 Bad Request and context window overflow errors.)

[OUTPUT]
- DualModeCompactionAndOverflowSelfHealingSuite: Orchestrates proactive context watermark compaction and
  provider 400 self-healing retries.

[POS]
Main suite orchestrating proactive watermark compaction and reactive provider 400 self-healing.
"""

from __future__ import annotations

import hashlib
from typing import Callable, List, Optional, Tuple

from .dual_mode_compaction_types import (
    CompactableMessage,
    CompactionExecutionResult,
    CompactionTriggerKind,
    ContextWindowBudgetConfig,
    ProviderOverflowKind,
    SelfHealingAuditReceipt,
)
from .overflow_detector import ProviderOverflowDetector


class DualModeCompactionAndOverflowSelfHealingSuite:
    """Orchestrates proactive context watermark compaction and provider 400 self-healing retries."""

    def __init__(
        self,
        session_id: str,
        config: Optional[ContextWindowBudgetConfig] = None,
    ) -> None:
        self._session_id = session_id
        self._config = config or ContextWindowBudgetConfig()
        self._audit_receipts: List[SelfHealingAuditReceipt] = []

    @property
    def session_id(self) -> str:
        """Return session ID."""
        return self._session_id

    @property
    def config(self) -> ContextWindowBudgetConfig:
        """Return current context budget configuration."""
        return self._config

    def estimate_total_tokens(self, messages: List[CompactableMessage]) -> int:
        """Sum estimated tokens across message list."""
        return sum(m.estimated_tokens for m in messages)

    def should_proactively_compact(self, messages: List[CompactableMessage]) -> bool:
        """Check if message tokens exceed active proactive watermark threshold."""
        total_tokens = self.estimate_total_tokens(messages)
        watermark = int(self._config.context_window_tokens * self._config.proactive_threshold_ratio)
        return total_tokens >= watermark

    def compact_context(
        self,
        messages: List[CompactableMessage],
        trigger_kind: CompactionTriggerKind = CompactionTriggerKind.PROACTIVE_WATERMARK,
    ) -> Tuple[List[CompactableMessage], CompactionExecutionResult]:
        """Compact messages folding oldest unpinned entries while preserving all pinned invariants."""
        original_tokens = self.estimate_total_tokens(messages)

        pinned_messages: List[CompactableMessage] = []
        compressible_messages: List[CompactableMessage] = []

        for msg in messages:
            if msg.is_pinned or msg.is_system_invariant:
                pinned_messages.append(msg)
            else:
                compressible_messages.append(msg)

        if len(compressible_messages) <= 2:
            # Cannot compact further
            result = CompactionExecutionResult(
                trigger_kind=trigger_kind,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                tokens_saved=0,
                retained_messages_count=len(messages),
                compacted_summary="",
                preserved_pinned_count=len(pinned_messages),
            )
            return list(messages), result

        # Determine cutoff based on trigger kind
        cut_ratio = (
            self._config.emergency_trim_ratio
            if trigger_kind == CompactionTriggerKind.REACTIVE_400_SELF_HEAL
            else 0.5
        )
        fold_count = max(1, int(len(compressible_messages) * cut_ratio))

        folded_slice = compressible_messages[:fold_count]
        retained_slice = compressible_messages[fold_count:]

        folded_texts = [f"{m.role}: {m.content[:80]}" for m in folded_slice]
        summary_content = (
            f"<compacted_context trigger='{trigger_kind.value}'>\n"
            f"Folded {len(folded_slice)} historical turns: "
            + "; ".join(folded_texts)
            + "\n</compacted_context>"
        )
        summary_tokens = max(20, len(summary_content) // 4)

        summary_message = CompactableMessage(
            message_id=f"compaction_{len(folded_slice)}_turns",
            role="system",
            content=summary_content,
            estimated_tokens=summary_tokens,
            is_pinned=False,
            is_system_invariant=False,
        )

        compacted_messages: List[CompactableMessage] = []
        compacted_messages.extend(pinned_messages)
        compacted_messages.append(summary_message)
        compacted_messages.extend(retained_slice)

        new_total_tokens = self.estimate_total_tokens(compacted_messages)
        tokens_saved = max(0, original_tokens - new_total_tokens)

        result = CompactionExecutionResult(
            trigger_kind=trigger_kind,
            original_tokens=original_tokens,
            compacted_tokens=new_total_tokens,
            tokens_saved=tokens_saved,
            retained_messages_count=len(compacted_messages),
            compacted_summary=summary_content,
            preserved_pinned_count=len(pinned_messages),
        )

        return compacted_messages, result

    def execute_with_overflow_self_healing(
        self,
        messages: List[CompactableMessage],
        llm_call: Callable[[List[CompactableMessage]], str],
    ) -> Tuple[str, List[CompactableMessage]]:
        """Execute LLM call with transparent in-place self-healing if provider 400 overflow occurs."""
        working_messages = list(messages)
        retries = 0

        while True:
            try:
                # 1. Proactive watermark pass before invocation
                if self.should_proactively_compact(working_messages):
                    working_messages, _ = self.compact_context(
                        working_messages,
                        trigger_kind=CompactionTriggerKind.PROACTIVE_WATERMARK,
                    )

                # 2. Invoke LLM
                response = llm_call(working_messages)
                return response, working_messages

            except Exception as exc:
                overflow_kind, error_text = ProviderOverflowDetector.classify_overflow(exc)
                if overflow_kind is None:
                    # Non-overflow error, propagate directly
                    raise

                retries += 1
                tokens_before = self.estimate_total_tokens(working_messages)

                if retries > self._config.max_self_healing_retries:
                    # Exhausted self-healing budget, record failure receipt and re-raise
                    audit_hash = hashlib.sha256(
                        f"{self._session_id}:{retries}:{tokens_before}:fail".encode("utf-8")
                    ).hexdigest()[:16]
                    self._audit_receipts.append(
                        SelfHealingAuditReceipt(
                            session_id=self._session_id,
                            retry_attempt=retries,
                            detected_overflow_kind=overflow_kind,
                            original_error_message=error_text,
                            tokens_before_retry=tokens_before,
                            tokens_after_retry=tokens_before,
                            recovered_successfully=False,
                            audit_hash=audit_hash,
                        )
                    )
                    raise

                # 3. Emergency reactive deep compaction
                working_messages, _ = self.compact_context(
                    working_messages,
                    trigger_kind=CompactionTriggerKind.REACTIVE_400_SELF_HEAL,
                )
                tokens_after = self.estimate_total_tokens(working_messages)

                # 4. Record successful self-healing attempt receipt
                audit_hash = hashlib.sha256(
                    f"{self._session_id}:{retries}:{tokens_before}:{tokens_after}:ok".encode("utf-8")
                ).hexdigest()[:16]
                self._audit_receipts.append(
                    SelfHealingAuditReceipt(
                        session_id=self._session_id,
                        retry_attempt=retries,
                        detected_overflow_kind=overflow_kind,
                        original_error_message=error_text,
                        tokens_before_retry=tokens_before,
                        tokens_after_retry=tokens_after,
                        recovered_successfully=True,
                        audit_hash=audit_hash,
                    )
                )

    def get_audit_receipts(self) -> List[SelfHealingAuditReceipt]:
        """Return list of recorded self-healing audit receipts."""
        return list(self._audit_receipts)
