"""Long-horizon research incremental checkpoints and draft persistence suite.

[OUTPUT]
- ResearchStatus: Execution progression status enum.
- ResearchChapterDraft: Materialized chapter draft container.
- ResearchCheckpoint: Structured state snapshot.
- ResumptionPlan: Actionable plan instructing the agent loop where and how to resume.
- IncrementalDraftStore: Atomic disk persistence for intermediate chapter drafts.
- ResearchCheckpointLedger: SQLite-backed transactional checkpoint ledger.
- ResearchResumptionEngine: Zero-waste resumption plan and prompt injector.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Long-horizon research incremental checkpoints and draft persistence suite.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.research_checkpoint.checkpoint_ledger import (
    ResearchCheckpointLedger,
)
from myrm_agent_harness.runtime.research_checkpoint.checkpoint_types import (
    ResearchChapterDraft,
    ResearchCheckpoint,
    ResearchStatus,
    ResumptionPlan,
)
from myrm_agent_harness.runtime.research_checkpoint.draft_store import (
    IncrementalDraftStore,
)
from myrm_agent_harness.runtime.research_checkpoint.resumption_engine import (
    ResearchResumptionEngine,
)

__all__ = [
    "IncrementalDraftStore",
    "ResearchChapterDraft",
    "ResearchCheckpoint",
    "ResearchCheckpointLedger",
    "ResearchResumptionEngine",
    "ResearchStatus",
    "ResumptionPlan",
]
