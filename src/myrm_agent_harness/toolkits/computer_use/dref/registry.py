"""Session-scoped @dref registry.

[INPUT]
- dref.errors::DRefStaleError (POS: stale ref lookup errors)
- dref.types::{ElementRef, SnapshotMeta} (POS: ref entries and snapshot metadata)

[OUTPUT]
- DRefRegistry: session-scoped @dref ID map with generation tracking

[POS]
Session-scoped registry for desktop @dref entries during a computer_use session.
"""

from __future__ import annotations

from collections.abc import Mapping

from myrm_agent_harness.toolkits.computer_use.dref.errors import DRefStaleError
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta


class DRefRegistry:
    """Maps @dref IDs to ElementRef entries for the current desktop session."""

    def __init__(self) -> None:
        self._refs: dict[str, ElementRef] = {}
        self._meta: SnapshotMeta | None = None
        self._generation: int = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def meta(self) -> SnapshotMeta | None:
        return self._meta

    def replace(
        self,
        refs: Mapping[str, ElementRef],
        meta: SnapshotMeta,
    ) -> None:
        self._refs = dict(refs)
        self._meta = meta
        self._generation += 1

    def get(self, ref_id: str) -> ElementRef:
        normalized = ref_id.strip()
        if normalized.startswith("@"):
            normalized = normalized[1:]
        if not normalized.startswith("d"):
            normalized = f"d{normalized}"
        element = self._refs.get(normalized)
        if element is None:
            raise DRefStaleError(normalized)
        return element

    def all_refs(self) -> dict[str, ElementRef]:
        return dict(self._refs)
