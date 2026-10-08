"""Collapses multi-generation compacted or branched session continuations.

[INPUT]
- toolkits.memory.lineage_search.models::RawSearchHit, SessionMeta (POS: Types and models for lineage search.)

[OUTPUT]
- LineageDeduplicator: Collapses multi-generation compacted or branched session continuations.

[POS]
Collapses multi-generation compacted or branched session continuations.
"""

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.lineage_search.models import (
    RawSearchHit,
    SessionMeta,
)


class LineageDeduplicator:
    """Collapses multi-generation compacted or branched session continuations

    into a single canonical representative per lineage tree.
    Prevents repetitive historical anchor pollution from dominating search output.
    """

    def __init__(self) -> None:
        pass

    def deduplicate(
        self,
        hits: Sequence[RawSearchHit],
        session_metas: dict[str, SessionMeta],
        limit: int = 10,
    ) -> list[tuple[RawSearchHit, str]]:
        """Deduplicate hits by canonical lineage root ID while preserving precedence.

        Returns list of (surviving_hit, lineage_root_id).
        """
        seen_lineage_roots: set[str] = set()
        deduped: list[tuple[RawSearchHit, str]] = []

        for hit in hits:
            meta = session_metas.get(hit.session_id)
            lineage_root = meta.effective_lineage_root() if meta else hit.session_id

            if lineage_root in seen_lineage_roots:
                continue

            seen_lineage_roots.add(lineage_root)
            deduped.append((hit, lineage_root))

            if len(deduped) >= limit:
                break

        return deduped
