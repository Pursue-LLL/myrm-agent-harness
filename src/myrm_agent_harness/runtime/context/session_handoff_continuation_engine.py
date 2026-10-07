"""Engine for Session Handoff and Clean Window Continuation.

Part of Item 126: SessionHandoffCleanWindowContinuationEngine.
Coordinates handoff state machines, compiles 8-part structured handoff memos into
clean-window priming bundles, and prevents historical regression / secondary pitfall falls.

[INPUT]
- runtime.context.session_handoff_continuation_types::CleanWindowContinuationBundle, HandoffPhaseKind,
  HandoffTriggerReason, StructuredHandoffMemo (POS: Types and models for Session Handoff and Clean Window
  Continuation.)
- utils.token_estimation::estimate_content_tokens (POS: Token estimation infrastructure. Covers
  message-level tokens and bind-tools overhead for context budget / compress / summarize decisions. Aligns
  with measure_turn1_token_inventory planning SSOT.)

[OUTPUT]
- SessionHandoffContinuationEngine: Stateful coordinator governing session handoffs and fresh-window
  bootstrap bundles.

[POS]
Engine for Session Handoff and Clean Window Continuation.
"""

from __future__ import annotations

import datetime
import logging
import threading
import uuid
from typing import Final

from myrm_agent_harness.runtime.context.session_handoff_continuation_types import (
    CleanWindowContinuationBundle,
    HandoffPhaseKind,
    HandoffTriggerReason,
    StructuredHandoffMemo,
)
from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

logger = logging.getLogger(__name__)

DEFAULT_ESTIMATED_PROMPT_OVERHEAD: Final[int] = 200


