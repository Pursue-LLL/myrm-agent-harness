"""Master facade suite for invalid generated title recovery and self-healing.

[INPUT]
- title_recovery_types: TitleRecoveryConfig, TitleRecoveryState,
  TitleRecoveryVerdict, TitleValidationResult.
- invalid_title_taxonomy: InvalidTitleTaxonomy.
- provisional_title_retry_gate: ProvisionalTitleRetryGate.

[OUTPUT]
- InvalidGeneratedTitleRecoverySuite: Master facade coordinating
  structural taxonomy validation, provisional delayed writes, and capped fallback.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.title_recovery
- Module: title_recovery_suite.py
"""

from typing import Optional, Tuple

from myrm_agent_harness.agent.context_management.title_recovery.invalid_title_taxonomy import (
    InvalidTitleTaxonomy,
)
from myrm_agent_harness.agent.context_management.title_recovery.provisional_title_retry_gate import (
    ProvisionalTitleRetryGate,
)
from myrm_agent_harness.agent.context_management.title_recovery.title_recovery_types import (
    TitleRecoveryConfig,
    TitleRecoveryState,
    TitleRecoveryVerdict,
    TitleValidationResult,
)


class InvalidGeneratedTitleRecoverySuite:
    """Master facade for vetting LLM titles, deferring dirty DB writes, and self-healing."""

    def __init__(self, config: Optional[TitleRecoveryConfig] = None) -> None:
        self._config = config or TitleRecoveryConfig()
        self._taxonomy = InvalidTitleTaxonomy(self._config)
        self._gate = ProvisionalTitleRetryGate(self._config)

    @property
    def config(self) -> TitleRecoveryConfig:
        """Returns the active configuration."""
        return self._config

    @property
    def taxonomy(self) -> InvalidTitleTaxonomy:
        """Returns the structural defect taxonomy classifier."""
        return self._taxonomy

    @property
    def gate(self) -> ProvisionalTitleRetryGate:
        """Returns the provisional title retry gate."""
        return self._gate

    def evaluate_title(
        self,
        session_id: str,
        raw_candidate: str,
        fallback_content: str,
    ) -> Tuple[TitleRecoveryVerdict, str, TitleValidationResult]:
        """Evaluates a raw LLM title, returning action verdict and effective title."""
        return self._gate.evaluate_title_candidate(session_id, raw_candidate, fallback_content)

    def validate_title(self, raw_candidate: str) -> TitleValidationResult:
        """Directly classifies and cleanses a candidate title string without modifying session state."""
        return self._taxonomy.validate_and_cleanse(raw_candidate)

    def is_valid_title(self, raw_candidate: str) -> bool:
        """Quick boolean check whether candidate title is free of structural defects."""
        return self._taxonomy.validate_and_cleanse(raw_candidate).is_valid

    def generate_fallback(self, fallback_content: str) -> str:
        """Generates a clean deterministic fallback title from conversation text."""
        return self._gate.generate_deterministic_fallback(fallback_content)

    def get_session_state(self, session_id: str) -> Optional[TitleRecoveryState]:
        """Retrieves session recovery state."""
        return self._gate.get_state(session_id)

    def reset_session(self, session_id: str) -> None:
        """Resets session recovery tracking."""
        self._gate.reset_session(session_id)
