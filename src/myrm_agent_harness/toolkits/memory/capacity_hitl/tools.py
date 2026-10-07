"""[POS]: src/myrm_agent_harness/toolkits/memory/capacity_hitl/tools.py
[INPUT]: CapacityHitlService instance.
[OUTPUT]: Meta tools exposed to AI Agent for checking memory capacity and reviewing candidates.
"""

from myrm_agent_harness.toolkits.memory.capacity_hitl.models import (
    CapacityStatusReport,
    HitlCandidateProposal,
    HitlCandidateStatus,
)
from myrm_agent_harness.toolkits.memory.capacity_hitl.service import (
    CapacityHitlService,
)


class CapacityHitlMetaTools:
    """Agent meta tools for monitoring memory capacity and proposing HITL candidates."""

    def __init__(self, service: CapacityHitlService) -> None:
        self._service = service

    def check_memory_capacity(
        self, total_entries: int, max_entries: int | None = None
    ) -> CapacityStatusReport:
        """Inspect memory capacity quota and determine if remediation candidates should be displayed."""
        return self._service.check_capacity_status(
            total_entries=total_entries, max_entries=max_entries
        )

    def list_pending_capacity_candidates(self) -> list[HitlCandidateProposal]:
        """Fetch read-only candidate proposals awaiting human review and approval."""
        return self._service.list_proposals(status=HitlCandidateStatus.PENDING)

    def propose_capacity_candidates(
        self,
        entries: list[dict[str, str | int | float | list[str]]],
        max_proposals: int = 10,
    ) -> list[HitlCandidateProposal]:
        """Formulate merge and archive candidate proposals without mutating existing memories."""
        return self._service.generate_and_store_proposals(
            entries=entries, max_proposals=max_proposals
        )
