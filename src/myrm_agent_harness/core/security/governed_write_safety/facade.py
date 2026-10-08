"""
[POS] src/myrm_agent_harness/core/security/governed_write_safety/facade.py
[INPUT] typing, types, opaque_registry, governed_write_engine
[OUTPUT] GovernedWriteSafetyFacade
Unified facade for opaque ID abstraction, proposal governance, and atomic commit verification.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .governed_write_engine import GovernedWriteEngine
from .opaque_registry import OpaqueFileRegistry
from .types import (
    CommitWriteResult,
    GovernedWriteProposal,
    PreImageSnapshot,
)

logger = logging.getLogger(__name__)


class GovernedWriteSafetyFacade:
    """Unified entrypoint for 'string is never authority' write safety pipeline."""

    def __init__(
        self,
        registry: OpaqueFileRegistry | None = None,
        engine: GovernedWriteEngine | None = None,
    ) -> None:
        self._registry = registry or OpaqueFileRegistry()
        self._engine = engine or GovernedWriteEngine()

    @property
    def registry(self) -> OpaqueFileRegistry:
        """Underlying opaque file ID registry."""
        return self._registry

    @property
    def engine(self) -> GovernedWriteEngine:
        """Underlying governed write execution engine."""
        return self._engine

    def register_opaque_file(self, raw_path: str) -> str:
        """Shield a raw filesystem path behind a secure opaque token."""
        return self._registry.register_path(raw_path)

    def resolve_path(self, opaque_file_id: str) -> str | None:
        """Resolve an opaque token to physical filesystem path."""
        return self._registry.resolve_opaque_id(opaque_file_id)

    def propose_edit(
        self,
        opaque_file_id: str,
        current_disk_content: str,
        candidate_content: str,
    ) -> GovernedWriteProposal:
        """Create a binding edit proposal tied to base content hash and opaque ID."""
        raw_path = self._registry.resolve_opaque_id(opaque_file_id)
        if raw_path is None:
            raise KeyError(f"Opaque file ID '{opaque_file_id}' is not registered in governance layer")

        return self._engine.create_proposal(
            opaque_file_id=opaque_file_id,
            raw_path=raw_path,
            current_disk_content=current_disk_content,
            candidate_content=candidate_content,
        )

    def approve_edit(self, proposal_id: str) -> str:
        """Approve an edit proposal and issue a single-use write lease token."""
        return self._engine.approve_proposal(proposal_id)

    def commit_edit(
        self,
        proposal_id: str,
        lease_token: str,
        current_disk_content: str,
        write_executor: Callable[[str], str],
    ) -> CommitWriteResult:
        """Commit an approved write proposal with atomic stale check and pre-image capture."""
        return self._engine.commit_write(
            proposal_id=proposal_id,
            lease_token=lease_token,
            current_disk_content=current_disk_content,
            write_executor=write_executor,
        )

    def get_snapshot(self, snapshot_id: str) -> PreImageSnapshot | None:
        """Retrieve pre-image snapshot record."""
        return self._engine.get_snapshot(snapshot_id)

    def get_proposal(self, proposal_id: str) -> GovernedWriteProposal | None:
        """Retrieve governed write proposal details."""
        return self._engine.get_proposal(proposal_id)
