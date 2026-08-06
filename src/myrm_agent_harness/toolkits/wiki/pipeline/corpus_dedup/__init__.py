"""Raw corpus deduplication governance for wiki compile prerequisites.

[POS]
See module docstring.
"""

from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.eligibility import (
    CorpusEligibilityFilter,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.governor import (
    CorpusDedupGovernor,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.scanner import (
    CorpusDedupScanner,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.snippets import (
    build_group_body_snippets,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.store import (
    CorpusDedupStore,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.types import (
    DedupStats,
    DedupTier,
    DispositionAction,
    DispositionResult,
    DuplicateGroup,
    DuplicateMemberSnippet,
    ExcludedRawEntry,
    GroupStatus,
    ScanProgress,
    ScanResult,
    TrashedRawEntry,
    VaultHygieneSnapshot,
)

__all__ = [
    "CorpusDedupGovernor",
    "CorpusDedupScanner",
    "CorpusDedupStore",
    "CorpusEligibilityFilter",
    "DedupStats",
    "DedupTier",
    "DispositionAction",
    "DispositionResult",
    "DuplicateGroup",
    "DuplicateMemberSnippet",
    "ExcludedRawEntry",
    "GroupStatus",
    "ScanProgress",
    "ScanResult",
    "TrashedRawEntry",
    "VaultHygieneSnapshot",
    "build_group_body_snippets",
]
