"""
[POS] src/myrm_agent_harness/core/security/governed_write_safety/__init__.py
String-Is-Never-Authority Governed Write Safety Suite.
Exports domain types, opaque registry, governed write engine, and facade.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import GovernedWriteSafetyFacade
from .governed_write_engine import GovernedWriteEngine
from .opaque_registry import OpaqueFileRegistry
from .types import (
    CommitWriteResult,
    ConflictRecoveryBundle,
    GovernedWriteProposal,
    PreImageSnapshot,
    WriteProposalStatus,
)

__all__ = [
    "CommitWriteResult",
    "ConflictRecoveryBundle",
    "GovernedWriteProposal",
    "GovernedWriteEngine",
    "GovernedWriteSafetyFacade",
    "OpaqueFileRegistry",
    "PreImageSnapshot",
    "WriteProposalStatus",
]
