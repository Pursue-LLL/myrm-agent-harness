"""Multi-Human Multi-Agent Live Document Co-Authoring Ledger and Conflict Arbitration module.

[INPUT]
- conflict_arbitrator
- ledger_engine
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Multi-Human Multi-Agent Live Document Co-Authoring Ledger and Conflict Arbitration module.

"""

from .conflict_arbitrator import CoAuthoringConflictArbitrator
from .ledger_engine import LiveDocumentCoAuthoringLedger
from .types import (
    ArbitrationStrategy,
    ArbitrationVerdict,
    BlockType,
    CollaboratorProfile,
    CollaboratorType,
    ConflictRecord,
    DeltaEntry,
    DeltaOperation,
    DocumentBlock,
    StagingProposal,
)

__all__ = [
    "ArbitrationStrategy",
    "ArbitrationVerdict",
    "BlockType",
    "CoAuthoringConflictArbitrator",
    "CollaboratorProfile",
    "CollaboratorType",
    "ConflictRecord",
    "DeltaEntry",
    "DeltaOperation",
    "DocumentBlock",
    "LiveDocumentCoAuthoringLedger",
    "StagingProposal",
]
