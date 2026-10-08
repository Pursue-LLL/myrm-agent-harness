"""Classification gate for externally visible irreversible actions.

Identifies actions that escape the local boundary to third parties (emails,
webhooks, social media posts, messaging platforms) and enforces mandatory
human review and suppression of "allow always" options.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from myrm_agent_harness.core.security.externally_visible_action.types import (
    ActionVisibilityScope,
    AuditedExternalAction,
    ExternalActionClassification,
)
from myrm_agent_harness.core.security.tool_registry.registry import (
    SafetyMetadata,
    resolve_safety_metadata,
)

# Heuristic patterns identifying potential third-party communication
_EXTERNAL_COMMUNICATION_KEYWORDS: tuple[str, ...] = (
    "email",
    "send_mail",
    "send_email",
    "smtp",
    "sms",
    "tweet",
    "slack",
    "discord",
    "telegram",
    "webhook",
    "publish_post",
    "post_message",
    "send_teammate_message",
    "external_dispatch",
    "third_party_notify",
)

_USER_LOCAL_TOOLS: frozenset[str] = frozenset(
    {
        "ask_question_tool",
        "browser_ask_human_tool",
        "request_answer_user_tool",
    }
)


class ExternallyVisibleActionGate:
    """Security classification gate enforcing strict reviews for external-facing side effects."""

    def __init__(self, max_audit_records: int = 500) -> None:
        self._max_audit_records: int = max_audit_records
        self._audit_records: list[AuditedExternalAction] = []
        self._lock: threading.Lock = threading.Lock()

    def classify_tool(
        self,
        tool_name: str,
        explicit_metadata: SafetyMetadata | None = None,
    ) -> ExternalActionClassification:
        """Classify a tool's visibility scope and human-review constraints.

        Args:
            tool_name: Concrete or abstract tool identifier.
            explicit_metadata: Optional explicit safety metadata override.

        Returns:
            ExternalActionClassification detailing visibility and review mandates.
        """
        metadata = explicit_metadata or resolve_safety_metadata(tool_name)

        if metadata.is_third_party_visible or self._matches_external_heuristics(tool_name):
            return ExternalActionClassification(
                tool_name=tool_name,
                is_third_party_visible=True,
                requires_mandatory_human_review=True,
                hide_allow_always=True,
                visibility_scope=ActionVisibilityScope.THIRD_PARTY_VISIBLE,
                rationale=(
                    f"Tool '{tool_name}' performs actions visible to external third parties. "
                    "Mandatory single-approval human review is enforced; persistent auto-allow is disabled."
                ),
            )

        if tool_name in _USER_LOCAL_TOOLS:
            return ExternalActionClassification(
                tool_name=tool_name,
                is_third_party_visible=False,
                requires_mandatory_human_review=False,
                hide_allow_always=False,
                visibility_scope=ActionVisibilityScope.USER_LOCAL,
                rationale=f"Tool '{tool_name}' interacts exclusively with the local user session.",
            )

        return ExternalActionClassification(
            tool_name=tool_name,
            is_third_party_visible=False,
            requires_mandatory_human_review=False,
            hide_allow_always=False,
            visibility_scope=ActionVisibilityScope.INTERNAL_ONLY,
            rationale=f"Tool '{tool_name}' operates within local agent environment boundaries.",
        )

    def record_audit(
        self,
        action_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        recipient_or_destination: str,
        content_preview: str,
        is_approved: bool,
        approved_by: str | None = None,
        timestamp: float | None = None,
    ) -> AuditedExternalAction:
        """Record an externally visible action attempt into the thread-safe audit log."""
        record = AuditedExternalAction(
            action_id=action_id,
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            recipient_or_destination=recipient_or_destination,
            content_preview=content_preview,
            is_approved=is_approved,
            approved_by=approved_by,
            timestamp=timestamp if timestamp is not None else time.time(),
        )
        with self._lock:
            self._audit_records.append(record)
            if len(self._audit_records) > self._max_audit_records:
                self._audit_records = self._audit_records[-self._max_audit_records :]
        return record

    def get_audit_records(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[AuditedExternalAction]:
        """Query recent external action audit records with optional session filtering."""
        with self._lock:
            if session_id is None:
                matches = list(self._audit_records)
            else:
                matches = [r for r in self._audit_records if r.session_id == session_id]
        return matches[-limit:]

    def clear_audit_records(self) -> None:
        """Clear audit history (used primarily for test isolation)."""
        with self._lock:
            self._audit_records.clear()

    @staticmethod
    def _matches_external_heuristics(tool_name: str) -> bool:
        normalized = tool_name.lower()
        return any(keyword in normalized for keyword in _EXTERNAL_COMMUNICATION_KEYWORDS)
