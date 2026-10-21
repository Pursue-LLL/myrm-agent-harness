"""[INPUT] Media assets, diagnostic execution steps, and Golden Eval tagging requests.
[OUTPUT] Thread-safe manager decoupling binary media from trace spans, lifecycle tracking, and eval pinning.
[POS] myrm_agent_harness.observability.multimodal_trace.manager

Thread-safe registry for multimodal media references and 3-step diagnostic traces:
1. Replaces bulky Base64 payloads with lightweight references.
2. Tracks 4-state media visibility (ready, uploading, expired, purged).
3. Provides Golden Eval pinning with retention lock preventing sandbox volume cleanup.
"""

from collections import defaultdict
import threading
import time

from .models import (
    MediaModality,
    MediaReference,
    MediaVisibilityState,
    MultimodalStepType,
    MultimodalTraceRecord,
    MultimodalTraceStep,
)


class MultimodalTraceManager:
    """Thread-safe manager for multimodal media references and diagnostic trace spans."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._media_refs: dict[str, MediaReference] = {}
        self._traces: dict[str, MultimodalTraceRecord] = {}

    def register_media(
        self,
        media_id: str,
        uri: str,
        modality: MediaModality | str,
        mime_type: str,
        file_size_bytes: int,
        sha256_hash: str,
        presigned_preview_url: str = "",
        visibility_state: MediaVisibilityState | str = MediaVisibilityState.READY,
    ) -> MediaReference:
        """Register a lightweight media reference decoupled from heavy binary content."""
        clean_id = media_id.strip()
        resolved_modality: MediaModality
        if isinstance(modality, MediaModality):
            resolved_modality = modality
        else:
            try:
                resolved_modality = MediaModality(modality.strip().lower())
            except ValueError:
                resolved_modality = MediaModality.IMAGE

        resolved_visibility: MediaVisibilityState
        if isinstance(visibility_state, MediaVisibilityState):
            resolved_visibility = visibility_state
        else:
            try:
                resolved_visibility = MediaVisibilityState(visibility_state.strip().lower())
            except ValueError:
                resolved_visibility = MediaVisibilityState.READY

        ref = MediaReference(
            media_id=clean_id,
            uri=uri.strip(),
            modality=resolved_modality,
            mime_type=mime_type.strip(),
            file_size_bytes=max(0, file_size_bytes),
            sha256_hash=sha256_hash.strip(),
            visibility_state=resolved_visibility,
            presigned_preview_url=presigned_preview_url.strip(),
            created_at_ms=int(time.time() * 1000),
        )

        with self._lock:
            self._media_refs[clean_id] = ref

        return ref

    def update_media_visibility(
        self,
        media_id: str,
        visibility_state: MediaVisibilityState | str,
        presigned_preview_url: str | None = None,
    ) -> bool:
        """Update 4-state visibility lifecycle or refresh presigned temporary URL."""
        clean_id = media_id.strip()
        with self._lock:
            existing = self._media_refs.get(clean_id)
            if existing is None:
                return False

            resolved_visibility: MediaVisibilityState
            if isinstance(visibility_state, MediaVisibilityState):
                resolved_visibility = visibility_state
            else:
                try:
                    resolved_visibility = MediaVisibilityState(visibility_state.strip().lower())
                except ValueError:
                    resolved_visibility = existing.visibility_state

            new_url = presigned_preview_url if presigned_preview_url is not None else existing.presigned_preview_url

            updated = MediaReference(
                media_id=existing.media_id,
                uri=existing.uri,
                modality=existing.modality,
                mime_type=existing.mime_type,
                file_size_bytes=existing.file_size_bytes,
                sha256_hash=existing.sha256_hash,
                visibility_state=resolved_visibility,
                presigned_preview_url=new_url,
                created_at_ms=existing.created_at_ms,
            )
            self._media_refs[clean_id] = updated

            # Synchronize into existing traces containing this media reference
            for tid, trace in list(self._traces.items()):
                matched = False
                new_refs: list[MediaReference] = []
                for r in trace.media_references:
                    if r.media_id == clean_id:
                        new_refs.append(updated)
                        matched = True
                    else:
                        new_refs.append(r)
                if matched:
                    self._traces[tid] = MultimodalTraceRecord(
                        trace_id=trace.trace_id,
                        session_id=trace.session_id,
                        prompt_summary=trace.prompt_summary,
                        media_references=tuple(new_refs),
                        steps=trace.steps,
                        pinned_for_golden_eval=trace.pinned_for_golden_eval,
                        golden_eval_category=trace.golden_eval_category,
                        created_at_ms=trace.created_at_ms,
                    )

            return True

    def get_media_reference(self, media_id: str) -> MediaReference | None:
        """Fetch media reference by ID."""
        with self._lock:
            return self._media_refs.get(media_id.strip())

    def record_trace(
        self,
        trace_id: str,
        session_id: str,
        prompt_summary: str,
        media_ids: tuple[str, ...] | list[str] = (),
        steps: tuple[MultimodalTraceStep, ...] | list[MultimodalTraceStep] = (),
    ) -> MultimodalTraceRecord:
        """Record an end-to-end multimodal execution trace."""
        clean_tid = trace_id.strip()
        clean_sid = session_id.strip()

        with self._lock:
            attached_refs: list[MediaReference] = []
            for mid in media_ids:
                ref = self._media_refs.get(mid.strip())
                if ref is not None:
                    attached_refs.append(ref)

            record = MultimodalTraceRecord(
                trace_id=clean_tid,
                session_id=clean_sid,
                prompt_summary=prompt_summary.strip(),
                media_references=tuple(attached_refs),
                steps=tuple(steps),
                pinned_for_golden_eval=False,
                golden_eval_category="",
                created_at_ms=int(time.time() * 1000),
            )
            self._traces[clean_tid] = record

        return record

    def pin_trace_for_golden_eval(
        self,
        trace_id: str,
        category: str = "visual_regression",
    ) -> bool:
        """Lock trace and its media references against TTL purging and mark as Golden Eval sample."""
        clean_tid = trace_id.strip()
        with self._lock:
            existing = self._traces.get(clean_tid)
            if existing is None:
                return False

            updated = MultimodalTraceRecord(
                trace_id=existing.trace_id,
                session_id=existing.session_id,
                prompt_summary=existing.prompt_summary,
                media_references=existing.media_references,
                steps=existing.steps,
                pinned_for_golden_eval=True,
                golden_eval_category=category.strip() or "visual_regression",
                created_at_ms=existing.created_at_ms,
            )
            self._traces[clean_tid] = updated
            return True

    def get_trace(self, trace_id: str) -> MultimodalTraceRecord | None:
        """Fetch full trace details by ID."""
        with self._lock:
            return self._traces.get(trace_id.strip())

    def list_traces(
        self,
        session_id: str | None = None,
        modality: MediaModality | str | None = None,
        pinned_only: bool = False,
        limit: int = 50,
    ) -> list[MultimodalTraceRecord]:
        """Query traces with filtering support."""
        with self._lock:
            results = list(self._traces.values())

        if session_id:
            results = [t for t in results if t.session_id == session_id.strip()]

        if modality:
            mod_val = modality.value if isinstance(modality, MediaModality) else modality.strip().lower()
            results = [t for t in results if any(m.modality.value == mod_val for m in t.media_references)]

        if pinned_only:
            results = [t for t in results if t.pinned_for_golden_eval]

        results.sort(key=lambda t: t.created_at_ms, reverse=True)
        return results[: max(1, limit)]

    def reset(self) -> None:
        """Clear all in-memory traces and media records."""
        with self._lock:
            self._media_refs.clear()
            self._traces.clear()


# Global thread-safe singleton
_default_manager: MultimodalTraceManager | None = None
_manager_lock = threading.Lock()


def get_default_multimodal_trace_manager() -> MultimodalTraceManager:
    """Retrieve or initialize the global MultimodalTraceManager instance."""
    global _default_manager
    if _default_manager is None:
        with _manager_lock:
            if _default_manager is None:
                _default_manager = MultimodalTraceManager()
    return _default_manager
