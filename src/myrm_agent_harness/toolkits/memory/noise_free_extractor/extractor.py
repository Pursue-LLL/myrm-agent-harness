"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/extractor.py
[INPUT]: Raw multi-turn conversation turns, candidate memory facts, and purge commands.
[OUTPUT]: NoiseFreeAsyncMemoryExtractor orchestrating noise stripping, PII gates, and epoch fences.

Reference: Anthropic Commerce Agents (commerce_common/memory.py).
Combines:
1. Tool receipt physical stripping (prevents catalog/execution noise from entering memory prompts);
2. PII safety gateway (prevents credit cards, IBANs, and credentials from persisting);
3. Monotonic purge generation epoch fencing (prevents background async writes from resurrecting purged facts).
"""

from collections.abc import Sequence
from threading import Lock

from .epoch_manager import PurgeGenerationEpochManager
from .noise_filter import ToolNoiseFilter
from .pii_gateway import PIISafetyGateway
from .types import (
    ConversationTurn,
    ExtractedFactCandidate,
    NoiseFreeConfig,
    PIIViolationDetail,
    PurgeEpochStatus,
    ToolStrippedMessage,
)


class NoiseFreeAsyncMemoryExtractor:
    """Orchestrates async clean memory extraction with PII screening and monotonic epoch fencing."""

    def __init__(
        self,
        config: NoiseFreeConfig | None = None,
        epoch_manager: PurgeGenerationEpochManager | None = None,
    ) -> None:
        self.config = config or NoiseFreeConfig()
        self.noise_filter = ToolNoiseFilter()
        self.pii_gateway = PIISafetyGateway(
            mask_instead_of_reject=self.config.mask_pii_instead_of_reject
        )
        self.epoch_manager = epoch_manager or PurgeGenerationEpochManager()
        self._store_lock = Lock()
        # user_id -> list of committed ExtractedFactCandidate
        self._facts_store: dict[str, list[ExtractedFactCandidate]] = {}

    def prepare_clean_context(
        self, user_id: str, turns: Sequence[ConversationTurn]
    ) -> tuple[str, int, int]:
        """Strip tool noise and record the observed generation before launching extraction.

        Returns:
            (clean_transcript, observed_generation, tokens_saved)
        """
        observed_generation = self.epoch_manager.start_extraction_task(user_id)

        if self.config.strip_tool_receipts:
            _, tokens_saved = self.noise_filter.process_dialogue(turns)
            clean_transcript = self.noise_filter.render_clean_transcript(turns)
        else:
            lines: list[str] = [f"{t.role}: {t.content}" for t in turns]
            clean_transcript = "\n\n".join(lines)
            tokens_saved = 0

        return clean_transcript, observed_generation, tokens_saved

    def process_and_filter_dialogue(
        self, turns: Sequence[ConversationTurn]
    ) -> tuple[list[ToolStrippedMessage], int]:
        """Directly return stripped structured messages and token savings count."""
        return self.noise_filter.process_dialogue(turns)

    def commit_extracted_fact(
        self, user_id: str, candidate: ExtractedFactCandidate
    ) -> tuple[bool, str, PIIViolationDetail | None]:
        """Validate candidate fact against monotonic epoch fence and PII gateway.

        Returns:
            (is_admitted, reason_or_status, primary_violation_if_any)
        """
        try:
            # 1. Monotonic epoch generation validation (prevents ghost write after user purge)
            is_valid_epoch = self.epoch_manager.validate_and_fence_write(
                user_id=user_id,
                observed_generation=candidate.generation_observed,
            )
            if not is_valid_epoch:
                return (
                    False,
                    f"Stale generation write dropped: observed={candidate.generation_observed} < current",
                    None,
                )

            # 2. PII Screening Gateway
            if self.config.enforce_pii_gate:
                pii_result = self.pii_gateway.inspect(candidate.fact_text)
                if not pii_result.is_clean:
                    self.epoch_manager.record_pii_violation(user_id)
                    primary_violation = (
                        pii_result.violations[0] if pii_result.violations else None
                    )
                    return (
                        False,
                        f"Blocked by PII safety gateway: {primary_violation.rule_name if primary_violation else 'violation'}",
                        primary_violation,
                    )
                # If mask mode is enabled, update candidate text with sanitized version
                if self.config.mask_pii_instead_of_reject:
                    candidate.fact_text = pii_result.sanitized_text

            # 3. Double-check confidence threshold
            if candidate.confidence < self.config.min_confidence_threshold:
                return (
                    False,
                    f"Confidence {candidate.confidence:.2f} below threshold {self.config.min_confidence_threshold:.2f}",
                    None,
                )

            # 4. Commit to persistence store
            with self._store_lock:
                facts = self._facts_store.setdefault(user_id, [])
                facts.append(candidate)

            return True, "Fact successfully validated and committed", None

        finally:
            self.epoch_manager.finish_extraction_task(user_id)

    def purge_user_memory(self, user_id: str) -> int:
        """Atomically clear user's stored facts and bump purge generation.

        Returns the new advanced generation epoch index.
        """
        with self._store_lock:
            self._facts_store[user_id] = []
        return self.epoch_manager.bump_generation_on_purge(user_id)

    def get_user_facts(self, user_id: str) -> list[ExtractedFactCandidate]:
        """Retrieve current committed facts for user."""
        with self._store_lock:
            return list(self._facts_store.get(user_id, []))

    def get_epoch_status(self, user_id: str) -> PurgeEpochStatus:
        """Retrieve epoch fence health and statistics."""
        with self._store_lock:
            facts_count = len(self._facts_store.get(user_id, []))
        return self.epoch_manager.get_status(user_id, stored_facts_count=facts_count)
