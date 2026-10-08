"""Live correction orchestrator coordinating detection, localization, mutation, and acknowledgement.

[INPUT]
- utterance: str
- candidates: Sequence[TargetNodeCandidate]

[OUTPUT]
- Optional[CorrectionAckReceipt]: Generated receipt or None if no correction detected

[POS]
myrm_agent_harness.toolkits.memory.live_correction.orchestrator
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.live_correction.detector import (
    NaturalLanguageCorrectionDetector,
)
from myrm_agent_harness.toolkits.memory.live_correction.localizer import (
    CorrectionTargetLocalizer,
)
from myrm_agent_harness.toolkits.memory.live_correction.models import (
    CorrectionAckReceipt,
    CorrectionIntentKind,
    CorrectionSlot,
    LiveCorrectionMutationResult,
    MutationAction,
    TargetNodeCandidate,
)
from myrm_agent_harness.toolkits.memory.live_correction.mutator import (
    AtomicMemoryMutator,
    MutationSinkProtocol,
)


class LiveCorrectionOrchestrator:
    """End-to-end pipeline orchestrating live memory correction from conversational utterances."""

    def __init__(
        self,
        detector: NaturalLanguageCorrectionDetector | None = None,
        localizer: CorrectionTargetLocalizer | None = None,
        mutator: AtomicMemoryMutator | None = None,
        sink: MutationSinkProtocol | None = None,
    ) -> None:
        self.detector = detector or NaturalLanguageCorrectionDetector()
        self.localizer = localizer or CorrectionTargetLocalizer()
        self.mutator = mutator or AtomicMemoryMutator(sink=sink)

    def process_utterance(
        self,
        utterance: str,
        candidates: Sequence[TargetNodeCandidate] = (),
    ) -> CorrectionAckReceipt | None:
        """Process a conversational utterance, applying live correction if detected."""
        start_t = time.perf_counter()

        slot = self.detector.detect(utterance)
        if slot is None:
            return None

        target = self.localizer.localize(slot, candidates)
        mutation_result = self.mutator.mutate(slot, target)

        ack_message = self._format_ack_message(slot, target, mutation_result)
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        return CorrectionAckReceipt(
            success=True,
            ack_message=ack_message,
            intent=slot.intent,
            slot=slot,
            mutated_record=mutation_result,
            processing_ms=round(elapsed_ms, 2),
        )

    def _format_ack_message(
        self,
        slot: CorrectionSlot,
        target: TargetNodeCandidate | None,
        mutation: LiveCorrectionMutationResult,
    ) -> str:
        """Generate a natural, clear acknowledgement sentence in matching language."""
        is_zh = any("\u4e00" <= char <= "\u9fff" for char in slot.raw_utterance)

        if mutation.action == MutationAction.RETRACT:
            if is_zh:
                return f"已为您撤回并清除关于「{slot.negated_value or '该主题'}」的历史记忆。"
            return f"Retracted and cleared memory regarding '{slot.negated_value or 'this topic'}'."

        if slot.intent == CorrectionIntentKind.BEHAVIOR_RULE:
            if is_zh:
                return f"已记录并启用新规则：「{slot.corrected_value}」，后续交互将严格遵守。"
            return f"Recorded and applied new rule: '{slot.corrected_value}'. All subsequent turns will adhere to it."

        if slot.intent == CorrectionIntentKind.PREFERENCE_UPDATE:
            if is_zh:
                if slot.negated_value:
                    return f"已为您更正偏好：由「{slot.negated_value}」调整为「{slot.corrected_value}」，后续对话将以此为准。"
                return f"已为您更新偏好：「{slot.corrected_value}」，后续对话将以此为准。"
            if slot.negated_value:
                return f"Preference updated: switched from '{slot.negated_value}' to '{slot.corrected_value}'. Future interactions will strictly respect this."
            return f"Preference updated to '{slot.corrected_value}'. Future interactions will strictly respect this."

        # Default Fact Superseded / General
        if is_zh:
            if slot.negated_value:
                return f"已纠正事实认知：已更正为「{slot.corrected_value}」（原「{slot.negated_value}」已失效）。"
            return f"已纠正事实认知并保存为最新记录：「{slot.corrected_value}」。"

        if slot.negated_value:
            return f"Fact corrected to '{slot.corrected_value}' (previous assertion '{slot.negated_value}' marked superseded)."
        return f"Fact corrected and saved as latest record: '{slot.corrected_value}'."
