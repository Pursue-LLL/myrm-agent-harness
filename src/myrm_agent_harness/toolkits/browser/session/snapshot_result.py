"""Immutable snapshot result type for browser ARIA snapshots.

[INPUT]
- toolkits.browser.snapshot::RefInfo, (POS: browser_snapshot tool for ARIA tree capture.)

[OUTPUT]
- SnapshotResult: snapshotresult

[POS]
Immutable snapshot result type for browser ARIA snapshots.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from types import MappingProxyType

from myrm_agent_harness.toolkits.browser.snapshot import RefInfo, SnapshotMeta


@dataclass(frozen=True)
class SnapshotResult:
    """snapshotresult

    containsenhanceresulting ARIA tree, refs mapsandmetadata.
    immutabledatastructure, guaranteessnapshotdata'scomplete.
    Supports tuple-style unpacking as ``aria_tree, metadata = result``.
    """

    aria_tree: str
    refs: MappingProxyType[str, RefInfo]
    meta: SnapshotMeta
    is_incremental: bool

    def __iter__(self) -> Iterator[object]:
        """Allow backward-compatible tuple unpacking."""
        yield self.aria_tree
        yield self.meta._asdict()

    @property
    def tree(self) -> str:
        """Backward-compatible alias for ``aria_tree``."""
        return self.aria_tree
