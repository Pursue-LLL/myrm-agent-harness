# [INPUT]: None
# [OUTPUT]: ActionDetailDescriptor, ActionExecutionFailure, ActiveEvidenceDisclosureSuite, BoundedEvidenceReader, EvidenceDisclosureReceipt, EvidenceOutcome, EvidenceQueryLocator, EvidenceRefTarget, EvidenceSourceState, PaginatedEvidencePage, QueryScopeKind, RealReadSlice, build_action_leaf_ref, build_collection_ref, disclose_action, parse_evidence_ref, project_action_isomorphic
# [POS]: agent/context_management/evidence_disclosure/__init__.py

"""Evidence disclosure subsystem providing isomorphic action disclosure and query scope isolation.

[INPUT]
- None (Public package facade).

[OUTPUT]
- ActionDetailDescriptor: Unified canonical descriptor of an action.
- ActionExecutionFailure: Detailed error record when an action execution fails.
- ActiveEvidenceDisclosureSuite: Unified engine managing isomorphic disclosure, scopes, and pagination.
- BoundedEvidenceReader: Engine calculating pagination windows bound to verifiable reading offsets.
- EvidenceDisclosureReceipt: Attestation receipt confirming evidence disclosure parity.
- EvidenceOutcome: Standard outcome state for tool/action execution.
- EvidenceQueryLocator: Deterministic evidence retrieval and scope isolation engine.
- EvidenceRefTarget: Structured reference representation of a collection or leaf action.
- EvidenceSourceState: State discriminator distinguishing active turns from completed history.
- PaginatedEvidencePage: Container with real-read window pagination metadata.
- QueryScopeKind: Deterministic scope constraint for evidence queries.
- RealReadSlice: Content slice bound to deterministic real-reading offsets and checksum.
- build_action_leaf_ref: Format leaf reference string for a specific action occurrence.
- build_collection_ref: Format collection reference string for a turn's action set.
- disclose_action: Attestation receipt generator validating parity compliance.
- parse_evidence_ref: Parse raw reference string into structured EvidenceRefTarget.
- project_action_isomorphic: Canonical functional projector transforming actions into unified descriptors.

[POS]
Package entry point for active/completed isomorphic evidence disclosure.
"""

from __future__ import annotations

from .active_evidence_disclosure_suite import (
    ActiveEvidenceDisclosureSuite,
    disclose_action,
    project_action_isomorphic,
)
from .evidence_disclosure_types import (
    ActionDetailDescriptor,
    ActionExecutionFailure,
    EvidenceDisclosureReceipt,
    EvidenceOutcome,
    EvidenceRefTarget,
    EvidenceSourceState,
    PaginatedEvidencePage,
    QueryScopeKind,
    RealReadSlice,
)
from .evidence_pagination_reader import BoundedEvidenceReader
from .evidence_query_locator import (
    EvidenceQueryLocator,
    build_action_leaf_ref,
    build_collection_ref,
    parse_evidence_ref,
)

__all__ = [
    "ActionDetailDescriptor",
    "ActionExecutionFailure",
    "ActiveEvidenceDisclosureSuite",
    "BoundedEvidenceReader",
    "EvidenceDisclosureReceipt",
    "EvidenceOutcome",
    "EvidenceQueryLocator",
    "EvidenceRefTarget",
    "EvidenceSourceState",
    "PaginatedEvidencePage",
    "QueryScopeKind",
    "RealReadSlice",
    "build_action_leaf_ref",
    "build_collection_ref",
    "disclose_action",
    "parse_evidence_ref",
    "project_action_isomorphic",
]
