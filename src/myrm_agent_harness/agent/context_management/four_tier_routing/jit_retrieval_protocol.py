# [INPUT]: FourTierContextConfig, JitHandle
# [OUTPUT]: JitRetrievalProtocol
# [POS]: agent/context_management/four_tier_routing/jit_retrieval_protocol.py

"""Tier 3: Just-In-Time (JIT) retrieval protocol and lightweight reference handles.

[INPUT]
- FourTierContextConfig, JitHandle from four_tier_types.

[OUTPUT]
- JitRetrievalProtocol: Manages lightweight documentation/schema handles, keeping the default
  context footprint minimal and expanding full payloads strictly on demand.

[POS]
Protocol layer preventing bloated context by replacing large references with interactive handles.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .four_tier_types import FourTierContextConfig, JitHandle


class JitRetrievalProtocol:
    """Coordinates lightweight pointer handles and on-demand content hydration."""

    def __init__(self, config: FourTierContextConfig | None = None) -> None:
        self._config = config or FourTierContextConfig()
        self._handles: Dict[str, JitHandle] = {}

    @property
    def config(self) -> FourTierContextConfig:
        return self._config

    def register_handle(self, handle: JitHandle) -> None:
        """Register a reference handle into the JIT catalog."""
        self._handles[handle.handle_id] = handle

    def get_handle(self, handle_id: str) -> Optional[JitHandle]:
        """Fetch a registered handle by its ID."""
        return self._handles.get(handle_id)

    def hydrate_handle(self, handle_id: str, content: str | None = None) -> Optional[JitHandle]:
        """Hydrate a handle with its full text payload, marking it active."""
        if handle_id not in self._handles:
            return None

        old = self._handles[handle_id]
        hydrated_text = content or old.hydrated_content or f"[Full content for {old.title} from {old.full_reference_pointer}]"
        updated = JitHandle(
            handle_id=old.handle_id,
            title=old.title,
            summary=old.summary,
            full_reference_pointer=old.full_reference_pointer,
            is_hydrated=True,
            hydrated_content=hydrated_text,
        )
        self._handles[handle_id] = updated
        return updated

    def de_hydrate_handle(self, handle_id: str) -> Optional[JitHandle]:
        """Collapse a hydrated handle back into a compact pointer."""
        if handle_id not in self._handles:
            return None

        old = self._handles[handle_id]
        updated = JitHandle(
            handle_id=old.handle_id,
            title=old.title,
            summary=old.summary,
            full_reference_pointer=old.full_reference_pointer,
            is_hydrated=False,
            hydrated_content=None,
        )
        self._handles[handle_id] = updated
        return updated

    def render_catalog(
        self,
        max_items: int | None = None,
    ) -> str:
        """Render registered JIT handles as compact pointers or hydrated sections."""
        limit = max_items or self._config.max_jit_handles
        selected = list(self._handles.values())[:limit]
        if not selected:
            return ""

        sections: List[str] = []
        for h in selected:
            if h.is_hydrated and h.hydrated_content:
                sections.append(
                    f"### [JIT HYDRATED REFERENCE: {h.title} ({h.handle_id})]\n"
                    f"Source: {h.full_reference_pointer}\n\n"
                    f"{h.hydrated_content}"
                )
            else:
                sections.append(
                    f"- [JIT Ref: {h.handle_id}] **{h.title}**: {h.summary} "
                    f"`(Source: {h.full_reference_pointer} | Un-hydrated)`"
                )

        return "\n\n".join(sections)

    def total_handles(self) -> int:
        """Return total count of registered JIT handles."""
        return len(self._handles)

    def hydrated_count(self) -> int:
        """Return count of currently hydrated handles."""
        return sum(1 for h in self._handles.values() if h.is_hydrated)
