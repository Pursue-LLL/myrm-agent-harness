"""Provisional title retry gate preventing dirty database writes and orchestrating self-healing.

[INPUT]
- title_recovery_types: TitleRecoveryConfig, TitleRecoveryState,
  TitleRecoveryVerdict, TitleValidationResult.
- invalid_title_taxonomy: InvalidTitleTaxonomy.

[OUTPUT]
- ProvisionalTitleRetryGate: Stateful gate coordinating title validation,
  provisional retry delay, and capped deterministic fallback.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.title_recovery
- Module: provisional_title_retry_gate.py
"""

import re
from typing import Dict, Optional, Tuple

from myrm_agent_harness.agent.context_management.title_recovery.invalid_title_taxonomy import (
    InvalidTitleTaxonomy,
)
from myrm_agent_harness.agent.context_management.title_recovery.title_recovery_types import (
    TitleRecoveryConfig,
    TitleRecoveryState,
    TitleRecoveryVerdict,
    TitleValidationResult,
)


class ProvisionalTitleRetryGate:
    """Controls database persistence of generated titles with bounded self-healing retries."""

    def __init__(self, config: TitleRecoveryConfig) -> None:
        self._config = config
        self._taxonomy = InvalidTitleTaxonomy(config)
        self._session_states: Dict[str, TitleRecoveryState] = {}

    @property
    def config(self) -> TitleRecoveryConfig:
        """Returns the active configuration."""
        return self._config

    def evaluate_title_candidate(
        self,
        session_id: str,
        raw_candidate: str,
        fallback_content: str,
    ) -> Tuple[TitleRecoveryVerdict, str, TitleValidationResult]:
        """Evaluates a raw LLM title candidate and determines whether to accept, retry, or fallback.

        Args:
            session_id: Unique conversation identifier.
            raw_candidate: Raw candidate string from title generation model.
            fallback_content: Dialogue snippet used for deterministic fallback extraction.

        Returns:
            Tuple of (TitleRecoveryVerdict, effective_title, TitleValidationResult).
        """
        state = self._get_or_create_state(session_id)

        # 1. Already finalized session keeps its immutable title
        if state.is_finalized:
            validation = self._taxonomy.validate_and_cleanse(state.current_title)
            return TitleRecoveryVerdict.ACCEPTED_CLEAN, state.current_title, validation

        validation = self._taxonomy.validate_and_cleanse(raw_candidate)

        # 2. Valid and clean title -> Accept and finalize immediately
        if validation.is_valid:
            state.is_finalized = True
            state.current_title = validation.cleaned_title
            state.history_verdicts.append(TitleRecoveryVerdict.ACCEPTED_CLEAN)
            return TitleRecoveryVerdict.ACCEPTED_CLEAN, validation.cleaned_title, validation

        # 3. Invalid candidate -> Increment exchange count
        state.exchange_count += 1

        # Check if more exchanges are permitted before capping out
        if state.exchange_count < self._config.max_recovery_exchanges:
            state.history_verdicts.append(TitleRecoveryVerdict.RETRY_LATER_PROVISIONAL)
            # Retain provisional title (or current default), allowing later turn to regenerate
            return TitleRecoveryVerdict.RETRY_LATER_PROVISIONAL, state.current_title, validation

        # 4. Exchange cap reached -> Trigger deterministic fallback and finalize
        fallback_title = self.generate_deterministic_fallback(fallback_content)
        state.is_finalized = True
        state.current_title = fallback_title
        state.history_verdicts.append(TitleRecoveryVerdict.FALLBACK_FINALIZED)
        return TitleRecoveryVerdict.FALLBACK_FINALIZED, fallback_title, validation

    def generate_deterministic_fallback(self, content: str) -> str:
        """Extracts a clean, deterministic fallback title from conversation text."""
        cleaned = re.sub(r"^(?:User|Assistant|System)[:：\s]*", "", content, flags=re.MULTILINE).strip()
        cleaned = re.sub(r"[#*`>~_-]+", " ", cleaned).strip()
        cleaned = " ".join(cleaned.split())

        preview_len = self._config.fallback_preview_length
        title = cleaned[:preview_len].strip()
        if len(title) < self._config.min_length:
            return "Untitled Chat"

        return title + ("..." if len(cleaned) > preview_len else "")

    def get_state(self, session_id: str) -> Optional[TitleRecoveryState]:
        """Returns the tracked recovery state for a session, if any."""
        return self._session_states.get(session_id)

    def reset_session(self, session_id: str) -> None:
        """Clears tracked state for a session."""
        self._session_states.pop(session_id, None)

    def _get_or_create_state(self, session_id: str) -> TitleRecoveryState:
        if session_id not in self._session_states:
            self._session_states[session_id] = TitleRecoveryState(
                session_id=session_id,
                current_title="Untitled Chat",
            )
        return self._session_states[session_id]
