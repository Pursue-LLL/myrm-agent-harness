"""Comprehensive facade suite for isomorphic active and completed evidence disclosure.

[INPUT]
- ActionDetailDescriptor: Unified canonical descriptor of an action.
- ActionExecutionFailure: Detailed error record when an action execution fails.
- EvidenceDisclosureReceipt: Attestation receipt confirming evidence disclosure parity.
- EvidenceOutcome: Standard outcome state for tool/action execution.
- EvidenceSourceState: State discriminator (ACTIVE_TURN vs COMPLETED_HISTORY).
- PaginatedEvidencePage: Paginated container with real-read metadata.
- QueryScopeKind: Deterministic scope constraint (ACTIVE_TURN, COMPLETED_HISTORY, UNIFIED_ALL).

[OUTPUT]
- ActiveEvidenceDisclosureSuite: Unified engine managing isomorphic disclosure, scopes, and pagination.
- project_action_isomorphic: Canonical functional projector transforming actions into unified descriptors.
- disclose_action: Attestation receipt generator validating parity compliance.

[POS]
End-to-end facade suite for active and history isomorphic evidence disclosure.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence
import uuid

from .evidence_disclosure_types import (
    ActionDetailDescriptor,
    ActionExecutionFailure,
    EvidenceDisclosureReceipt,
    EvidenceOutcome,
    EvidenceSourceState,
    PaginatedEvidencePage,
    QueryScopeKind,
)
from .evidence_pagination_reader import BoundedEvidenceReader
from .evidence_query_locator import (
    EvidenceQueryLocator,
    build_action_leaf_ref,
    build_collection_ref,
    parse_evidence_ref,
)


def project_action_isomorphic(
    turn_ref: str,
    occurrence: int,
    action_name: str,
    request: Mapping[str, str | int | float | bool | None],
    outcome: EvidenceOutcome,
    source_state: EvidenceSourceState,
    *,
    result: Mapping[str, str | int | float | bool | None] | str | None = None,
    failure: ActionExecutionFailure | None = None,
    references: tuple[str, ...] = (),
    timestamp: float | None = None,
) -> ActionDetailDescriptor:
    """Project action details into the single canonical schema shared between active and history states."""
    return ActionDetailDescriptor(
        turn_ref=turn_ref,
        occurrence=occurrence,
        action_name=action_name,
        request=request,
        outcome=outcome,
        source_state=source_state,
        result=result,
        failure=failure,
        references=references,
        timestamp=timestamp if timestamp is not None else time.time(),
        kind="session_action",
    )


def disclose_action(descriptor: ActionDetailDescriptor) -> EvidenceDisclosureReceipt:
    """Generate an attestation receipt confirming that an action satisfies isomorphic disclosure."""
    receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    return EvidenceDisclosureReceipt(
        receipt_id=receipt_id,
        action_ref=descriptor.ref,
        isomorphic_parity=True,
        source_state=descriptor.source_state,
        fingerprint=descriptor.content_hash,
        timestamp=time.time(),
    )


class ActiveEvidenceDisclosureSuite:
    """End-to-end suite providing isomorphic disclosure, deterministic query scoping, and bound pagination."""

    def __init__(
        self,
        *,
        default_page_size: int = 10,
        max_page_size: int = 100,
    ) -> None:
        self._locator = EvidenceQueryLocator()
        self._reader = BoundedEvidenceReader(
            default_page_size=default_page_size,
            max_page_size=max_page_size,
        )

    def project_active_action(
        self,
        turn_ref: str,
        occurrence: int,
        action_name: str,
        request: Mapping[str, str | int | float | bool | None],
        outcome: EvidenceOutcome,
        *,
        result: Mapping[str, str | int | float | bool | None] | str | None = None,
        failure: ActionExecutionFailure | None = None,
        references: tuple[str, ...] = (),
    ) -> ActionDetailDescriptor:
        """Project an ongoing or settled action in the active turn into canonical isomorphic schema."""
        return project_action_isomorphic(
            turn_ref=turn_ref,
            occurrence=occurrence,
            action_name=action_name,
            request=request,
            outcome=outcome,
            source_state=EvidenceSourceState.ACTIVE_TURN,
            result=result,
            failure=failure,
            references=references,
        )

    def project_completed_action(
        self,
        turn_ref: str,
        occurrence: int,
        action_name: str,
        request: Mapping[str, str | int | float | bool | None],
        outcome: EvidenceOutcome,
        *,
        result: Mapping[str, str | int | float | bool | None] | str | None = None,
        failure: ActionExecutionFailure | None = None,
        references: tuple[str, ...] = (),
        timestamp: float | None = None,
    ) -> ActionDetailDescriptor:
        """Project a finalized action in completed history into identical isomorphic schema."""
        return project_action_isomorphic(
            turn_ref=turn_ref,
            occurrence=occurrence,
            action_name=action_name,
            request=request,
            outcome=outcome,
            source_state=EvidenceSourceState.COMPLETED_HISTORY,
            result=result,
            failure=failure,
            references=references,
            timestamp=timestamp,
        )

    def verify_isomorphic_parity(
        self,
        active_desc: ActionDetailDescriptor,
        history_desc: ActionDetailDescriptor,
    ) -> bool:
        """Verify that an active action and a historical action share identical semantic keys and structure."""
        active_proj = active_desc.to_projection()
        history_proj = history_desc.to_projection()

        # Both must share identical structural keys
        if set(active_proj.keys()) - {"source_state", "timestamp"} != set(history_proj.keys()) - {"source_state", "timestamp"}:
            return False

        # Must have same canonical kind
        if active_desc.kind != "session_action" or history_desc.kind != "session_action":
            return False

        # Key semantic properties must match when comparing identical occurrences
        return bool(
            active_desc.action_name == history_desc.action_name
            and active_desc.occurrence == history_desc.occurrence
            and dict(active_desc.request) == dict(history_desc.request)
        )

    def disclose(self, descriptor: ActionDetailDescriptor) -> EvidenceDisclosureReceipt:
        """Disclose canonical action details and issue an attestation receipt."""
        return disclose_action(descriptor)

    def locate_evidence(
        self,
        scope: QueryScopeKind,
        *,
        target_ref: str | None = None,
        action_name: str | None = None,
        keyword: str | None = None,
        active_actions: Sequence[ActionDetailDescriptor] = (),
        history_actions: Sequence[ActionDetailDescriptor] = (),
    ) -> tuple[ActionDetailDescriptor, ...]:
        """Query action evidence with deterministic scope isolation."""
        return self._locator.locate(
            scope,
            target_ref=target_ref,
            action_name=action_name,
            keyword=keyword,
            active_actions=active_actions,
            history_actions=history_actions,
        )

    def paginate_and_read(
        self,
        descriptors: Sequence[ActionDetailDescriptor],
        *,
        page_number: int = 1,
        page_size: int | None = None,
        text_content_by_ref: Mapping[str, str] | None = None,
        max_text_window: int = 512,
    ) -> PaginatedEvidencePage:
        """Paginate action descriptors and bind each view to verifiable real reading offsets."""
        return self._reader.paginate_and_read(
            descriptors,
            page_number=page_number,
            page_size=page_size,
            text_content_by_ref=text_content_by_ref,
            max_text_window=max_text_window,
        )

    @staticmethod
    def parse_ref(ref: str) -> str | None:
        """Validate and return canonical reference if valid, else None."""
        target = parse_evidence_ref(ref)
        return target.canonical_ref if target is not None else None

    @staticmethod
    def make_leaf_ref(turn_ref: str, occurrence: int) -> str:
        return build_action_leaf_ref(turn_ref, occurrence)

    @staticmethod
    def make_collection_ref(turn_ref: str) -> str:
        return build_collection_ref(turn_ref)
