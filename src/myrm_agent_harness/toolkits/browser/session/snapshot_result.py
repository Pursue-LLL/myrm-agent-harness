"""Immutable snapshot result type for browser ARIA snapshots.

[INPUT]
- toolkits.browser.snapshot::RefInfo, (POS: browser_snapshot tool for ARIA tree capture.)

[OUTPUT]
- SnapshotResult: immutable snapshot result type (aria_tree, refs, meta).

[POS]
Immutable snapshot result type for browser ARIA snapshots.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.snapshot import RefInfo, SnapshotMeta

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session.snapshot_diff import DiffOutput


@dataclass(frozen=True)
class SnapshotResult:
    """Immutable snapshot result for one browser ARIA snapshot.

    Contains the enhanced ARIA tree, the refs maps, and metadata in an
    immutable data structure, guaranteeing the snapshot data is complete.
    Supports tuple-style unpacking as ``aria_tree, metadata = result``.
    """

    aria_tree: str
    refs: MappingProxyType[str, RefInfo]
    meta: SnapshotMeta
    is_incremental: bool
    diff_output: DiffOutput | None = None

    def __iter__(self) -> Iterator[object]:
        """Allow backward-compatible tuple unpacking."""
        yield self.aria_tree
        yield self.meta._asdict()

    @property
    def tree(self) -> str:
        """Backward-compatible alias for ``aria_tree``."""
        return self.aria_tree

    @property
    def is_identical(self) -> bool:
        """Whether the snapshot is identical to the baseline."""
        return self.diff_output.is_identical if self.diff_output is not None else False

    @property
    def additions(self) -> int:
        """Count of added lines in the semantic diff."""
        return self.diff_output.additions if self.diff_output is not None else 0

    @property
    def removals(self) -> int:
        """Count of removed lines in the semantic diff."""
        return self.diff_output.removals if self.diff_output is not None else 0

    @property
    def tokens_saved(self) -> int:
        """Estimated tokens saved by differential representation."""
        return self.diff_output.tokens_saved if self.diff_output is not None else 0

    @property
    def is_fallback_full(self) -> bool:
        """Whether the diff exceeded change ratio and fell back to full snapshot."""
        return self.diff_output.is_fallback_full if self.diff_output is not None else False
