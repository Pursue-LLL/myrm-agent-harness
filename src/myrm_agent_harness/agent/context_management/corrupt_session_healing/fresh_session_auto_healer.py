"""Zero-freeze fresh session derivation and self-healing context injector.

[INPUT]
- healing_types: HealingSuiteConfig, RestorationOutcome, RestorationStatus,
  SalvagedMessageItem.

[OUTPUT]
- FreshSessionAutoHealer: Derives resilient replacement sessions when restoration
  encounters fatal corruption, seamlessly priming salvaged context.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.corrupt_session_healing
- Module: fresh_session_auto_healer.py
"""

import time
from typing import Optional, Sequence
from myrm_agent_harness.agent.context_management.corrupt_session_healing.healing_types import (
    HealingSuiteConfig,
    RestorationOutcome,
    RestorationStatus,
    SalvagedMessageItem,
)


class FreshSessionAutoHealer:
    """Spawns fresh replacement sessions to prevent application freeze on storage corruption."""

    def __init__(self, config: Optional[HealingSuiteConfig] = None) -> None:
        self._config = config or HealingSuiteConfig()

    def derive_healed_session(
        self,
        corrupted_session_id: str,
        salvaged_messages: Sequence[SalvagedMessageItem],
        diagnostic_reason: str,
    ) -> RestorationOutcome:
        """Derives a resilient replacement session initialized with any salvaged history.

        Args:
            corrupted_session_id: Original failed session identifier.
            salvaged_messages: Partial messages recovered by the salvager.
            diagnostic_reason: Cause of original failure.

        Returns:
            RestorationOutcome indicating the active session and recovery status.
        """
        now_ts = int(time.time())
        fresh_id = f"{self._config.fresh_session_prefix}-{corrupted_session_id[:12]}-{now_ts}"

        if salvaged_messages:
            status = RestorationStatus.SALVAGED_PARTIAL
            msg = (
                f"Session '{corrupted_session_id}' suffered partial corruption ({diagnostic_reason}). "
                f"Successfully salvaged {len(salvaged_messages)} messages and ported to fresh session '{fresh_id}'."
            )
        else:
            status = RestorationStatus.HEALED_FRESH_FALLBACK
            msg = (
                f"Session '{corrupted_session_id}' was severely corrupted ({diagnostic_reason}). "
                f"Created clean fresh session '{fresh_id}' to prevent UI freeze."
            )

        return RestorationOutcome(
            original_session_id=corrupted_session_id,
            active_session_id=fresh_id,
            status=status,
            salvaged_messages=salvaged_messages,
            is_fresh_session=True,
            diagnostic_message=msg,
        )

    def render_healed_context_intro(self, outcome: RestorationOutcome) -> str:
        """Renders an introductory system guidance block for the new healed conversation."""
        lines = ["[SESSION_AUTO_HEALED_NOTICE]"]
        lines.append(f"- Original Session ID: {outcome.original_session_id}")
        lines.append(f"- Healed Session ID: {outcome.active_session_id}")
        lines.append(f"- Status: {outcome.status.value}")
        if outcome.salvaged_messages:
            lines.append(
                f"- Salvaged History: {len(outcome.salvaged_messages)} messages successfully recovered."
            )
        else:
            lines.append("- Salvaged History: None (Fresh start).")
        lines.append("- Note: Previous storage record was safely quarantined.")
        lines.append("[/SESSION_AUTO_HEALED_NOTICE]")
        return "\n".join(lines)