class SessionHandoffContinuationEngine:
    """Stateful coordinator governing session handoffs and fresh-window bootstrap bundles."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phases: dict[str, HandoffPhaseKind] = {}
        self._memos: dict[str, StructuredHandoffMemo] = {}
        self._bundles: dict[str, CleanWindowContinuationBundle] = {}

    def initiate_handoff(
        self,
        source_session_id: str,
        trigger_reason: HandoffTriggerReason = HandoffTriggerReason.CAPACITY_SATURATION,
    ) -> str:
        """Start a new handoff lifecycle for an active session."""
        handoff_id = f"handoff-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._phases[handoff_id] = HandoffPhaseKind.PREPARING
        logger.info(
            "Initiated handoff %s for session %s (reason: %s)",
            handoff_id,
            source_session_id,
            trigger_reason,
        )
        return handoff_id

    def submit_memo(
        self,
        handoff_id: str,
        memo: StructuredHandoffMemo,
    ) -> None:
        """Store the compiled 8-part structured handoff memo and transition to READY."""
        with self._lock:
            phase = self._phases.get(handoff_id)
            if phase != HandoffPhaseKind.PREPARING:
                raise ValueError(
                    f"Cannot submit memo in state '{phase}'; handoff must be in '{HandoffPhaseKind.PREPARING}'"
                )
            self._memos[handoff_id] = memo
            self._phases[handoff_id] = HandoffPhaseKind.READY_FOR_SHIFT

    def compile_bootstrap_prompt(self, memo: StructuredHandoffMemo) -> str:
        """Compile the 8-part memo into an unambiguous, dense Markdown bootstrap prompt."""
        lines: list[str] = [
            "<session_handoff_context>",
            "# Session Continuation Handoff Memorandum",
            f"- **Source Session ID**: `{memo.source_session_id}`",
            f"- **Handoff ID**: `{memo.memo_id}`",
            f"- **Trigger Reason**: `{memo.trigger_reason.value}`",
            f"- **Timestamp**: `{memo.created_at}`",
            "",
            "## 1. Primary Objective",
            memo.current_objective.strip(),
            "",
            "## 2. Completed Milestones",
        ]
        if memo.completed_milestones:
            for item in memo.completed_milestones:
                lines.append(f"- [x] {item}")
        else:
            lines.append("- *(None recorded)*")

        lines.extend(
            [
                "",
                "## 3. Active Hypotheses & State",
            ]
        )
        if memo.active_hypotheses:
            for hyp in memo.active_hypotheses:
                lines.append(f"- {hyp}")
        else:
            lines.append("- *(No unresolved hypotheses)*")

        lines.extend(
            [
                "",
                "## 4. Rejected Alternatives & Disqualifications (DO NOT RE-ATTEMPT)",
            ]
        )
        if memo.rejected_alternatives:
            for alt in memo.rejected_alternatives:
                lines.append(
                    f"- ⚠️ **Rejected Approach**: {alt.proposed_approach}\n"
                    f"  - **Failure Reason**: {alt.failure_reason}\n"
                    f"  - **Enforce No Retry**: {alt.prevent_retry}"
                )
        else:
            lines.append("- *(No approaches marked as disqualified)*")

        lines.extend(
            [
                "",
                "## 5. Critical Constraints & Principles",
            ]
        )
        if memo.critical_constraints:
            for constraint in memo.critical_constraints:
                lines.append(f"- 🛑 {constraint}")
        else:
            lines.append("- *(Standard system constraints apply)*")

        lines.extend(
            [
                "",
                "## 6. Actionable Next Steps",
            ]
        )
        if memo.next_action_plan:
            for idx, step in enumerate(memo.next_action_plan, 1):
                lines.append(f"{idx}. {step}")
        else:
            lines.append("1. Await explicit user prompt.")

        lines.extend(
            [
                "",
                "## 7. Modified Files & Artifacts",
            ]
        )
        if memo.modified_files_and_artifacts:
            for path in memo.modified_files_and_artifacts:
                lines.append(f"- `{path}`")
        else:
            lines.append("- *(No persistent files recorded)*")

        lines.extend(
            [
                "",
                "## 8. External State Anchors",
            ]
        )
        if memo.external_state_anchors:
            for k, v in memo.external_state_anchors.items():
                lines.append(f"- `{k}`: {v}")
        else:
            lines.append("- *(None)*")

        lines.extend(
            [
                "",
                "</session_handoff_context>",
                "You are resuming work from a clean context window. "
                "Adopt the objective above, strictly respect the rejected alternatives, "
                "and execute the next action plan immediately.",
            ]
        )

        return "\n".join(lines)

    def generate_clean_window_bundle(
        self,
        handoff_id: str,
        new_session_id: str,
        source_context_tokens: int,
    ) -> CleanWindowContinuationBundle:
        """Produce the clean window bootstrap bundle and compute token savings."""
        with self._lock:
            phase = self._phases.get(handoff_id)
            if phase != HandoffPhaseKind.READY_FOR_SHIFT:
                raise ValueError(f"Cannot generate bundle in phase '{phase}'; memo must be submitted first.")
            memo = self._memos[handoff_id]

        prompt = self.compile_bootstrap_prompt(memo)
        memo_tokens = estimate_content_tokens(prompt) + DEFAULT_ESTIMATED_PROMPT_OVERHEAD

        safe_source_tokens = max(1, source_context_tokens)
        if safe_source_tokens > memo_tokens:
            savings_pct = round(((safe_source_tokens - memo_tokens) / safe_source_tokens) * 100.0, 2)
        else:
            savings_pct = 0.0

        bundle = CleanWindowContinuationBundle(
            source_session_id=memo.source_session_id,
            new_session_id=new_session_id,
            handoff_memo=memo,
            bootstrap_prompt=prompt,
            source_context_tokens=safe_source_tokens,
            handoff_memo_tokens=memo_tokens,
            estimated_token_savings_pct=savings_pct,
            timestamp_iso=datetime.datetime.now(datetime.UTC).isoformat(),
        )

        with self._lock:
            self._bundles[handoff_id] = bundle

        return bundle

    def commit_transfer(self, handoff_id: str) -> bool:
        """Mark the handoff as successfully transferred to the fresh window."""
        with self._lock:
            if handoff_id not in self._bundles:
                return False
            self._phases[handoff_id] = HandoffPhaseKind.TRANSFERRED
            return True

    def abort_handoff(self, handoff_id: str, reason: str = "") -> None:
        """Abort an in-flight handoff lifecycle."""
        with self._lock:
            self._phases[handoff_id] = HandoffPhaseKind.ABORTED
        logger.warning("Handoff %s aborted (reason: %s)", handoff_id, reason)

    def get_phase(self, handoff_id: str) -> HandoffPhaseKind:
        """Check current lifecycle phase of a handoff."""
        with self._lock:
            return self._phases.get(handoff_id, HandoffPhaseKind.ABORTED)
