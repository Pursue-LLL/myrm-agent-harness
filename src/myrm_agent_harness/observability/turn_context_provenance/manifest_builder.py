"""
[INPUT]: Raw chunk contents, source IDs, kinds, session/turn IDs, and model snapshots.
[OUTPUT]: Built TurnContextInjectionManifest and diff items via TurnContextManifestBuilder.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/turn_context_provenance/manifest_builder.py
"""

from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional, Tuple

from .models import (
    InjectionSourceKind,
    TurnContextChunk,
    TurnContextInjectionManifest,
    TurnProvenanceDiffItem,
)


class TurnContextManifestBuilder:
    """Builder for constructing turn-level injection manifests and diffing reproducibility snapshots."""

    def __init__(self) -> None:
        self._raw_chunks: List[Tuple[str, InjectionSourceKind, str, Optional[int], Dict[str, str]]] = []

    def add_chunk(
        self,
        source_id: str,
        kind: InjectionSourceKind,
        content: str,
        estimated_tokens: Optional[int] = None,
        meta: Optional[Dict[str, str]] = None,
    ) -> "TurnContextManifestBuilder":
        """Add a source chunk to the turn injection assembly queue."""
        self._raw_chunks.append(
            (source_id, kind, content, estimated_tokens, meta or {})
        )
        return self

    def build(
        self,
        session_id: str,
        turn_id: str,
        model_snapshot_id: str = "claude-3-7-sonnet-20250219",
    ) -> TurnContextInjectionManifest:
        """Build the immutable TurnContextInjectionManifest with SHA256 fingerprints."""
        chunks: List[TurnContextChunk] = []
        total_tokens = 0
        total_chars = 0

        for idx, (source_id, kind, content, est_tokens, meta) in enumerate(self._raw_chunks):
            content_chars = len(content)
            sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            tokens = est_tokens if est_tokens is not None else max(1, content_chars // 4)

            total_tokens += tokens
            total_chars += content_chars

            chunk = TurnContextChunk(
                chunk_id=f"{turn_id}_chunk_{idx}",
                source_id=source_id,
                kind=kind,
                content_sha256=sha256,
                content_chars=content_chars,
                estimated_tokens=tokens,
                order_index=idx,
                meta=meta,
            )
            chunks.append(chunk)

        created_at = datetime.now(timezone.utc).isoformat()

        return TurnContextInjectionManifest(
            session_id=session_id,
            turn_id=turn_id,
            chunks=chunks,
            total_tokens=total_tokens,
            total_chars=total_chars,
            model_snapshot_id=model_snapshot_id,
            created_at=created_at,
        )

    @staticmethod
    def diff_manifests(
        previous: TurnContextInjectionManifest,
        current: TurnContextInjectionManifest,
    ) -> List[TurnProvenanceDiffItem]:
        """Compute the minimal injection delta and provenance diff across two turns."""
        prev_map: Dict[str, TurnContextChunk] = {c.source_id: c for c in previous.chunks}
        curr_map: Dict[str, TurnContextChunk] = {c.source_id: c for c in current.chunks}

        diffs: List[TurnProvenanceDiffItem] = []
        all_source_ids = list(dict.fromkeys(list(prev_map.keys()) + list(curr_map.keys())))

        for sid in all_source_ids:
            p_chunk = prev_map.get(sid)
            c_chunk = curr_map.get(sid)

            if p_chunk is None and c_chunk is not None:
                diffs.append(
                    TurnProvenanceDiffItem(
                        source_id=sid,
                        kind=c_chunk.kind,
                        diff_type="ADDED",
                        previous_sha256=None,
                        current_sha256=c_chunk.content_sha256,
                        token_delta=c_chunk.estimated_tokens,
                    )
                )
            elif p_chunk is not None and c_chunk is None:
                diffs.append(
                    TurnProvenanceDiffItem(
                        source_id=sid,
                        kind=p_chunk.kind,
                        diff_type="REMOVED",
                        previous_sha256=p_chunk.content_sha256,
                        current_sha256=None,
                        token_delta=-p_chunk.estimated_tokens,
                    )
                )
            elif p_chunk is not None and c_chunk is not None:
                delta = c_chunk.estimated_tokens - p_chunk.estimated_tokens
                if p_chunk.content_sha256 != c_chunk.content_sha256:
                    diff_type = "MODIFIED"
                else:
                    diff_type = "UNCHANGED"

                diffs.append(
                    TurnProvenanceDiffItem(
                        source_id=sid,
                        kind=c_chunk.kind,
                        diff_type=diff_type,
                        previous_sha256=p_chunk.content_sha256,
                        current_sha256=c_chunk.content_sha256,
                        token_delta=delta,
                    )
                )

        return diffs
